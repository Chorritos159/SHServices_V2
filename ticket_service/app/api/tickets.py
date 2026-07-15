from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from app.models.schemas import (
    TicketCreate, TicketResponse, TicketPendiente, EstadoUpdate,
    DiagnosticarRequest, GarantiaOut,
)
from app.models.ticket import TicketDB
from app.models.garantia import GarantiaDB
from app.core.database import get_db
from app.core.logger import get_logger
from app.core.rabbitmq import publicar_evento
import uuid
import json
import httpx
from datetime import datetime, timedelta

router = APIRouter()
logger = get_logger("ticket_service")

# URL interna del almacén (red Docker). El ticket_service orquesta el stock aquí.
ALMACEN_URL = "http://almacen-service:80/api/v1/almacen"
DIAS_GARANTIA = 90  # regla de negocio estricta: 90 días exactos

# Transiciones legales de la máquina de estados (centralizada en el backend).
TRANSICIONES = {
    "EN_COLA": {"EN_DIAGNOSTICO", "DIAGNOSTICADO", "RECHAZADO"},
    "EN_DIAGNOSTICO": {"DIAGNOSTICADO", "RECHAZADO"},
    "DIAGNOSTICADO": {"ENTREGADO", "RECHAZADO"},
    "VENTA_REGISTRADA": {"ENTREGADO"},
}


def _validar_transicion(actual: str, destino: str):
    if destino not in TRANSICIONES.get(actual, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Transición ilegal: {actual} → {destino}.",
        )


async def _mover_stock(operacion: str, repuestos: list[dict], sede: str, correlation_id: str):
    """Llama al almacén para confirmar/liberar cada repuesto reservado del ticket."""
    if not repuestos:
        return
    async with httpx.AsyncClient() as client:
        for r in repuestos:
            try:
                await client.post(
                    f"{ALMACEN_URL}/{operacion}",
                    json={"codigo_producto": r["codigo_producto"], "cantidad": r["cantidad"], "sede": sede},
                    headers={"x-correlation-id": correlation_id},
                    timeout=5.0,
                )
            except httpx.RequestError:
                logger.error(f"No se pudo {operacion} stock de {r['codigo_producto']} (almacén inaccesible).")

@router.post("/", response_model=TicketResponse, status_code=201)
async def crear_ticket(
    ticket: TicketCreate, 
    request: Request, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)  # Inyectamos la base de datos aquí
):
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id

    # IDENTIDAD desde el token (inyectada por el Gateway). Ya NO viene en el body.
    sede = request.headers.get("x-user-sede", "").upper()
    usuario = request.headers.get("x-user-sub", "desconocido")
    if not sede:
        raise HTTPException(status_code=401, detail="Falta la sede en el token (cabecera X-User-Sede).")

    if ticket.tipoOperacion == "SOPORTE" and (not ticket.equipo or not ticket.caracteristicas_falla):
        raise HTTPException(status_code=422, detail="En SOPORTE, el equipo y la falla son obligatorios.")

    # 1. Preparar los datos (la sede sale del token, no del cliente)
    ticket_id = f"TICK-{sede[:3]}-{str(uuid.uuid4())[:4].upper()}"
    estado_inicial = "EN_COLA" if ticket.tipoOperacion == "SOPORTE" else "VENTA_REGISTRADA"

    # 2. Guardar en PostgreSQL
    nuevo_ticket_db = TicketDB(
        id=ticket_id,
        datos_cliente=ticket.datosCliente,
        documento_cliente=ticket.documento_cliente,
        telefono_cliente=ticket.telefono_cliente,
        tipo_operacion=ticket.tipoOperacion,
        datos_equipo=ticket.equipo,            # espejo legado
        equipo=ticket.equipo,
        numero_serie=ticket.numero_serie,
        caracteristicas_falla=ticket.caracteristicas_falla,
        precio_estimado=ticket.precio_estimado,
        sede=sede,
        usuario_registro=usuario,
        prioridad=ticket.prioridad,
        estado=estado_inicial
    )
    db.add(nuevo_ticket_db)
    db.commit()
    db.refresh(nuevo_ticket_db)
    logger.info(f"💾 Ticket {ticket_id} guardado (sede {sede}, por {usuario}).")

    # 3. Disparar el Evento a RabbitMQ
    evento_payload = {
        "evento": "TicketCreado.v1",
        "trace_id": correlation_id,
        "datos": {"idTicket": ticket_id, "sede": sede}
    }
    background_tasks.add_task(
        publicar_evento, exchange_name="tickets.eventos", routing_key="ticket.creado", mensaje=evento_payload
    )

    return TicketResponse(
        idTicket=ticket_id,
        estadoInicial=estado_inicial,
        fechaRegistro=nuevo_ticket_db.fecha_registro.isoformat() + "Z",
        tipoOperacionRegistrada=ticket.tipoOperacion
    )


@router.get("/pendientes", response_model=list[TicketPendiente], tags=["Tickets"])
async def listar_pendientes(request: Request, db: Session = Depends(get_db)):
    """
    Lista los tickets EN_COLA (la bandeja del técnico).

    Nota: es una ruta fija (no ?estado=...) a propósito, porque el API Gateway
    descarta los query strings al reenviar. Así el filtro viaja en la ruta.
    """
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id

    tickets = (
        db.query(TicketDB)
        .filter(TicketDB.estado == "EN_COLA")
        .order_by(TicketDB.fecha_registro)
        .all()
    )
    logger.info(f"📋 Tickets pendientes (EN_COLA) solicitados: {len(tickets)}.")
    return tickets


@router.get("/", response_model=list[TicketPendiente], tags=["Tickets"])
async def listar_tickets(request: Request, db: Session = Depends(get_db)):
    """Lista TODOS los tickets (más recientes primero)."""
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    tickets = db.query(TicketDB).order_by(TicketDB.fecha_registro.desc()).all()
    return tickets


@router.get("/por-estado/{estado}", response_model=list[TicketPendiente], tags=["Tickets"])
async def listar_por_estado(estado: str, request: Request, db: Session = Depends(get_db)):
    """
    Filtra tickets por estado (ej. DIAGNOSTICADO para la bandeja de Entregas y Cobros).
    Filtro por RUTA (no ?query) porque el Gateway descarta los query strings.
    """
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    tickets = (
        db.query(TicketDB)
        .filter(TicketDB.estado == estado.upper())
        .order_by(TicketDB.fecha_registro.desc())
        .all()
    )
    logger.info(f"📋 Tickets en estado '{estado.upper()}': {len(tickets)}.")
    return tickets


@router.patch("/{ticket_id}", response_model=TicketPendiente, tags=["Tickets"])
async def actualizar_estado(
    ticket_id: str,
    cambio: EstadoUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Actualiza el estado de un ticket (ej. tras el diagnóstico: EN_COLA → DIAGNOSTICADO)."""
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id

    ticket = db.query(TicketDB).filter(TicketDB.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")

    ticket.estado = cambio.estado
    db.commit()
    db.refresh(ticket)
    logger.info(f"🔄 Ticket {ticket_id} actualizado a estado '{cambio.estado}'.")
    return ticket


# ─────────────────────────────────────────────────────────────────────────
# MÁQUINA DE ESTADOS (centralizada en el backend). Cada transición valida que
# sea legal y dispara los efectos de stock/garantía correspondientes.
# ─────────────────────────────────────────────────────────────────────────

def _obtener_ticket(db: Session, ticket_id: str) -> TicketDB:
    ticket = db.query(TicketDB).filter(TicketDB.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")
    return ticket


@router.post("/{ticket_id}/tomar", response_model=TicketPendiente, tags=["Máquina de Estados"])
async def tomar_ticket(ticket_id: str, request: Request, db: Session = Depends(get_db)):
    """EN_COLA → EN_DIAGNOSTICO (el técnico toma la atención)."""
    logger.extra["correlation_id"] = request.headers.get("x-correlation-id", "N/A")
    ticket = _obtener_ticket(db, ticket_id)
    _validar_transicion(ticket.estado, "EN_DIAGNOSTICO")
    ticket.estado = "EN_DIAGNOSTICO"
    db.commit(); db.refresh(ticket)
    return ticket


@router.post("/{ticket_id}/diagnosticar", response_model=TicketPendiente, tags=["Máquina de Estados"])
async def diagnosticar_ticket(
    ticket_id: str, datos: DiagnosticarRequest, request: Request, db: Session = Depends(get_db)
):
    """
    → DIAGNOSTICADO. Registra en el ticket los repuestos reservados (el stock ya
    lo reservó el diagnostico_service) para poder CONFIRMAR/LIBERAR luego.
    """
    logger.extra["correlation_id"] = request.headers.get("x-correlation-id", "N/A")
    ticket = _obtener_ticket(db, ticket_id)
    _validar_transicion(ticket.estado, "DIAGNOSTICADO")
    ticket.repuestos_reservados = json.dumps([r.model_dump() for r in datos.repuestos])
    ticket.estado = "DIAGNOSTICADO"
    db.commit(); db.refresh(ticket)
    logger.info(f"🩺 Ticket {ticket_id} → DIAGNOSTICADO ({len(datos.repuestos)} repuesto(s) reservado(s)).")
    return ticket


@router.post("/{ticket_id}/rechazar", response_model=TicketPendiente, tags=["Máquina de Estados"])
async def rechazar_ticket(ticket_id: str, request: Request, db: Session = Depends(get_db)):
    """→ RECHAZADO. El cliente no aceptó: LIBERA el stock reservado (vuelve a disponible)."""
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    ticket = _obtener_ticket(db, ticket_id)
    _validar_transicion(ticket.estado, "RECHAZADO")

    repuestos = json.loads(ticket.repuestos_reservados or "[]")
    await _mover_stock("liberar", repuestos, ticket.sede, correlation_id)

    ticket.estado = "RECHAZADO"
    db.commit(); db.refresh(ticket)
    logger.info(f"🚫 Ticket {ticket_id} → RECHAZADO. Stock liberado.")
    return ticket


@router.post("/{ticket_id}/entregar", tags=["Máquina de Estados"])
async def entregar_ticket(ticket_id: str, request: Request, db: Session = Depends(get_db)):
    """
    → ENTREGADO. Se cobró y se entrega: CONFIRMA (consume) el stock reservado y,
    si es SOPORTE, genera automáticamente una GARANTÍA de 90 días exactos.
    """
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    ticket = _obtener_ticket(db, ticket_id)
    _validar_transicion(ticket.estado, "ENTREGADO")

    # Confirma (consume) los repuestos reservados en el diagnóstico.
    repuestos = json.loads(ticket.repuestos_reservados or "[]")
    await _mover_stock("confirmar", repuestos, ticket.sede, correlation_id)

    ticket.estado = "ENTREGADO"

    garantia_out = None
    if ticket.tipo_operacion == "SOPORTE":
        ahora = datetime.utcnow()
        garantia = GarantiaDB(
            id=f"GAR-{ticket.sede[:3]}-{str(uuid.uuid4())[:4].upper()}",
            id_ticket=ticket.id,
            documento_cliente=ticket.documento_cliente,
            equipo=ticket.equipo,
            numero_serie=ticket.numero_serie,
            descripcion=ticket.caracteristicas_falla,
            fecha_entrega=ahora,
            fecha_vencimiento=ahora + timedelta(days=DIAS_GARANTIA),
            dias=DIAS_GARANTIA,
        )
        db.add(garantia)
        garantia_out = {"id": garantia.id, "fecha_vencimiento": garantia.fecha_vencimiento.isoformat() + "Z", "dias": DIAS_GARANTIA}

    db.commit()
    logger.info(f"📦 Ticket {ticket_id} → ENTREGADO. Stock confirmado. Garantía: {garantia_out}")
    return {"id": ticket.id, "estado": "ENTREGADO", "garantia": garantia_out}


# ─────────────────────────────────────────────────────────────────────────
# CONSULTA DE GARANTÍAS (Recepción / Admin)
# ─────────────────────────────────────────────────────────────────────────

def _garantia_out(g: GarantiaDB) -> dict:
    ahora = datetime.utcnow()
    restantes = (g.fecha_vencimiento - ahora).days
    return {
        "id": g.id, "id_ticket": g.id_ticket, "documento_cliente": g.documento_cliente,
        "equipo": g.equipo, "numero_serie": g.numero_serie, "descripcion": g.descripcion,
        "fecha_entrega": g.fecha_entrega, "fecha_vencimiento": g.fecha_vencimiento, "dias": g.dias,
        "vigente": g.fecha_vencimiento >= ahora, "dias_restantes": max(restantes, 0),
    }


@router.get("/garantias", response_model=list[GarantiaOut], tags=["Garantías"])
async def listar_garantias(request: Request, db: Session = Depends(get_db)):
    """Lista todas las garantías con su vigencia (para Recepción y Admin)."""
    logger.extra["correlation_id"] = request.headers.get("x-correlation-id", "N/A")
    garantias = db.query(GarantiaDB).order_by(GarantiaDB.fecha_entrega.desc()).all()
    return [_garantia_out(g) for g in garantias]


@router.get("/garantias/por-documento/{documento}", response_model=list[GarantiaOut], tags=["Garantías"])
async def garantias_por_documento(documento: str, request: Request, db: Session = Depends(get_db)):
    """Busca garantías por DNI/RUC del cliente (para verificar si un equipo vuelve en garantía)."""
    logger.extra["correlation_id"] = request.headers.get("x-correlation-id", "N/A")
    garantias = (
        db.query(GarantiaDB)
        .filter(GarantiaDB.documento_cliente == documento)
        .order_by(GarantiaDB.fecha_entrega.desc())
        .all()
    )
    return [_garantia_out(g) for g in garantias]
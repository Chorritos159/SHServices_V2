from typing import Annotated
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models.schemas import (
    TicketCreate, TicketResponse, TicketPendiente, EstadoUpdate,
    DiagnosticarRequest, EntregarRequest,
)
from app.models.ticket import TicketDB
from app.models.idempotencia import IdempotenciaDB
from app.core.database import get_db
from app.core.logger import get_logger
from app.core.rabbitmq import publicar_evento
import uuid
import json
import httpx
import time
from datetime import datetime, timedelta

router = APIRouter()
# Centinela: clave reservada pero con el trabajo aun sin terminar.
IDEM_EN_CURSO = -1

logger = get_logger("ticket-service")   # con guion, como los otros 8 servicios

# URL interna del almacén (red Docker). El ticket_service orquesta el stock aquí.
ALMACEN_URL = "http://almacen-service:80/api/v1/almacen"

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
            detail=f"Transición ilegal: {actual} -> {destino}.",
        )


async def _mover_stock(operacion: str, repuestos: list[dict], sede: str,
                       correlation_id: str, id_ticket: str = "") -> list[str]:
    """Llama al almacén para confirmar/liberar cada repuesto del ticket.

    Devuelve la lista de repuestos que NO se pudieron mover, para que quien
    llama decida. Antes solo capturaba `RequestError` (fallo de conexión) e
    IGNORABA las respuestas de error: si almacén contestaba 409 o 500, el
    ticket se cerraba igual y el stock se quedaba reservado para siempre —
    justo el sintoma de "el ticket desaparecio pero el stock sigue reservado".
    """
    if not repuestos:
        return []
    fallidos: list[str] = []
    async with httpx.AsyncClient() as client:
        for r in repuestos:
            codigo = r["codigo_producto"]
            try:
                resp = await client.post(
                    f"{ALMACEN_URL}/{operacion}",
                    json={"codigo_producto": codigo, "cantidad": r["cantidad"], "sede": sede},
                    headers={
                        "x-correlation-id": correlation_id,
                        # Derivada: un reintento no mueve el stock dos veces.
                        "Idempotency-Key": f"{operacion}-{id_ticket}-{codigo}",
                    },
                    timeout=5.0,
                )
                if resp.status_code >= 400:
                    fallidos.append(codigo)
                    logger.error(
                        f"almacen respondio {resp.status_code} al {operacion} "
                        f"{codigo}: {resp.text[:120]}")
            except httpx.RequestError as exc:
                fallidos.append(codigo)
                logger.error(f"No se pudo {operacion} stock de {codigo} (almacen inaccesible): {exc}")
    return fallidos

@router.post("/", response_model=TicketResponse, status_code=201)
async def crear_ticket(
    ticket: TicketCreate, 
    request: Request, 
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)]  # Inyectamos la base de datos aquí
):
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    inicio = time.monotonic()

    # IDENTIDAD desde el token (inyectada por el Gateway). Ya NO viene en el body.
    sede = request.headers.get("x-user-sede", "").upper()
    usuario = request.headers.get("x-user-sub", "desconocido")
    if not sede:
        raise HTTPException(status_code=401, detail="Falta la sede en el token (cabecera X-User-Sede).")

    if ticket.tipoOperacion == "SOPORTE" and (not ticket.equipo or not ticket.caracteristicas_falla):
        raise HTTPException(status_code=422, detail="En SOPORTE, el equipo y la falla son obligatorios.")

    # Idempotencia (S34, Idempotency-Key): a diferencia de facturas, un ticket
    # NO tiene clave natural (el mismo cliente puede traer el mismo equipo en
    # visitas distintas y legítimas) — se necesita un token opaco por intento
    # de envío. Si el cliente lo manda y ya se procesó, se devuelve la MISMA
    # respuesta sin crear un ticket nuevo. Si no lo manda, se comporta como
    # antes (sin deduplicar) — el header es opt-in.
    # La clave se RESERVA antes de crear nada, no se comprueba y luego se
    # guarda. Comprobar-y-luego-actuar NO es atomico: cuando el circuito abre,
    # el Gateway reintenta hasta 4 veces con la MISMA clave, y los reintentos
    # entraban antes de que el primero llegara a registrarla. Resultado medido:
    # el tercer envio creaba 4 tickets, uno por intento del retry.
    #
    # Con el INSERT primero, el indice unico de PostgreSQL arbitra: solo UNA
    # peticion consigue la clave y las demas chocan con IntegrityError, que es
    # la senal de que otro ya se encargo.
    clave_idem = request.headers.get("idempotency-key")
    if clave_idem:
        try:
            db.add(IdempotenciaDB(
                clave=clave_idem, operacion="crear_ticket",
                status_code=IDEM_EN_CURSO, respuesta_json="{}",
            ))
            db.commit()
        except IntegrityError:
            db.rollback()
            previo = db.query(IdempotenciaDB).filter(
                IdempotenciaDB.clave == clave_idem).first()
            if previo is not None and previo.status_code != IDEM_EN_CURSO:
                logger.info(
                    f"Idempotency-Key '{clave_idem}' ya procesada; se devuelve la respuesta original.",
                    extra={"campos": {"operation": "crear_ticket", "event": "TicketCreado.v1",
                                      "result": "duplicado"}},
                )
                return JSONResponse(status_code=previo.status_code,
                                    content=json.loads(previo.respuesta_json))
            if previo is not None:
                # El gemelo sigue trabajando: 409 y no un ticket duplicado.
                raise HTTPException(
                    status_code=409,
                    detail="Ese mismo registro se esta procesando ahora mismo; espera el resultado.",
                )

    # 1. Preparar los datos (la sede sale del token, no del cliente)
    estado_inicial = "EN_COLA" if ticket.tipoOperacion == "SOPORTE" else "VENTA_REGISTRADA"

    # 2. Guardar en PostgreSQL.
    # El ID usaba solo 4 hex (65.536 combinaciones): bajo carga concurrente
    # chocaban por la paradoja del cumpleanos y salia un 500 (UniqueViolation).
    # Ahora: 8 hex (4.300 millones) + reintento con ID nuevo si aun asi colisiona.
    nuevo_ticket_db = None
    for intento in range(1, 6):
        ticket_id = f"TICK-{sede[:3]}-{uuid.uuid4().hex[:12].upper()}"
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
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            if intento == 5:
                logger.error(
                    "No se pudo generar un ID de ticket libre tras 5 intentos.",
                    extra={"campos": {"operation": "crear_ticket", "result": "error"}},
                )
                raise HTTPException(
                    status_code=503,
                    detail="No se pudo registrar el ticket por alta concurrencia. Intentalo de nuevo.",
                )
    db.refresh(nuevo_ticket_db)
    duracion_ms = round((time.monotonic() - inicio) * 1000, 1)
    logger.info(
        f"Ticket {ticket_id} guardado (sede {sede}, por {usuario}).",
        extra={"campos": {"operation": "crear_ticket", "event": "TicketCreado.v1",
                           "result": "ok", "durationMs": duracion_ms, "idTicket": ticket_id}},
    )

    respuesta = TicketResponse(
        idTicket=ticket_id,
        estadoInicial=estado_inicial,
        fechaRegistro=nuevo_ticket_db.fecha_registro.isoformat() + "Z",
        tipoOperacionRegistrada=ticket.tipoOperacion
    )

    # Completa la clave YA RESERVADA con la respuesta real, para que los
    # reintentos posteriores la devuelvan en vez de crear otro ticket.
    if clave_idem:
        try:
            fila = db.query(IdempotenciaDB).filter(
                IdempotenciaDB.clave == clave_idem).first()
            if fila is not None:
                fila.status_code = 201
                fila.respuesta_json = respuesta.model_dump_json()
                db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning(f"No se pudo cerrar la Idempotency-Key '{clave_idem}': {exc}")

    # 3. Disparar el Evento a RabbitMQ
    evento_payload = {
        "evento": "TicketCreado.v1",
        "trace_id": correlation_id,
        "datos": {"idTicket": ticket_id, "sede": sede, "estado": estado_inicial}
    }
    # Se SUELTA la conexion antes de encolar la tarea de fondo. FastAPI mantiene
    # viva la sesion de `get_db` hasta que TODAS las background tasks terminan:
    # si publicar en RabbitMQ tardaba, la conexion seguia retenida sin usarse y
    # el pool se agotaba bajo carga. La respuesta ya esta construida, asi que
    # cerrar aqui no afecta a la serializacion.
    db.close()

    background_tasks.add_task(
        publicar_evento, exchange_name="tickets.eventos", routing_key="ticket.creado", mensaje=evento_payload
    )

    return respuesta


@router.get("/pendientes", response_model=list[TicketPendiente], tags=["Tickets"])
async def listar_pendientes(request: Request, db: Annotated[Session, Depends(get_db)], limite: int = Query(200, ge=1, le=500)):
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
        .limit(limite)
        .all()
    )
    logger.info(f"Tickets pendientes (EN_COLA) solicitados: {len(tickets)}.")
    return tickets


@router.get("/", response_model=list[TicketPendiente], tags=["Tickets"])
async def listar_tickets(request: Request, db: Annotated[Session, Depends(get_db)], limite: int = Query(200, ge=1, le=500)):
    """Lista TODOS los tickets (más recientes primero)."""
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    tickets = db.query(TicketDB).order_by(TicketDB.fecha_registro.desc()).limit(limite).all()
    return tickets


@router.get("/por-estado/{estado}", response_model=list[TicketPendiente], tags=["Tickets"])
async def listar_por_estado(estado: str, request: Request, db: Annotated[Session, Depends(get_db)], limite: int = Query(200, ge=1, le=500)):
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
        .limit(limite)
        .all()
    )
    logger.info(f"Tickets en estado '{estado.upper()}': {len(tickets)}.")
    return tickets


@router.patch("/{ticket_id}", response_model=TicketPendiente, tags=["Tickets"])
async def actualizar_estado(
    ticket_id: str,
    cambio: EstadoUpdate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    """Actualiza el estado de un ticket (ej. tras el diagnóstico: EN_COLA -> DIAGNOSTICADO)."""
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id

    ticket = db.query(TicketDB).filter(TicketDB.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado.")

    ticket.estado = cambio.estado
    db.commit()
    db.refresh(ticket)
    logger.info(f"Ticket {ticket_id} actualizado a estado '{cambio.estado}'.")
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
async def tomar_ticket(ticket_id: str, request: Request, db: Annotated[Session, Depends(get_db)]):
    """EN_COLA -> EN_DIAGNOSTICO (el técnico toma la atención)."""
    logger.extra["correlation_id"] = request.headers.get("x-correlation-id", "N/A")
    ticket = _obtener_ticket(db, ticket_id)
    _validar_transicion(ticket.estado, "EN_DIAGNOSTICO")
    ticket.estado = "EN_DIAGNOSTICO"
    db.commit(); db.refresh(ticket)
    return ticket


@router.post("/{ticket_id}/diagnosticar", response_model=TicketPendiente, tags=["Máquina de Estados"])
async def diagnosticar_ticket(
    ticket_id: str,
    datos: DiagnosticarRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
):
    """
    -> DIAGNOSTICADO. Registra en el ticket los repuestos reservados (el stock ya
    lo reservó el diagnostico_service) para poder CONFIRMAR/LIBERAR luego.
    Emite 'ticket.listo' para que Recepción (CAJA) sepa que ya se puede cobrar.
    """
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    ticket = _obtener_ticket(db, ticket_id)
    _validar_transicion(ticket.estado, "DIAGNOSTICADO")
    ticket.repuestos_reservados = json.dumps([r.model_dump() for r in datos.repuestos])
    ticket.estado = "DIAGNOSTICADO"
    db.commit(); db.refresh(ticket)
    logger.info(f"Ticket {ticket_id} -> DIAGNOSTICADO ({len(datos.repuestos)} repuesto(s) reservado(s)).")

    # Notifica a CAJA que el equipo está listo para cobro y entrega.
    evento_payload = {
        "evento": "TicketListo.v1",
        "trace_id": correlation_id,
        "datos": {"idTicket": ticket.id, "sede": ticket.sede},
    }
    background_tasks.add_task(
        publicar_evento, exchange_name="tickets.eventos",
        routing_key="ticket.listo", mensaje=evento_payload,
    )
    return ticket


@router.post("/{ticket_id}/rechazar", response_model=TicketPendiente, tags=["Máquina de Estados"])
async def rechazar_ticket(ticket_id: str, request: Request, db: Annotated[Session, Depends(get_db)]):
    """-> RECHAZADO. El cliente no aceptó: LIBERA el stock reservado (vuelve a disponible)."""
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    ticket = _obtener_ticket(db, ticket_id)
    _validar_transicion(ticket.estado, "RECHAZADO")

    repuestos = json.loads(ticket.repuestos_reservados or "[]")
    await _mover_stock("liberar", repuestos, ticket.sede, correlation_id)

    ticket.estado = "RECHAZADO"
    db.commit(); db.refresh(ticket)
    logger.info(f"Ticket {ticket_id} -> RECHAZADO. Stock liberado.")
    return ticket


@router.post("/{ticket_id}/entregar", tags=["Máquina de Estados"])
async def entregar_ticket(
    ticket_id: str,
    datos: EntregarRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    """
    -> ENTREGADO. Se cobró y se entrega: CONFIRMA (consume) el stock reservado y,
    si es SOPORTE, genera automáticamente una GARANTÍA de 90 días exactos, guardando
    el monto cobrado (que el BFF pasa desde la factura).
    """
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    ticket = _obtener_ticket(db, ticket_id)
    _validar_transicion(ticket.estado, "ENTREGADO")

    # Confirma (consume) los repuestos reservados en el diagnóstico.
    repuestos = json.loads(ticket.repuestos_reservados or "[]")
    fallidos = await _mover_stock("confirmar", repuestos, ticket.sede,
                                  correlation_id, ticket.id)
    if fallidos:
        # NO se cierra el ticket si el stock no salio: cerrarlo dejaria las
        # unidades reservadas sin dueno y sin forma de recuperarlas. Se
        # responde 503 para que el cliente reintente; el evento del cobro
        # tambien lo reintentara por su cuenta.
        raise HTTPException(
            status_code=503,
            detail=(f"No se pudo confirmar el stock de {', '.join(fallidos)} en almacen. "
                    "El ticket sigue abierto: reintenta la entrega en unos segundos."),
        )

    ticket.estado = "ENTREGADO"
    db.commit()

    # La GARANTIA ya NO se emite aqui: la emite facturacion-service junto con el
    # cobro (es parte del ciclo economico y asi sobrevive si tickets cae).
    logger.info(f"Ticket {ticket_id} -> ENTREGADO. Stock confirmado.")
    return {"id": ticket.id, "estado": "ENTREGADO"}


# La CONSULTA DE GARANTIAS se movio a facturacion-service
# (GET /api/v1/facturas/garantias). Motivo: la garantia nace del cobro y asi
# sigue disponible aunque el ticket-service este caido.

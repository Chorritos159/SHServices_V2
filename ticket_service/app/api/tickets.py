from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from app.models.schemas import TicketCreate, TicketResponse, TicketPendiente, EstadoUpdate
from app.models.ticket import TicketDB
from app.core.database import get_db
from app.core.logger import get_logger
from app.core.rabbitmq import publicar_evento
import uuid
from datetime import datetime

router = APIRouter()
logger = get_logger("ticket_service")

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

    if ticket.tipoOperacion == "SOPORTE" and not ticket.datosEquipo:
        raise HTTPException(status_code=422, detail="Se requiere especificar el equipo para soporte.")

    # 1. Preparar los datos (la sede sale del token, no del cliente)
    ticket_id = f"TICK-{sede[:3]}-{str(uuid.uuid4())[:4].upper()}"
    estado_inicial = "EN_COLA" if ticket.tipoOperacion == "SOPORTE" else "VENTA_REGISTRADA"

    # 2. Guardar en PostgreSQL
    nuevo_ticket_db = TicketDB(
        id=ticket_id,
        datos_cliente=ticket.datosCliente,
        tipo_operacion=ticket.tipoOperacion,
        datos_equipo=ticket.datosEquipo,
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
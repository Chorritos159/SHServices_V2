from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from app.models.schemas import TicketCreate, TicketResponse
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
    
    if ticket.tipoOperacion == "SOPORTE" and not ticket.datosEquipo:
        raise HTTPException(status_code=422, detail="Se requiere especificar el equipo para soporte.")

    # 1. Preparar los datos
    ticket_id = f"TICK-{ticket.sede[:3].upper()}-{str(uuid.uuid4())[:4].upper()}"
    estado_inicial = "EN_COLA" if ticket.tipoOperacion == "SOPORTE" else "VENTA_REGISTRADA"

    # 2. Guardar en PostgreSQL
    nuevo_ticket_db = TicketDB(
        id=ticket_id,
        datos_cliente=ticket.datosCliente,
        tipo_operacion=ticket.tipoOperacion,
        datos_equipo=ticket.datosEquipo,
        sede=ticket.sede,
        usuario_registro=ticket.usuarioRegistro,
        prioridad=ticket.prioridad,
        estado=estado_inicial
    )
    db.add(nuevo_ticket_db)
    db.commit()
    db.refresh(nuevo_ticket_db)
    logger.info(f"💾 Ticket {ticket_id} guardado físicamente en PostgreSQL.")

    # 3. Disparar el Evento a RabbitMQ
    evento_payload = {
        "evento": "TicketCreado.v1",
        "trace_id": correlation_id,
        "datos": {"idTicket": ticket_id, "sede": ticket.sede}
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
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_serializer
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Annotated, Optional
from datetime import datetime, timezone
import httpx

from app.core.database import get_db
from app.core.logger import get_logger, RECHAZADO, DUPLICADO
from app.core.rabbitmq import publicar_evento
from app.models.asignacion import AsignacionDB

router = APIRouter()
logger = get_logger("diagnostico-service")

# Ruta interna (red Docker) al ticket-service para la sincronización best-effort.
# El router de ticket-service se monta en /api/v1/tickets (una sola vez), así que
# la transición "tomar" queda en /api/v1/tickets/{id}/tomar.
TICKET_SERVICE_URL = "http://ticket-service:80/api/v1/tickets"


async def _sincronizar_ticket_tomado(id_ticket: str, tecnico: str, sede: str, correlation_id: str):
    """Avisa al ticket-service que el ticket fue tomado (EN_COLA -> EN_DIAGNOSTICO).

    Se ejecuta en segundo plano (best-effort): la asignación ya quedó guardada de
    forma autoritativa en diagnostico-service, así que si el ticket-service está
    caído esto simplemente se pierde sin afectar al técnico. Cuando el
    ticket-service esté sano, el estado se sincroniza; si no, el ticket sigue
    EN_COLA pero la exclusividad la garantiza igualmente la tabla de asignaciones.
    """
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{TICKET_SERVICE_URL}/{id_ticket}/tomar",
                headers={"x-correlation-id": correlation_id,
                         "x-user-sub": tecnico, "x-user-sede": sede},
                timeout=3.0,
            )
    except httpx.HTTPError as exc:
        logger.warning(
            f"No se pudo sincronizar el estado en ticket-service ({type(exc).__name__}); "
            f"la asignacion de {id_ticket} quedo guardada igual.",
            extra={"campos": {"operation": "tomar_ticket", "event": "TicketTomado.v1",
                              "result": "ticket_sync_diferido", "idTicket": id_ticket}},
        )


# ── Contratos ─────────────────────────────────────────────────────────────
class TomarTicketRequest(BaseModel):
    """Datos del ticket que el frontend YA tiene (de la cola) y envía al tomarlo.

    Se cachean aquí para que 'Mis Tickets' no tenga que consultar al
    ticket-service. Solo `id_ticket` es obligatorio (es la clave de exclusividad).
    """
    id_ticket: str
    datos_cliente: Optional[str] = None
    documento_cliente: Optional[str] = None
    telefono_cliente: Optional[str] = None
    tipo_operacion: Optional[str] = None
    equipo: Optional[str] = None
    numero_serie: Optional[str] = None
    caracteristicas_falla: Optional[str] = None
    prioridad: Optional[str] = None


class AsignacionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_ticket: str
    tecnico: str
    sede: str
    estado: str
    datos_cliente: Optional[str] = None
    documento_cliente: Optional[str] = None
    telefono_cliente: Optional[str] = None
    tipo_operacion: Optional[str] = None
    equipo: Optional[str] = None
    numero_serie: Optional[str] = None
    caracteristicas_falla: Optional[str] = None
    prioridad: Optional[str] = None
    fecha_tomado: datetime

    @field_serializer("fecha_tomado")
    def _fecha_utc(self, dt: datetime) -> str:
        # Marca explícita de UTC para que el frontend la muestre en hora de Perú.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()


# ── Endpoints ─────────────────────────────────────────────────────────────
@router.post("/tomar", response_model=AsignacionOut, status_code=201, tags=["Asignaciones"])
async def tomar_ticket(
    datos: TomarTicketRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
):
    """El técnico TOMA un ticket de la cola y queda asignado solo a él.

    Exclusividad: si ya lo tomó otro técnico -> 409. Si lo tomó el MISMO técnico
    -> se devuelve la asignación existente (idempotente, no duplica). La
    asignación es autoritativa aquí; avisar al ticket-service es best-effort.
    """
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    tecnico = request.headers.get("x-user-sub", "")
    sede = request.headers.get("x-user-sede", "").upper()
    if not tecnico or not sede:
        raise HTTPException(
            status_code=401,
            detail="Tu token no trae identidad o sede. Vuelve a iniciar sesion.",
        )

    with logger.operacion(
        "tomar_ticket", event="TicketTomado.v1",
        idTicket=datos.id_ticket, sede=sede, tecnico=tecnico,
    ) as op:
        # Exclusividad: ¿ya está tomado?
        existente = db.query(AsignacionDB).filter(
            AsignacionDB.id_ticket == datos.id_ticket
        ).first()
        if existente:
            if existente.tecnico == tecnico:
                op.result = DUPLICADO
                op.mensaje = f"El tecnico {tecnico} ya tenia asignado el ticket {datos.id_ticket}."
                return existente  # idempotente
            op.result = RECHAZADO
            op.campos["tomadoPor"] = existente.tecnico
            op.mensaje = (f"Ticket {datos.id_ticket} ya tomado por {existente.tecnico}; "
                          f"{tecnico} no puede tomarlo.")
            raise HTTPException(
                status_code=409,
                detail=(f"Este ticket ya fue tomado por otro tecnico. "
                        f"Elige otro de la cola."),
            )

        asignacion = AsignacionDB(
            id_ticket=datos.id_ticket,
            tecnico=tecnico,
            sede=sede,
            estado="TOMADO",
            datos_cliente=datos.datos_cliente,
            documento_cliente=datos.documento_cliente,
            telefono_cliente=datos.telefono_cliente,
            tipo_operacion=datos.tipo_operacion,
            equipo=datos.equipo,
            numero_serie=datos.numero_serie,
            caracteristicas_falla=datos.caracteristicas_falla,
            prioridad=datos.prioridad,
        )
        db.add(asignacion)
        try:
            db.commit()
            db.refresh(asignacion)
        except IntegrityError:
            # Carrera: dos técnicos tomaron el mismo ticket en el mismo instante.
            db.rollback()
            otra = db.query(AsignacionDB).filter(
                AsignacionDB.id_ticket == datos.id_ticket
            ).first()
            op.result = RECHAZADO
            op.mensaje = f"Carrera al tomar {datos.id_ticket}; gano {getattr(otra, 'tecnico', '¿?')}."
            raise HTTPException(
                status_code=409,
                detail="Este ticket acaba de ser tomado por otro tecnico. Elige otro de la cola.",
            )

        # Best-effort EN SEGUNDO PLANO: avisar al ticket-service para sacarlo de
        # la cola EN_COLA. No bloquea la respuesta — así "tomar" es instantáneo
        # aunque el ticket-service esté caído. La asignación ya es autoritativa
        # aquí, y la exclusividad la garantiza esta tabla, no el ticket-service.
        background_tasks.add_task(
            _sincronizar_ticket_tomado, datos.id_ticket, tecnico, sede, correlation_id,
        )

        # Rastro de auditoría (async, no bloquea): el admin podrá ver quién tomó qué.
        background_tasks.add_task(
            publicar_evento,
            exchange_name="tickets.eventos",
            routing_key="ticket.tomado",
            mensaje={"evento": "TicketTomado.v1", "trace_id": correlation_id,
                     "datos": {"idTicket": datos.id_ticket, "sede": sede, "tecnico": tecnico}},
        )

        op.mensaje = f"Ticket {datos.id_ticket} tomado por {tecnico} en {sede}."
        return asignacion


@router.get("/mias", response_model=list[AsignacionOut], tags=["Asignaciones"])
async def mis_asignaciones(request: Request, db: Annotated[Session, Depends(get_db)], limite: int = Query(200, ge=1, le=500)):
    """Bandeja 'Mis Tickets' del técnico. Se sirve SOLO desde diagnostico-service,
    sin depender del ticket-service (resiliencia)."""
    logger.extra["correlation_id"] = request.headers.get("x-correlation-id", "N/A")
    tecnico = request.headers.get("x-user-sub", "")
    if not tecnico:
        raise HTTPException(status_code=401, detail="Tu token no trae identidad. Vuelve a iniciar sesion.")

    asignaciones = (
        db.query(AsignacionDB)
        .filter(AsignacionDB.tecnico == tecnico)
        .order_by(AsignacionDB.fecha_tomado.desc())
        .limit(limite)
        .all()
    )
    logger.info(f"'Mis Tickets' de {tecnico}: {len(asignaciones)} asignacion(es).")
    return asignaciones


@router.get("/", response_model=list[AsignacionOut], tags=["Asignaciones"])
async def todas_las_asignaciones(request: Request, db: Annotated[Session, Depends(get_db)], limite: int = Query(200, ge=1, le=500)):
    """Vista de ADMIN: todos los tickets tomados y quién los atiende."""
    logger.extra["correlation_id"] = request.headers.get("x-correlation-id", "N/A")
    rol = request.headers.get("x-user-rol", "").upper()
    if rol != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Solo un administrador puede ver todas las asignaciones.",
        )
    asignaciones = db.query(AsignacionDB).order_by(AsignacionDB.fecha_tomado.desc()).limit(limite).all()
    logger.info(f"Admin consulta todas las asignaciones: {len(asignaciones)}.")
    return asignaciones

"""Gestion de suscripciones de webhooks salientes (S31/S34).

Un tercero se registra aqui con su URL para recibir eventos del negocio por
HTTP. La ENTREGA de los eventos la hace el consumidor (app/core/webhooks.py);
esto es solo el ABM de a quien avisar.
"""
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logger import get_logger, NO_ENCONTRADO, RECHAZADO
from app.models.webhook import WebhookSuscripcionDB, EntregaWebhookDB

router = APIRouter()
logger = get_logger("notificacion-service")

EVENTOS_VALIDOS = {"*", "ticket.creado", "ticket.listo", "producto.registrado"}


class SuscripcionCreate(BaseModel):
    url: HttpUrl = Field(..., description="URL a la que se hara POST cuando ocurra el evento")
    evento: str = Field("*", description="Evento a escuchar: ticket.creado, ticket.listo, producto.registrado o * (todos)")
    descripcion: str | None = Field(None, description="Para que es esta suscripcion")


class SuscripcionOut(BaseModel):
    id: int
    url: str
    evento: str
    descripcion: str | None
    activo: bool


class EntregaOut(BaseModel):
    url: str
    evento: str
    referencia: str | None
    estado: str
    intentos: int
    status_code: int | None
    trace_id: str | None


def _trazar(request: Request):
    logger.extra["correlation_id"] = request.headers.get("x-correlation-id", "N/A")


@router.post("/webhooks/suscripciones", response_model=SuscripcionOut, status_code=201, tags=["Webhooks"])
async def crear_suscripcion(sub: SuscripcionCreate, request: Request, db: Session = Depends(get_db)):
    """Registra una URL para recibir un evento del negocio por webhook."""
    _trazar(request)
    with logger.operacion("crear_suscripcion_webhook", url=str(sub.url), eventoSuscrito=sub.evento) as op:
        if sub.evento not in EVENTOS_VALIDOS:
            op.result = RECHAZADO
            op.mensaje = f"Suscripcion rechazada: evento '{sub.evento}' no existe."
            raise HTTPException(
                status_code=422,
                detail=f"El evento '{sub.evento}' no existe. Validos: {', '.join(sorted(EVENTOS_VALIDOS))}.",
            )
        registro = WebhookSuscripcionDB(
            url=str(sub.url), evento=sub.evento, descripcion=sub.descripcion, activo=True,
        )
        db.add(registro)
        db.commit()
        db.refresh(registro)
        op.campos["suscripcionId"] = registro.id
        op.mensaje = f"Suscripcion #{registro.id} creada: {sub.url} escucha '{sub.evento}'."
        return registro


@router.get("/webhooks/suscripciones", response_model=list[SuscripcionOut], tags=["Webhooks"])
async def listar_suscripciones(request: Request, db: Session = Depends(get_db)):
    """Lista las suscripciones registradas."""
    _trazar(request)
    return db.query(WebhookSuscripcionDB).order_by(WebhookSuscripcionDB.id).all()


@router.delete("/webhooks/suscripciones/{sub_id}", status_code=200, tags=["Webhooks"])
async def borrar_suscripcion(sub_id: int, request: Request, db: Session = Depends(get_db)):
    """Da de baja una suscripcion (deja de recibir webhooks)."""
    _trazar(request)
    with logger.operacion("borrar_suscripcion_webhook", suscripcionId=sub_id) as op:
        registro = db.query(WebhookSuscripcionDB).filter(WebhookSuscripcionDB.id == sub_id).first()
        if not registro:
            op.result = NO_ENCONTRADO
            op.mensaje = f"No existe la suscripcion #{sub_id}."
            raise HTTPException(status_code=404, detail=f"No existe la suscripcion de webhook #{sub_id}.")
        db.delete(registro)
        db.commit()
        op.mensaje = f"Suscripcion #{sub_id} dada de baja."
        return {"eliminada": sub_id}


@router.get("/webhooks/entregas", response_model=list[EntregaOut], tags=["Webhooks"])
async def listar_entregas(request: Request, db: Session = Depends(get_db)):
    """Bitacora de las ultimas entregas de webhooks (auditoria)."""
    _trazar(request)
    return (
        db.query(EntregaWebhookDB)
        .order_by(EntregaWebhookDB.id.desc())
        .limit(100)
        .all()
    )

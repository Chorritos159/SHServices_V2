from typing import Annotated
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from app.models.schemas import NotificacionOut
from app.models.notificacion import NotificacionDB
from app.core.database import get_db
from app.core.logger import get_logger

router = APIRouter()
logger = get_logger("notificacion-service")


def _rol_del_token(request: Request) -> str:
    """El rol lo inyecta el Gateway (X-User-Rol) tras validar el JWT."""
    return request.headers.get("x-user-rol", "").upper()


@router.get("/mis-alertas", response_model=list[NotificacionOut], tags=["Notificaciones"])
async def mis_alertas(request: Request, db: Annotated[Session, Depends(get_db)]):
    """Devuelve las notificaciones NO leídas del rol del usuario (según el JWT)."""
    rol = _rol_del_token(request)
    logger.extra["correlation_id"] = request.headers.get("x-correlation-id", "N/A")
    if not rol:
        return []
    alertas = (
        db.query(NotificacionDB)
        .filter(NotificacionDB.rol_destino == rol, NotificacionDB.leida == False)  # noqa: E712
        .order_by(NotificacionDB.created_at.desc())
        .all()
    )
    return alertas


@router.post("/marcar-leidas", tags=["Notificaciones"])
async def marcar_leidas(request: Request, db: Annotated[Session, Depends(get_db)]):
    """Marca como leídas todas las notificaciones del rol (al abrir la campanita)."""
    rol = _rol_del_token(request)
    if not rol:
        return {"actualizadas": 0}
    n = (
        db.query(NotificacionDB)
        .filter(NotificacionDB.rol_destino == rol, NotificacionDB.leida == False)  # noqa: E712
        .update({NotificacionDB.leida: True})
    )
    db.commit()
    return {"actualizadas": n}

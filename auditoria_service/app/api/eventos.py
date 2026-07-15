from fastapi import APIRouter, Request
from app.core.store import obtener_eventos
from app.models.schemas import EventoAuditoria
from app.core.logger import get_logger

router = APIRouter()
logger = get_logger("auditoria-service")


@router.get("/eventos", response_model=list[EventoAuditoria], tags=["Auditoría"])
async def listar_eventos(request: Request, limite: int = 100):
    """Expone la traza de eventos auditados para que el Admin la renderice."""
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id

    eventos = obtener_eventos(limite)
    logger.info(f"📖 Traza de auditoría solicitada: {len(eventos)} eventos.")
    return eventos

from fastapi import APIRouter
from app.core.logger import get_logger

router = APIRouter()
logger = get_logger("health-check")

@router.get("/health", tags=["Operaciones"])
async def health_check():
    """Endpoint para que Docker y el Gateway verifiquen si el servicio está vivo."""
    logger.info("Chequeo de salud (Health Check) solicitado.")
    return {"status": "ok", "service": "online"}
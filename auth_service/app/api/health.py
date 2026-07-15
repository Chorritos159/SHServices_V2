from fastapi import APIRouter
from sqlalchemy import text
from app.core.database import engine
from app.core.logger import get_logger

router = APIRouter()
logger = get_logger("health-check")

SERVICE_NAME = "auth-service"
VERSION = "1.0.0"


@router.get("/health", tags=["Operaciones"])
async def health_check():
    """Health check avanzado (FF-DEP-02): valida la conexión a PostgreSQL."""
    database = "UP"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        database = "DOWN"
        logger.error(f"Health: fallo de conexión a la base de datos: {e}")

    return {
        "status": "UP" if database == "UP" else "DEGRADED",
        "service": SERVICE_NAME,
        "version": VERSION,
        "dependencies": {"database": database},
    }

import asyncio
import os
from fastapi import APIRouter
from sqlalchemy import text
from app.core.database import engine
from app.core.logger import get_logger

router = APIRouter()
logger = get_logger("health-check")

SERVICE_NAME = "notificacion-service"
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


@router.post("/_chaos/crash", tags=["Chaos"])
async def chaos_crash():
    """DEMO de auto-healing (S34): simula un CRASH REAL del servicio.

    A diferencia de `docker stop`/`docker kill`/`docker pause` —que Docker trata
    como "el usuario pidió parar" y por eso NO disparan `restart: always`—, aquí
    el propio proceso muere solo con `os._exit(1)` ~0.5s después de responder, y
    Docker lo revive automáticamente en ~2s.
    """
    logger.error(
        "CHAOS: crash provocado por /_chaos/crash; el proceso saldra con os._exit(1).",
        extra={"campos": {"operation": "chaos_crash", "result": "provocado"}},
    )
    asyncio.get_event_loop().call_later(0.5, lambda: os._exit(1))
    return {
        "crashing": True,
        "service": SERVICE_NAME,
        "mensaje": "El proceso se caera en ~0.5s; restart:always lo revive en unos segundos.",
    }

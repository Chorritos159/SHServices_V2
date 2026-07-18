import asyncio
import os
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from app.core.database import engine
from app.core.logger import get_logger

router = APIRouter()
logger = get_logger("health-check")

SERVICE_NAME = "facturacion-service"
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


# Interruptor del endpoint de caos (Hallazgo 6 de la auditoria OWASP).
# APAGADO por defecto: si nadie lo enciende explicitamente, el endpoint no
# existe. En ESTE proyecto docker-compose lo enciende a proposito para poder
# demostrar el auto-healing de la S34; en un despliegue real iria apagado.
CHAOS_ENABLED = os.getenv("CHAOS_ENABLED", "false").lower() in ("1", "true", "yes", "on")


@router.post("/_chaos/crash", tags=["Chaos"], include_in_schema=CHAOS_ENABLED)
async def chaos_crash():
    """DEMO de auto-healing (S34): simula un CRASH REAL del servicio.

    A diferencia de `docker stop`/`docker kill`/`docker pause` —que Docker trata
    como "el usuario pidió parar" y por eso NO disparan `restart: always`—, aquí
    el propio proceso muere solo con `os._exit(1)` ~0.5s después de responder, y
    Docker lo revive automáticamente en ~2s.
    """
    if not CHAOS_ENABLED:
        # 404 y no 403: apagado, ni siquiera revelamos que el endpoint existe.
        raise HTTPException(status_code=404, detail="Not Found")

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

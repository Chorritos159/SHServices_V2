import asyncio
import os
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from app.core.database import engine
from app.core.logger import get_logger

router = APIRouter()
logger = get_logger("health-check")

SERVICE_NAME = "almacen-service"
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

    ALCANCE REAL: MATA UN WORKER, NO EL CONTENEDOR. Estos servicios arrancan
    con `uvicorn --workers 4`, donde el PID 1 es el maestro y los 4 workers son
    sus hijos. Este `os._exit(1)` mata al worker que atiende esta petición; el
    maestro lo respawnea en ~1s. Es auto-healing REAL, pero a nivel de PROCESO:
    el servicio nunca deja de responder, porque los otros 3 workers siguen
    atendiendo, y por eso el circuito del Gateway ni se entera.

    NO SE PUEDE tumbar el contenedor desde aquí, y se comprobó: `os.kill(1,
    SIGKILL)` devuelve 0 pero el contenedor sigue con `RestartCount=0`, porque
    el kernel descarta las señales dirigidas al PID 1 desde dentro de su propio
    namespace. Tampoco sirve `docker kill` desde fuera: Docker lo trata como
    parada pedida por el usuario y NO aplica `restart: always` (verificado:
    quedó en `Exited (137)` sin volver).

    Para demostrar una CAÍDA DE SERVICIO completa —circuito que se abre,
    degradación con contrato, ausencia de cascada— hay que parar el contenedor
    desde fuera; eso lo hace `pruebas_k6/caos.py`. Lo que sí se recupera solo
    allí es el CIRCUITO, que vuelve a CLOSED por la sonda activa (ADR-0014) sin
    que nadie lo toque.
    """
    if not CHAOS_ENABLED:
        # 404 y no 403: apagado, ni siquiera revelamos que el endpoint existe.
        raise HTTPException(status_code=404, detail="Not Found")

    logger.error(
        "CHAOS: crash provocado por /_chaos/crash; muere ESTE worker (os._exit(1)).",
        extra={"campos": {"operation": "chaos_crash", "result": "provocado"}},
    )
    # Se programa DESPUÉS de responder para que el cliente reciba el aviso.
    asyncio.get_event_loop().call_later(0.5, lambda: os._exit(1))
    return {
        "crashing": True,
        "service": SERVICE_NAME,
        "mensaje": "Este worker muere en ~0.5s; uvicorn lo respawnea en ~1s. "
                   "El contenedor NO cae: el servicio sigue disponible con los demas workers.",
    }

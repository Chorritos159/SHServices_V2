from fastapi import FastAPI
from sqlalchemy import text
from app.api import health, notificaciones
from app.core.exceptions import global_exception_handler
from app.core.logger import get_logger
from app.core.database import engine, Base
from app.models import notificacion  # noqa: F401 (registra la tabla)
from app.core.consumer import iniciar_consumidor
import asyncio

logger = get_logger("notificacion-service")

# Crea la tabla 'notificaciones' en PostgreSQL si no existe.
Base.metadata.create_all(bind=engine)

# Migración NO destructiva (Fase 3, S34): agrega la restricción de
# idempotencia a una tabla que puede ya existir con filas. Primero elimina
# duplicados exactos que hayan quedado de antes de esta migración (se
# conserva el más antiguo), luego crea el índice único si aún no existe.
with engine.begin() as conn:
    conn.execute(text("""
        DELETE FROM notificaciones a USING notificaciones b
        WHERE a.id > b.id AND a.trace_id = b.trace_id AND a.evento = b.evento
              AND a.rol_destino = b.rol_destino AND a.trace_id IS NOT NULL
    """))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_notif_trace_evento_rol "
        "ON notificaciones (trace_id, evento, rol_destino) WHERE trace_id IS NOT NULL"
    ))

app = FastAPI(
    title="Servicio de Notificaciones Internas",
    description="Consume eventos de RabbitMQ y genera alertas dirigidas por rol (ADMIN/TECNICO).",
    version="1.0.0",
)

app.add_exception_handler(Exception, global_exception_handler)
app.include_router(health.router)
app.include_router(notificaciones.router, prefix="/api/v1/notificaciones", tags=["Notificaciones"])


@app.on_event("startup")
async def startup_event():
    logger.info("El microservicio de Notificaciones ha arrancado.")
    asyncio.create_task(iniciar_consumidor())

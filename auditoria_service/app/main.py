from fastapi import FastAPI
from sqlalchemy import text
from app.api import health, eventos
from app.core.exceptions import global_exception_handler
from app.core.logger import get_logger
from app.core.consumer import iniciar_consumidor
from app.core.database import engine, Base
from app.models import evento  # noqa: F401  (registra el modelo en Base.metadata)
import asyncio

# Fase 4: crea la tabla de auditoría en PostgreSQL si no existe.
Base.metadata.create_all(bind=engine)

# Migración NO destructiva (Fase 3, S34): agrega la restricción de
# idempotencia a una tabla que puede ya existir con filas. Primero elimina
# duplicados exactos que hayan quedado de antes de esta migración (se
# conserva el más antiguo), luego crea el índice único si aún no existe.
with engine.begin() as conn:
    conn.execute(text("""
        DELETE FROM auditoria_eventos a USING auditoria_eventos b
        WHERE a.id > b.id AND a.trace_id = b.trace_id AND a.evento = b.evento
              AND a.trace_id IS NOT NULL
    """))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_auditoria_trace_evento "
        "ON auditoria_eventos (trace_id, evento) WHERE trace_id IS NOT NULL"
    ))

app = FastAPI(
    title="Servicio de Auditoría",
    description="Consumidor asíncrono de eventos con persistencia en PostgreSQL.",
    version="1.0.0"
)

logger = get_logger("auditoria-service")
app.add_exception_handler(Exception, global_exception_handler)
app.include_router(health.router)
app.include_router(eventos.router, prefix="/api/v1/auditoria", tags=["Auditoría"])

@app.on_event("startup")
async def startup_event():
    logger.info("El microservicio de Auditoría ha arrancado.")
    # Lanzamos el consumidor en segundo plano para que no bloquee la API
    asyncio.create_task(iniciar_consumidor())
from fastapi import FastAPI
from sqlalchemy import text
from prometheus_fastapi_instrumentator import Instrumentator
from app.api import health, eventos
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.exceptions import (
    global_exception_handler, http_exception_handler, validation_exception_handler,
)
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
# Errores legibles y trazables (ver app/core/exceptions.py):
# 4xx/5xx explicitos, payloads invalidos y el ultimo recurso.
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)
app.include_router(health.router)
app.include_router(eventos.router, prefix="/api/v1/auditoria", tags=["Auditoría"])

# Observabilidad (Fase 4, S34): expone /metrics para que Prometheus haga scrape.
Instrumentator().instrument(app).expose(app)

# El event loop solo guarda referencias DÉBILES a las tareas: si nadie más
# referencia la del consumidor, el garbage collector puede recolectarla a
# medio camino y el servicio dejaría de consumir eventos en silencio (sin
# error, sin log). Guardar la referencia a nivel de módulo lo evita.
_tareas_fondo: set[asyncio.Task] = set()


@app.on_event("startup")
async def startup_event():
    logger.info("El microservicio de Auditoría ha arrancado.")
    # Lanzamos el consumidor en segundo plano para que no bloquee la API
    tarea = asyncio.create_task(iniciar_consumidor())
    _tareas_fondo.add(tarea)
    tarea.add_done_callback(_tareas_fondo.discard)
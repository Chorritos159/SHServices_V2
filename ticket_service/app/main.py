from app.core.database import engine
from app.models.ticket import Base
from app.models.idempotencia import IdempotenciaDB  # noqa: F401 (registra la tabla 'idempotencia')
from fastapi import FastAPI
from sqlalchemy import text
from prometheus_fastapi_instrumentator import Instrumentator
from app.api import health, tickets
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.exceptions import (
    global_exception_handler, http_exception_handler, validation_exception_handler,
)
from app.core.logger import get_logger

app = FastAPI(
    title="Servicio de Gestión de Tickets",
    description="Microservicio gobernado para ciclo de vida de atenciones",
    version="1.0.0"
)
# Crea la tabla 'tickets' si no existe. ('garantias' ya no es de este
# servicio: la gestiona facturacion-service junto con el cobro.)
Base.metadata.create_all(bind=engine)

# Migración NO destructiva: create_all no altera tablas existentes, así que
# agregamos las columnas enriquecidas si aún no existen (idempotente). Los
# tickets ya creados NO se pierden ni se tocan.
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS documento_cliente VARCHAR"))
    conn.execute(text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS telefono_cliente VARCHAR"))
    conn.execute(text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS equipo VARCHAR"))
    conn.execute(text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS numero_serie VARCHAR"))
    conn.execute(text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS caracteristicas_falla TEXT"))
    conn.execute(text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS precio_estimado DOUBLE PRECISION"))
    conn.execute(text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS repuestos_reservados TEXT"))

logger = get_logger("ticket-service")
# Errores legibles y trazables (ver app/core/exceptions.py):
# 4xx/5xx explicitos, payloads invalidos y el ultimo recurso.
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# Registramos las rutas
app.include_router(health.router)
# IMPORTANTE: Aquí conectamos el archivo que acabas de crear
app.include_router(tickets.router, prefix="/api/v1/tickets", tags=["Tickets"])

# Observabilidad: expone /metrics para que Prometheus haga scrape.
Instrumentator().instrument(app).expose(app)

@app.on_event("startup")
async def startup_event():
    # Indices de las consultas calientes. Van aqui y no en `create_all` porque
    # este solo crea indices al CREAR la tabla: en una base que ya existe (la de
    # cualquier despliegue en marcha) no los anadiria nunca. IF NOT EXISTS lo
    # hace idempotente, asi que es seguro en cada arranque.
    try:
        from sqlalchemy import text as _sql
        from app.core.database import engine as _engine
        with _engine.begin() as _conn:
            _conn.execute(_sql(
                "CREATE INDEX IF NOT EXISTS ix_tickets_estado_fecha "
                "ON tickets (estado, fecha_registro)"))
            _conn.execute(_sql(
                "CREATE INDEX IF NOT EXISTS ix_tickets_documento "
                "ON tickets (documento_cliente)"))
    except Exception as _exc:      # nunca impedir el arranque por un indice
        logger.error(f"No se pudieron preparar los indices de tickets: {_exc}")

    # Consumidor de eventos: es quien pasa el ticket a DIAGNOSTICADO cuando el
    # tecnico registra su diagnostico. Se guarda la referencia a la tarea porque
    # asyncio solo mantiene weakrefs: sin ella el recolector puede cancelarla.
    import asyncio
    from app.core.consumer import iniciar_consumidor
    app.state.consumidor = asyncio.create_task(iniciar_consumidor())

    logger.info("El Servicio de Gestión de Tickets ha arrancado exitosamente.")
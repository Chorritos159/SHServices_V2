from fastapi import FastAPI
from sqlalchemy import text
from app.api import health, diagnostico, asignaciones
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.exceptions import (
    global_exception_handler, http_exception_handler, validation_exception_handler,
)
from app.core.logger import get_logger
from app.core.database import engine
from app.models.diagnostico import Base
from app.models import idempotencia  # noqa: F401 (registra la tabla de idempotencia en Base)
from app.models import asignacion    # noqa: F401 (registra la tabla de asignaciones en Base)

# Crea las tablas automáticamente (diagnósticos + idempotencia + asignaciones).
Base.metadata.create_all(bind=engine)

# Migración no destructiva: create_all NO altera tablas existentes, así que
# añadimos las columnas nuevas de la Fase 3 si aún no existen (idempotente).
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE diagnosticos ADD COLUMN IF NOT EXISTS precio_reparacion DOUBLE PRECISION NOT NULL DEFAULT 0"))
    conn.execute(text("ALTER TABLE diagnosticos ADD COLUMN IF NOT EXISTS mano_obra DOUBLE PRECISION NOT NULL DEFAULT 0"))
    conn.execute(text("ALTER TABLE diagnosticos ADD COLUMN IF NOT EXISTS repuestos_json TEXT"))

app = FastAPI(
    title="Servicio de Diagnóstico Técnico",
    description="Microservicio de evaluación técnica e integración con Almacén.",
    version="1.0.0"
)

logger = get_logger("diagnostico-service")
# Errores legibles y trazables (ver app/core/exceptions.py):
# 4xx/5xx explicitos, payloads invalidos y el ultimo recurso.
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

app.include_router(health.router)
app.include_router(diagnostico.router, prefix="/api/v1/diagnosticos", tags=["Diagnósticos"])
# Asignaciones (¿quién atiende qué?): diagnostico-service es el dueño para que
# "Mis Tickets" no dependa del ticket-service. Se monta en /api/v1/asignaciones
# (sin doblar "diagnosticos") para que el Gateway lo exponga como
# /api/v1/diagnosticos/asignaciones/... (el prefijo "diagnosticos" lo pone el
# enrutado del Gateway a partir del nombre del servicio).
app.include_router(asignaciones.router, prefix="/api/v1/asignaciones", tags=["Asignaciones"])

@app.on_event("startup")
async def startup_event():
    # Ver el comentario equivalente en facturacion_service/app/main.py: los
    # listados ordenan por fecha y sin indice acaban en escaneo completo.
    try:
        from sqlalchemy import text as _sql
        from app.core.database import engine as _engine
        with _engine.begin() as _conn:
            _conn.execute(_sql("CREATE INDEX IF NOT EXISTS ix_asignaciones_fecha_tomado "
                               "ON asignaciones (fecha_tomado DESC)"))
    except Exception as _exc:
        logger.error(f"No se pudieron preparar los indices de diagnostico: {_exc}")

    logger.info("El Servicio de Diagnóstico Técnico ha arrancado exitosamente.")
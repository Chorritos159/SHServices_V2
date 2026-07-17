from fastapi import FastAPI
from sqlalchemy import text
from app.api import health, diagnostico
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.exceptions import (
    global_exception_handler, http_exception_handler, validation_exception_handler,
)
from app.core.logger import get_logger
from app.core.database import engine
from app.models.diagnostico import Base
from app.models import idempotencia  # noqa: F401 (registra la tabla de idempotencia en Base)

# Crea las tablas automáticamente (diagnósticos + idempotencia).
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

@app.on_event("startup")
async def startup_event():
    logger.info("El Servicio de Diagnóstico Técnico ha arrancado exitosamente.")
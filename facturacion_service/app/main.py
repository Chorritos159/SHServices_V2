from fastapi import FastAPI
from sqlalchemy import text
from app.api import health, facturacion
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.exceptions import (
    global_exception_handler, http_exception_handler, validation_exception_handler,
)
from app.core.logger import get_logger
from app.core.database import engine
from app.models.factura import Base

# Crear la tabla de facturas en PostgreSQL automáticamente
Base.metadata.create_all(bind=engine)

# Migración NO destructiva: agrega el detalle de líneas si aún no existe (idempotente).
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE facturas ADD COLUMN IF NOT EXISTS detalle_json TEXT"))

app = FastAPI(
    title="Servicio de Facturación y Finanzas",
    description="Microservicio gobernado para la emisión de comprobantes fiscales de las atenciones.",
    version="1.0.0"
)

logger = get_logger("facturacion-service")
# Errores legibles y trazables (ver app/core/exceptions.py):
# 4xx/5xx explicitos, payloads invalidos y el ultimo recurso.
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

app.include_router(health.router)
app.include_router(facturacion.router, prefix="/api/v1/facturas", tags=["Facturación"])

@app.on_event("startup")
async def startup_event():
    logger.info("El Servicio de Facturación ha arrancado exitosamente.")
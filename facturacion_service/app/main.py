from fastapi import FastAPI
from sqlalchemy import text
from prometheus_fastapi_instrumentator import Instrumentator
from app.api import health, facturacion
from app.core.exceptions import global_exception_handler
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
app.add_exception_handler(Exception, global_exception_handler)

app.include_router(health.router)
app.include_router(facturacion.router, prefix="/api/v1/facturas", tags=["Facturación"])

# Observabilidad: expone /metrics para Prometheus.
Instrumentator().instrument(app).expose(app)

@app.on_event("startup")
async def startup_event():
    logger.info("El Servicio de Facturación ha arrancado exitosamente.")
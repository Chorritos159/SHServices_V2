from fastapi import FastAPI
from sqlalchemy import text
from prometheus_fastapi_instrumentator import Instrumentator
from app.api import health, almacen
from app.core.exceptions import global_exception_handler
from app.core.logger import get_logger
from app.core.database import engine
from app.models.inventario import Base

# Crear la tabla 'inventario' en Postgres si no existe
Base.metadata.create_all(bind=engine)

# Migración NO destructiva: agrega el precio de venta si aún no existe (idempotente).
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE inventario ADD COLUMN IF NOT EXISTS precio_unitario DOUBLE PRECISION NOT NULL DEFAULT 0"))

app = FastAPI(
    title="Servicio de Almacén e Inventario",
    description="Microservicio gobernado para la gestión de repuestos y productos por sede.",
    version="1.0.0"
)

logger = get_logger("almacen-service")
app.add_exception_handler(Exception, global_exception_handler)

# Registrar rutas
app.include_router(health.router)
app.include_router(almacen.router, prefix="/api/v1/almacen", tags=["Almacén"])

# Observabilidad: expone /metrics para Prometheus.
Instrumentator().instrument(app).expose(app)

@app.on_event("startup")
async def startup_event():
    logger.info("El Servicio de Almacén e Inventario ha arrancado exitosamente.")
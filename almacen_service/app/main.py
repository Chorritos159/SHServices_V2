from fastapi import FastAPI
from app.api import health, almacen
from app.core.exceptions import global_exception_handler
from app.core.logger import get_logger
from app.core.database import engine
from app.models.inventario import Base

# Crear la tabla 'inventario' en Postgres si no existe
Base.metadata.create_all(bind=engine)

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

@app.on_event("startup")
async def startup_event():
    logger.info("El Servicio de Almacén e Inventario ha arrancado exitosamente.")
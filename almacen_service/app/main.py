from fastapi import FastAPI
from sqlalchemy import text
from app.api import health, almacen
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.exceptions import (
    global_exception_handler, http_exception_handler, validation_exception_handler,
)
from app.core.logger import get_logger
from app.core.database import engine
from app.core.seed import seed_inventario_base
from app.models.inventario import Base

# Crear la tabla 'inventario' en Postgres si no existe
Base.metadata.create_all(bind=engine)

# Migración NO destructiva: agrega el precio de venta si aún no existe (idempotente).
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE inventario ADD COLUMN IF NOT EXISTS precio_unitario DOUBLE PRECISION NOT NULL DEFAULT 0"))

# Seed de inventario base (idempotente): que el almacen no arranque vacio.
seed_inventario_base()

app = FastAPI(
    title="Servicio de Almacén e Inventario",
    description="Microservicio gobernado para la gestión de repuestos y productos por sede.",
    version="1.0.0"
)

logger = get_logger("almacen-service")
# Errores legibles y trazables (ver app/core/exceptions.py):
# 4xx/5xx explicitos, payloads invalidos y el ultimo recurso.
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# Registrar rutas
app.include_router(health.router)
app.include_router(almacen.router, prefix="/api/v1/almacen", tags=["Almacén"])

@app.on_event("startup")
async def startup_event():
    # Las secuencias que numeran los códigos de producto (REP-001, PRD-001).
    # Se crean aquí y no en una migración porque este proyecto genera el
    # esquema con `create_all`, que no sabe de secuencias sueltas. Es
    # idempotente: si ya existen, solo se comprueba que no vayan por detrás
    # del máximo actual.
    from app.core.database import SessionLocal
    from app.api.almacen import _asegurar_secuencias
    db = SessionLocal()
    try:
        _asegurar_secuencias(db)
        logger.info("Secuencias de codigos de producto listas (REP / PRD).")
    except Exception as exc:      # nunca impedir el arranque por esto
        logger.error(f"No se pudieron preparar las secuencias de codigos: {exc}")
    finally:
        db.close()

    logger.info("El Servicio de Almacén e Inventario ha arrancado exitosamente.")
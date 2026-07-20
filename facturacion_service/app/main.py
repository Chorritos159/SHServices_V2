from fastapi import FastAPI
from sqlalchemy import text
from app.api import health, facturacion, garantias
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.exceptions import (
    global_exception_handler, http_exception_handler, validation_exception_handler,
)
from app.core.logger import get_logger
from app.core.database import engine
from app.models.factura import Base
from app.models import garantia  # noqa: F401 (registra la tabla garantias)

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
# Garantias: se montan en /api/v1/garantias (sin doblar "facturas") para que el
# Gateway las exponga como /api/v1/facturas/garantias.
app.include_router(garantias.router, prefix="/api/v1/garantias", tags=["Garantías"])

@app.on_event("startup")
async def startup_event():
    # Indices de los listados. Van aqui y no en `create_all` porque este solo
    # crea indices al CREAR la tabla: en una base que ya existe no los anadiria
    # nunca. Sin ellos, ordenar por fecha era un escaneo completo que superaba
    # el timeout del Gateway y abria el circuito de facturas una y otra vez.
    try:
        from sqlalchemy import text as _sql
        from app.core.database import engine as _engine
        with _engine.begin() as _conn:
            _conn.execute(_sql("CREATE INDEX IF NOT EXISTS ix_garantias_fecha_entrega "
                               "ON garantias (fecha_entrega DESC)"))
            _conn.execute(_sql("CREATE INDEX IF NOT EXISTS ix_facturas_fecha_emision "
                               "ON facturas (fecha_emision DESC)"))
    except Exception as _exc:      # nunca impedir el arranque por un indice
        logger.error(f"No se pudieron preparar los indices de facturacion: {_exc}")

    logger.info("El Servicio de Facturación ha arrancado exitosamente.")
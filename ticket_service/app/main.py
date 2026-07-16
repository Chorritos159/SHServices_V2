from app.core.database import engine
from app.models.ticket import Base
from app.models.garantia import GarantiaDB  # noqa: F401 (registra la tabla 'garantias' en Base)
from fastapi import FastAPI
from sqlalchemy import text
from prometheus_fastapi_instrumentator import Instrumentator
from app.api import health, tickets
from app.core.exceptions import global_exception_handler
from app.core.logger import get_logger

app = FastAPI(
    title="Servicio de Gestión de Tickets",
    description="Microservicio gobernado para ciclo de vida de atenciones",
    version="1.0.0"
)
# Crea tablas 'tickets' y 'garantias' si no existen.
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
    conn.execute(text("ALTER TABLE garantias ADD COLUMN IF NOT EXISTS monto_total DOUBLE PRECISION"))

logger = get_logger("ticket-service")
app.add_exception_handler(Exception, global_exception_handler)

# Registramos las rutas
app.include_router(health.router)
# IMPORTANTE: Aquí conectamos el archivo que acabas de crear
app.include_router(tickets.router, prefix="/api/v1/tickets", tags=["Tickets"])

# Observabilidad: expone /metrics para que Prometheus haga scrape.
Instrumentator().instrument(app).expose(app)

@app.on_event("startup")
async def startup_event():
    logger.info("El Servicio de Gestión de Tickets ha arrancado exitosamente.")
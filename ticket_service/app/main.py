from app.core.database import engine
from app.models.ticket import Base
from fastapi import FastAPI
from app.api import health, tickets
from app.core.exceptions import global_exception_handler
from app.core.logger import get_logger

app = FastAPI(
    title="Servicio de Gestión de Tickets",
    description="Microservicio gobernado para ciclo de vida de atenciones",
    version="1.0.0"
)
Base.metadata.create_all(bind=engine)

logger = get_logger("ticket-service")
app.add_exception_handler(Exception, global_exception_handler)

# Registramos las rutas
app.include_router(health.router)
# IMPORTANTE: Aquí conectamos el archivo que acabas de crear
app.include_router(tickets.router, prefix="/api/v1/tickets", tags=["Tickets"])

@app.on_event("startup")
async def startup_event():
    logger.info("El Servicio de Gestión de Tickets ha arrancado exitosamente.")
from fastapi import FastAPI
from app.api import health
from app.core.exceptions import global_exception_handler
from app.core.logger import get_logger

# 1. Inicializar la app
app = FastAPI(
    title="Plantilla Base de Servicio",
    description="Servicio modular con logging JSON y escudo de errores.",
    version="1.0.0"
)

# 2. Inicializar el logger principal
logger = get_logger("ticket-service")

# 3. Registrar el Manejador Global de Errores
app.add_exception_handler(Exception, global_exception_handler)

# 4. Incluir las rutas (Endpoints)
app.include_router(health.router)

@app.on_event("startup")
async def startup_event():
    logger.info("El microservicio ha arrancado exitosamente.")
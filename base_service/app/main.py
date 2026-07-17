from fastapi import FastAPI
from app.api import health
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.exceptions import (
    global_exception_handler, http_exception_handler, validation_exception_handler,
)
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
# Errores legibles y trazables (ver app/core/exceptions.py):
# 4xx/5xx explicitos, payloads invalidos y el ultimo recurso.
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# 4. Incluir las rutas (Endpoints)
app.include_router(health.router)

@app.on_event("startup")
async def startup_event():
    logger.info("El microservicio ha arrancado exitosamente.")
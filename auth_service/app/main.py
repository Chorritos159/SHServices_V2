from fastapi import FastAPI
from app.api import health, auth
from app.core.exceptions import global_exception_handler
from app.core.logger import get_logger

app = FastAPI(
    title="Servicio de Autenticación",
    description="Microservicio emisor de tokens de seguridad JWT.",
    version="1.0.0"
)

logger = get_logger("auth-service")
app.add_exception_handler(Exception, global_exception_handler)

app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1/auth")

@app.on_event("startup")
async def startup_event():
    logger.info("El Servicio de Autenticación (JWT) ha arrancado exitosamente.")
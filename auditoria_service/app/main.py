from fastapi import FastAPI
from app.api import health
from app.core.exceptions import global_exception_handler
from app.core.logger import get_logger
from app.core.consumer import iniciar_consumidor
import asyncio

app = FastAPI(
    title="Servicio de Auditoría",
    description="Consumidor asíncrono de eventos para trazabilidad.",
    version="1.0.0"
)

logger = get_logger("auditoria-service")
app.add_exception_handler(Exception, global_exception_handler)
app.include_router(health.router)

@app.on_event("startup")
async def startup_event():
    logger.info("El microservicio de Auditoría ha arrancado.")
    # Lanzamos el consumidor en segundo plano para que no bloquee la API
    asyncio.create_task(iniciar_consumidor())
from fastapi import FastAPI
from app.api import health, eventos
from app.core.exceptions import global_exception_handler
from app.core.logger import get_logger
from app.core.consumer import iniciar_consumidor
from app.core.database import engine, Base
from app.models import evento  # noqa: F401  (registra el modelo en Base.metadata)
import asyncio

# Fase 4: crea la tabla de auditoría en PostgreSQL si no existe.
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Servicio de Auditoría",
    description="Consumidor asíncrono de eventos con persistencia en PostgreSQL.",
    version="1.0.0"
)

logger = get_logger("auditoria-service")
app.add_exception_handler(Exception, global_exception_handler)
app.include_router(health.router)
app.include_router(eventos.router, prefix="/api/v1/auditoria", tags=["Auditoría"])

@app.on_event("startup")
async def startup_event():
    logger.info("El microservicio de Auditoría ha arrancado.")
    # Lanzamos el consumidor en segundo plano para que no bloquee la API
    asyncio.create_task(iniciar_consumidor())
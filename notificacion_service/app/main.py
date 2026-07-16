from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from app.api import health, notificaciones
from app.core.exceptions import global_exception_handler
from app.core.logger import get_logger
from app.core.database import engine, Base
from app.models import notificacion  # noqa: F401 (registra la tabla)
from app.core.consumer import iniciar_consumidor
import asyncio

logger = get_logger("notificacion-service")

# Crea la tabla 'notificaciones' en PostgreSQL si no existe.
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Servicio de Notificaciones Internas",
    description="Consume eventos de RabbitMQ y genera alertas dirigidas por rol (ADMIN/TECNICO).",
    version="1.0.0",
)

app.add_exception_handler(Exception, global_exception_handler)
app.include_router(health.router)
app.include_router(notificaciones.router, prefix="/api/v1/notificaciones", tags=["Notificaciones"])

# Observabilidad: expone /metrics para Prometheus.
Instrumentator().instrument(app).expose(app)


@app.on_event("startup")
async def startup_event():
    logger.info("El microservicio de Notificaciones ha arrancado.")
    asyncio.create_task(iniciar_consumidor())

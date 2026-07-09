from fastapi import FastAPI
from app.api import health, diagnostico
from app.core.exceptions import global_exception_handler
from app.core.logger import get_logger
from app.core.database import engine
from app.models.diagnostico import Base

# Crea la tabla automáticamente
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Servicio de Diagnóstico Técnico",
    description="Microservicio de evaluación técnica e integración con Almacén.",
    version="1.0.0"
)

logger = get_logger("diagnostico-service")
app.add_exception_handler(Exception, global_exception_handler)

app.include_router(health.router)
app.include_router(diagnostico.router, prefix="/api/v1/diagnosticos", tags=["Diagnósticos"])

@app.on_event("startup")
async def startup_event():
    logger.info("El Servicio de Diagnóstico Técnico ha arrancado exitosamente.")
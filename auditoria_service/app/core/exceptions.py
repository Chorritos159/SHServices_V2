from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.logger import get_logger
import traceback

# Instanciamos el logger para el manejador de errores
logger = get_logger("exception-handler")

async def global_exception_handler(request: Request, exc: Exception):
    """Atrapa cualquier error no controlado y devuelve una respuesta segura."""
    # Extraer correlation_id si existe en los headers (inyectado por el Gateway)
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    
    # Inyectamos el ID al logger para este error específico
    logger.extra["correlation_id"] = correlation_id
    
    # Registramos el error real en la terminal para el programador
    logger.error(f"Error inesperado: {str(exc)} | Traceback: {traceback.format_exc()}")
    
    # Le devolvemos un mensaje seguro y elegante al frontend/Gateway
    return JSONResponse(
        status_code=500,
        content={
            "error": "Error Interno del Servidor",
            "detalle": "Ha ocurrido un problema al procesar la solicitud.",
            "trace_id": correlation_id
        }
    )
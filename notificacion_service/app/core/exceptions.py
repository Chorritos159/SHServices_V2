from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.logger import get_logger
import traceback

logger = get_logger("exception-handler")

async def global_exception_handler(request: Request, exc: Exception):
    """Atrapa cualquier error no controlado y devuelve una respuesta segura."""
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    logger.error(f"Error inesperado: {str(exc)} | Traceback: {traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Error Interno del Servidor",
            "detalle": "Ha ocurrido un problema al procesar la solicitud.",
            "trace_id": correlation_id,
        },
    )

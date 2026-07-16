import logging
import json
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Logs estructurados (S34): un JSON por linea, con campos operables.

    Campos base: timestamp, level, service, correlationId, message.
    Campos opcionales por llamada (kwarg `campos` dentro de `extra`):
      operation, event, result, durationMs, y cualquier dato de negocio
      relevante (idTicket, dependency, retryAttempt, circuitBreakerState...).
    """
    def format(self, record):
        log_record = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "service": getattr(record, "service_name", "servicio-base"),
            "correlationId": getattr(record, "correlation_id", "N/A"),
            "message": record.getMessage(),
        }
        campos = getattr(record, "campos", None)
        if campos:
            log_record.update(campos)
        return json.dumps(log_record, ensure_ascii=False)


class AdaptadorContextual(logging.LoggerAdapter):
    """LoggerAdapter que FUSIONA el `extra` por-llamada con el contexto base
    (service_name, correlation_id) en vez de reemplazarlo. El LoggerAdapter
    estandar de la libreria descarta cualquier `extra=` pasado en la llamada
    (kwargs["extra"] = self.extra), lo que silenciaba los campos S34 por-request.
    """
    def process(self, msg, kwargs):
        extra = dict(self.extra)
        extra.update(kwargs.get("extra") or {})
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(service_name: str):
    logger = logging.getLogger(service_name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(JSONFormatter())
        logger.addHandler(console_handler)
        # Desactivar propagacion para no duplicar logs de uvicorn
        logger.propagate = False
    return AdaptadorContextual(logger, {"service_name": service_name, "correlation_id": "N/A"})

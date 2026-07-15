import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    """Convierte los logs en JSON estandarizado para Observabilidad."""
    def format(self, record):
        log_record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "service_name": getattr(record, "service_name", "servicio-base"),
            "trace_id": getattr(record, "correlation_id", "N/A"),
            "message": record.getMessage(),
        }
        return json.dumps(log_record)

def get_logger(service_name: str):
    logger = logging.getLogger(service_name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(JSONFormatter())
        logger.addHandler(console_handler)
        logger.propagate = False
    return logging.LoggerAdapter(logger, {"service_name": service_name, "correlation_id": "N/A"})

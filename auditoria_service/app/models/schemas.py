from pydantic import BaseModel
from typing import Any, Optional


class EventoAuditoria(BaseModel):
    """Contrato de salida del GET /api/v1/auditoria/eventos."""
    evento: Optional[str] = None
    trace_id: Optional[str] = None
    sede: Optional[str] = None
    idTicket: Optional[str] = None
    recibido_en: str
    datos: dict[str, Any] = {}

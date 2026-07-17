from pydantic import BaseModel, field_serializer
from typing import Optional
from datetime import datetime, timezone


class NotificacionOut(BaseModel):
    id: int
    mensaje: str
    referencia: Optional[str] = None
    evento: Optional[str] = None
    created_at: datetime

    @field_serializer("created_at")
    def _serializar_fecha(self, dt: datetime) -> str:
        """La fecha se guarda naive en UTC; se emite con marcador UTC explicito
        (+00:00) para que el frontend sepa la zona y la muestre en hora de Peru.
        Sin esto salia "naive" y el navegador la interpretaba como local (5h de mas).
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

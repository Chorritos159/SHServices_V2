from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class NotificacionOut(BaseModel):
    id: int
    mensaje: str
    referencia: Optional[str] = None
    evento: Optional[str] = None
    created_at: datetime

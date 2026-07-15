from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.core.database import Base
import datetime


class NotificacionDB(Base):
    """Notificación interna dirigida a un rol (ADMIN o TECNICO)."""
    __tablename__ = "notificaciones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rol_destino = Column(String, nullable=False, index=True)  # ADMIN | TECNICO
    mensaje = Column(String, nullable=False)
    referencia = Column(String, nullable=True)   # idTicket o código de producto
    evento = Column(String, nullable=True)
    trace_id = Column(String, nullable=True)
    leida = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

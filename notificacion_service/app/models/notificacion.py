from sqlalchemy import Column, Integer, String, Boolean, DateTime, UniqueConstraint
from app.core.database import Base
import datetime


class NotificacionDB(Base):
    """Notificación interna dirigida a un rol (ADMIN o TECNICO)."""
    __tablename__ = "notificaciones"
    # Idempotencia (S34): un redelivery de RabbitMQ del mismo evento no debe
    # generar una segunda alerta duplicada para el mismo destinatario.
    __table_args__ = (UniqueConstraint("trace_id", "evento", "rol_destino", name="ux_notif_trace_evento_rol"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    rol_destino = Column(String, nullable=False, index=True)  # ADMIN | TECNICO
    mensaje = Column(String, nullable=False)
    referencia = Column(String, nullable=True)   # idTicket o código de producto
    evento = Column(String, nullable=True)
    trace_id = Column(String, nullable=True)
    leida = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

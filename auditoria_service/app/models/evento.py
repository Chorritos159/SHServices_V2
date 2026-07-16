from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint
from app.core.database import Base
import datetime


class EventoAuditoriaDB(Base):
    """Traza de auditoría persistente. Cada evento consumido de RabbitMQ se guarda aquí."""
    __tablename__ = "auditoria_eventos"
    # Idempotencia (S34): RabbitMQ entrega "al menos una vez" — si un ack se
    # pierde tras persistir (crash del consumidor antes de confirmar), el
    # mismo mensaje se REENTREGA. (trace_id, evento) identifica el mismo
    # evento de negocio: un redelivery no debe duplicar la traza.
    __table_args__ = (UniqueConstraint("trace_id", "evento", name="ux_auditoria_trace_evento"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    evento = Column(String, nullable=True)
    # correlationId propagado por todo el sistema (FF-DEP-05). SIEMPRE se guarda.
    trace_id = Column(String, nullable=True, index=True)
    sede = Column(String, nullable=True)
    id_ticket = Column(String, nullable=True)
    datos_json = Column(Text, nullable=True)  # payload completo del evento
    recibido_en = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

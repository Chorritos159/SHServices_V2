from sqlalchemy import Column, Integer, String, Boolean, DateTime, UniqueConstraint, Index
from app.core.database import Base
import datetime


class NotificacionDB(Base):
    """Notificación interna dirigida a un rol (ADMIN o TECNICO)."""
    __tablename__ = "notificaciones"
    __table_args__ = (
        # Idempotencia (S34): un redelivery de RabbitMQ del mismo evento no debe
        # generar una segunda alerta duplicada para el mismo destinatario.
        UniqueConstraint("trace_id", "evento", "rol_destino", name="ux_notif_trace_evento_rol"),
        # Índice COMPUESTO para `GET /mis-alertas`, que filtra por
        # (rol_destino, leida) y ordena por created_at DESC.
        #
        # Había índices sueltos en `rol_destino` y `leida`, pero ninguno en
        # `created_at`: PostgreSQL usaba uno de ellos y luego ORDENABA en
        # memoria todas las filas que pasaran el filtro. Con 46.627
        # notificaciones acumuladas por una corrida de carga (el ADMIN recibe
        # copia de TODOS los eventos), eso era un sort completo por petición y
        # agotaba el pool de conexiones del servicio.
        #
        # Con las tres columnas en el orden del WHERE + ORDER BY, la consulta
        # se resuelve recorriendo el índice y parando en el LIMIT.
        Index("ix_notif_rol_leida_fecha", "rol_destino", "leida", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    rol_destino = Column(String, nullable=False, index=True)  # ADMIN | TECNICO
    mensaje = Column(String, nullable=False)
    referencia = Column(String, nullable=True)   # idTicket o código de producto
    evento = Column(String, nullable=True)
    trace_id = Column(String, nullable=True)
    leida = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

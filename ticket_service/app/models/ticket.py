from sqlalchemy import Column, String, DateTime
from app.core.database import Base
import datetime

class TicketDB(Base):
    """Modelo de base de datos para la tabla 'tickets'"""
    __tablename__ = "tickets"

    id = Column(String, primary_key=True, index=True)
    datos_cliente = Column(String, nullable=False)
    tipo_operacion = Column(String, nullable=False)
    datos_equipo = Column(String, nullable=True)
    sede = Column(String, nullable=False)
    usuario_registro = Column(String, nullable=False)
    prioridad = Column(String, nullable=False)
    estado = Column(String, nullable=False, default="EN_COLA")
    fecha_registro = Column(DateTime, default=datetime.datetime.utcnow)
from sqlalchemy import Column, String, Integer, Text, DateTime
from app.core.database import Base
import datetime


class IdempotenciaDB(Base):
    """Registro de idempotencia (S34): una `Idempotency-Key` ya procesada
    devuelve SIEMPRE la misma respuesta, sin repetir el efecto (crear un
    ticket duplicado) ante un reintento del cliente o del Gateway.
    """
    __tablename__ = "idempotencia"

    clave = Column(String, primary_key=True)          # Idempotency-Key del cliente
    operacion = Column(String, nullable=False)         # p.ej. "crear_ticket"
    status_code = Column(Integer, nullable=False)
    respuesta_json = Column(Text, nullable=False)
    creado_en = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

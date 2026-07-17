from sqlalchemy import Column, String, Integer, Text, DateTime
from app.core.database import Base
import datetime


class IdempotenciaDB(Base):
    """Registro de idempotencia (S34) para el diagnóstico.

    Registrar un diagnóstico RESERVA stock en almacén, así que un reintento
    (por ejemplo, del outbox del Gateway tras una caída) NO debe volver a
    reservar ni crear un segundo diagnóstico. Con la misma `Idempotency-Key`
    se devuelve SIEMPRE la respuesta original, sin repetir el efecto.
    """
    __tablename__ = "idempotencia_diagnostico"

    clave = Column(String, primary_key=True)          # Idempotency-Key del cliente/Gateway
    operacion = Column(String, nullable=False)         # "registrar_diagnostico"
    status_code = Column(Integer, nullable=False)
    respuesta_json = Column(Text, nullable=False)
    creado_en = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

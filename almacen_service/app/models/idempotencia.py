from sqlalchemy import Column, String, Integer, Text, DateTime
from app.core.database import Base
import datetime


class IdempotenciaDB(Base):
    """Registro de idempotencia (S34) para el almacén.

    Cubre las dos operaciones del almacén que tienen efecto lateral y que un
    reintento no debe repetir:

      - `crear_producto`: si el servicio se cae entre el commit y la respuesta,
        el cliente (o el outbox del Gateway) reintenta y se daba de alta el
        producto DOS veces.
      - `consumir_stock`: el técnico pulsa varias veces "agregar repuesto" y el
        descuento se aplicaba una vez por pulsación.

    Con la misma `Idempotency-Key` se devuelve SIEMPRE la respuesta original,
    sin repetir el efecto. Misma tabla para ambas porque la clave la genera el
    cliente y ya es única de por sí; `operacion` queda para poder auditar.
    """
    __tablename__ = "idempotencia_almacen"

    clave = Column(String, primary_key=True)           # Idempotency-Key del cliente/Gateway
    operacion = Column(String, nullable=False)          # "crear_producto" | "consumir_stock"
    status_code = Column(Integer, nullable=False)
    respuesta_json = Column(Text, nullable=False)
    creado_en = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

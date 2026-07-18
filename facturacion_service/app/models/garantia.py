from sqlalchemy import Column, String, Integer, DateTime, Float
from app.core.database import Base
import datetime


class GarantiaDB(Base):
    """Garantía de 90 días de una reparación.

    Vive en **facturacion-service** porque la garantía es parte del ciclo
    ECONÓMICO de la operación (nace con el cobro, respalda lo facturado), no
    del ciclo del ticket. Además así la consulta de garantías sigue disponible
    aunque el ticket-service esté caído.

    Misma tabla `garantias` de siempre (todos los servicios comparten la BD),
    así que no hace falta migrar datos: las garantías existentes se siguen
    viendo igual.
    """
    __tablename__ = "garantias"

    id = Column(String, primary_key=True, index=True)          # GAR-PIU-XXXX
    id_ticket = Column(String, nullable=False, index=True)
    documento_cliente = Column(String, nullable=True, index=True)
    equipo = Column(String, nullable=True)
    numero_serie = Column(String, nullable=True, index=True)    # búsqueda fiable del equipo
    descripcion = Column(String, nullable=True)                 # qué reparación cubre
    fecha_entrega = Column(DateTime, default=datetime.datetime.utcnow)
    fecha_vencimiento = Column(DateTime, nullable=False)        # fecha_entrega + 90 días
    dias = Column(Integer, default=90, nullable=False)
    monto_total = Column(Float, nullable=True)                  # cuánto se cobró

from sqlalchemy import Column, String, Float, DateTime
from app.core.database import Base
import datetime

class FacturaDB(Base):
    """Modelo de base de datos para la tabla 'facturas'"""
    __tablename__ = "facturas"

    id = Column(String, primary_key=True, index=True) # Número de boleta/factura (Ej: FAC-PIU-A12B)
    id_ticket = Column(String, nullable=False, unique=True)
    monto_mano_obra = Column(Float, nullable=False)
    monto_repuestos = Column(Float, nullable=False)
    monto_total = Column(Float, nullable=False)
    metodo_pago = Column(String, nullable=False) # EFECTIVO, TARJETA, YAPE
    fecha_emision = Column(DateTime, default=datetime.datetime.utcnow)
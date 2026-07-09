from sqlalchemy import Column, String, Integer
from app.core.database import Base

class ProductoDB(Base):
    """Modelo de base de datos para la tabla 'inventario'"""
    __tablename__ = "inventario"

    codigo = Column(String, primary_key=True, index=True) # Ej: REP-VENT-01
    nombre = Column(String, nullable=False)
    categoria = Column(String, nullable=False) # "REPUESTO" o "PRODUCTO_VENTA"
    sede = Column(String, nullable=False) # "PIURA"
    stock_disponible = Column(Integer, default=0, nullable=False)
    stock_reservado = Column(Integer, default=0, nullable=False)
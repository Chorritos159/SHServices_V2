from sqlalchemy import Column, String, Integer, DateTime
from app.core.database import Base
import datetime


class GarantiaDB(Base):
    """
    Garantía generada automáticamente al ENTREGAR una reparación (SOPORTE).
    Regla de negocio estricta: 90 días exactos desde la entrega.
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

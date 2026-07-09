from sqlalchemy import Column, String, DateTime
from app.core.database import Base
import datetime

class DiagnosticoDB(Base):
    __tablename__ = "diagnosticos"

    id = Column(String, primary_key=True, index=True)
    id_ticket = Column(String, nullable=False, unique=True)
    falla_detectada = Column(String, nullable=False)
    repuesto_solicitado = Column(String, nullable=True)
    cantidad_repuesto = Column(String, nullable=True)
    estado = Column(String, default="EVALUADO", nullable=False)
    fecha_diagnostico = Column(DateTime, default=datetime.datetime.utcnow)
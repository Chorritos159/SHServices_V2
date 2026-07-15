from sqlalchemy import Column, String, DateTime, Float, Text
from app.core.database import Base
import datetime

class DiagnosticoDB(Base):
    __tablename__ = "diagnosticos"

    id = Column(String, primary_key=True, index=True)
    id_ticket = Column(String, nullable=False, unique=True)
    falla_detectada = Column(String, nullable=False)
    # Fase 3: precio de la reparación + lista de repuestos serializada como JSON.
    precio_reparacion = Column(Float, default=0.0, nullable=False)
    repuestos_json = Column(Text, nullable=True)  # [{"codigo_repuesto": "REP-001", "cantidad": 2}, ...]
    estado = Column(String, default="DIAGNOSTICADO", nullable=False)
    fecha_diagnostico = Column(DateTime, default=datetime.datetime.utcnow)

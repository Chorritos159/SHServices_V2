from sqlalchemy import Column, String
from app.core.database import Base


class UsuarioDB(Base):
    """Empleado del sistema. Persistido en PostgreSQL (ya no en memoria)."""
    __tablename__ = "usuarios"

    usuario = Column(String, primary_key=True, index=True)
    password = Column(String, nullable=False)  # demo: texto plano (igual que el resto del proyecto)
    rol = Column(String, nullable=False)        # ADMIN | CAJA | TECNICO
    sede = Column(String, nullable=False)       # PIURA, LIMA, etc.

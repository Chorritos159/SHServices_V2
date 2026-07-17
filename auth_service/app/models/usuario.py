from sqlalchemy import Column, String
from app.core.database import Base


class UsuarioDB(Base):
    """Empleado del sistema. Persistido en PostgreSQL (ya no en memoria)."""
    __tablename__ = "usuarios"

    usuario = Column(String, primary_key=True, index=True)
    # Hash bcrypt con salt (OWASP A02). Nunca texto plano: ver app/core/password.py.
    # Las filas legadas en texto plano se migran solas en el primer login exitoso.
    password = Column(String, nullable=False)
    rol = Column(String, nullable=False)        # ADMIN | CAJA | TECNICO
    sede = Column(String, nullable=False)       # PIURA, LIMA, etc.

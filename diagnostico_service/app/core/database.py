from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
import os

# Cadena de conexión hacia el contenedor 'postgres-db' (Compose inyecta DATABASE_URL).
# El default ahora apunta al servicio Docker, ya no a localhost.
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://admin:password123@postgres-db:5432/shservices_db"
)

# pool_pre_ping: valida la conexión con un SELECT 1 antes de entregarla (reconexión
#   transparente si PostgreSQL se reinició y dejó conexiones muertas en el pool).
# pool_recycle: descarta conexiones con más de 280s para evitar cierres del servidor.
engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, pool_recycle=280)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependencia para inyectar la sesión de base de datos en las rutas
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
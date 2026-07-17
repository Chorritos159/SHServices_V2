from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
import os

# Conexión del Gateway a PostgreSQL. El Gateway persiste aquí SOLO su outbox
# transaccional (store-and-forward): las escrituras del cliente que no pudieron
# entregarse a un microservicio caído quedan guardadas y se reintentan solas.
# Misma base que el resto de servicios (Compose inyecta DATABASE_URL).
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://admin:password123@postgres-db:5432/shservices_db",
)

# pool_pre_ping: valida la conexión (SELECT 1) antes de entregarla, para
# reconectar de forma transparente si PostgreSQL se reinició.
engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, pool_recycle=280)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

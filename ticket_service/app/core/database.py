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
# Dimensionado del POOL de conexiones. Los valores por defecto de SQLAlchemy
# (pool_size=5, max_overflow=10, pool_timeout=30) se quedaron cortos y lo
# destapó la corrida de carga de 500k: aparecieron HTTP 500 con
#   "QueuePool limit of size 5 overflow 10 reached, connection timed out"
# Dos problemas, no uno:
#
#   1. 15 conexiones por servicio no dan para la concurrencia real.
#   2. pool_timeout=30s era PEOR que quedarse sin conexión: el Gateway corta
#      a los 8s, así que el cliente ya se había ido y el worker seguía 22s
#      más esperando un hueco, ocupando un hilo para nadie.
#
# Ahora: 20 conexiones por servicio (10 + 10 de overflow) y espera de 5s. Si
# en 5s no hay conexión, el servicio está saturado de verdad y conviene
# decirlo rápido (se traduce en 503, no en 500 — ver app/core/exceptions.py).
#
# El total (8 servicios x 20 = 160) cabe porque PostgreSQL sube a
# max_connections=200 en docker-compose.yml. Con los 100 de fábrica no
# entraba, y ese era el techo real del sistema.
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
POOL_MAX_OVERFLOW = int(os.getenv("DB_POOL_MAX_OVERFLOW", "10"))
POOL_TIMEOUT_S = float(os.getenv("DB_POOL_TIMEOUT", "5"))

_OPCIONES_POOL = {
    "pool_pre_ping": True,   # valida con SELECT 1: reconecta solo si Postgres se reinició
    "pool_recycle": 280,     # descarta conexiones viejas antes de que las cierre el servidor
}
# El dimensionado del pool solo aplica a PostgreSQL. SQLite —que usan los tests
# unitarios para poder importar estos módulos sin psycopg2— usa
# SingletonThreadPool, que no acepta `max_overflow` ni `pool_timeout` y revienta
# con TypeError al construir el engine.
if not SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    _OPCIONES_POOL.update({
        "pool_size": POOL_SIZE,
        "max_overflow": POOL_MAX_OVERFLOW,
        "pool_timeout": POOL_TIMEOUT_S,
    })

engine = create_engine(SQLALCHEMY_DATABASE_URL, **_OPCIONES_POOL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependencia para inyectar la sesión de base de datos en las rutas
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
"""Configuración de los tests unitarios.

Los módulos de resiliencia del Gateway (`app/core/…`) son **Python puro** (solo
usan `time`), así que se pueden importar y probar sin Docker, sin base de datos
y sin red. Aquí solo se añade `api_gateway/` al path para poder hacer
`from app.core.resilience import CircuitBreaker`.
"""
import os
import sys

# El outbox importa `app.core.database`, que crea el engine SQLAlchemy al
# importarse. Con la URL de PostgreSQL exigiría el driver psycopg2; se apunta a
# SQLite en memoria para que el import funcione sin instalar nada más. Los tests
# no tocan la base: solo prueban lógica pura (backoff, textos).
os.environ.setdefault("DATABASE_URL", "sqlite://")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "api_gateway"))

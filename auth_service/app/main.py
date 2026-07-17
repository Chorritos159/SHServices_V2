from fastapi import FastAPI
from app.api import health, auth
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.exceptions import (
    global_exception_handler, http_exception_handler, validation_exception_handler,
)
from app.core.logger import get_logger
from app.core.database import engine, SessionLocal, Base
from app.core import password as pwd
from app.models.usuario import UsuarioDB

logger = get_logger("auth-service")

# Crea la tabla 'usuarios' en PostgreSQL si no existe.
Base.metadata.create_all(bind=engine)


# Usuarios base de la demo. Solo hay dos sedes reales: PIURA y TALARA (no LIMA).
# El admin queda en PIURA; hay caja y tecnico en cada sede.
_USUARIOS_BASE = [
    ("admin",     "admin123",    "ADMIN",   "PIURA"),
    ("caja01",    "caja123",     "CAJA",    "PIURA"),
    ("tecnico01", "tecnico123",  "TECNICO", "PIURA"),
    ("caja02",    "caja123",     "CAJA",    "TALARA"),
    ("tecnico02", "tecnico123",  "TECNICO", "TALARA"),
]


def seed_usuarios_base():
    """
    SEED de credenciales maestras: inserta los usuarios base que falten.
    Garantiza que el sistema NUNCA quede inaccesible por falta de credenciales
    (incluso tras borrar el volumen). Es idempotente: no duplica.

    Ademas corrige la sede LIMA de una version anterior del seed: LIMA no es una
    sede valida del negocio (solo PIURA y TALARA), asi que se migra a PIURA.
    """
    db = SessionLocal()
    try:
        # Correccion idempotente: cualquier usuario que quedo en LIMA pasa a PIURA.
        migrados = db.query(UsuarioDB).filter(UsuarioDB.sede == "LIMA").update({UsuarioDB.sede: "PIURA"})
        if migrados:
            logger.info(f"Sede LIMA corregida a PIURA en {migrados} usuario(s).")

        existentes = {u.usuario for u in db.query(UsuarioDB.usuario).all()}
        nuevos = [
            UsuarioDB(usuario=u, password=pwd.hashear(p), rol=r, sede=s)
            for (u, p, r, s) in _USUARIOS_BASE if u not in existentes
        ]
        if nuevos:
            # Las credenciales de demo se hashean igual que cualquier otra
            # (OWASP A02): ni siquiera el seed escribe texto plano en la BD.
            db.add_all(nuevos)
            db.commit()
            logger.info(f"Seed de usuarios: {len(nuevos)} usuario(s) creados "
                        f"({', '.join(u.usuario for u in nuevos)}).")
        else:
            db.commit()
            logger.info("Seed de usuarios omitido: todos ya existen.")
    finally:
        db.close()


seed_usuarios_base()

app = FastAPI(
    title="Servicio de Autenticación",
    description="Microservicio emisor de tokens JWT con gestión de usuarios en PostgreSQL.",
    version="1.0.0"
)

# Errores legibles y trazables (ver app/core/exceptions.py):
# 4xx/5xx explicitos, payloads invalidos y el ultimo recurso.
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)
app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1/auth")


@app.on_event("startup")
async def startup_event():
    logger.info("El Servicio de Autenticación (JWT) ha arrancado exitosamente.")

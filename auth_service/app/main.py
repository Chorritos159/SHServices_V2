from fastapi import FastAPI
from app.api import health, auth
from app.core.exceptions import global_exception_handler
from app.core.logger import get_logger
from app.core.database import engine, SessionLocal, Base
from app.core import password as pwd
from app.models.usuario import UsuarioDB

logger = get_logger("auth-service")

# Crea la tabla 'usuarios' en PostgreSQL si no existe.
Base.metadata.create_all(bind=engine)


def seed_usuarios_base():
    """
    SEED de credenciales maestras: si la tabla está VACÍA, inserta los 3 usuarios
    base. Garantiza que el sistema NUNCA quede inaccesible por falta de credenciales
    (incluso tras borrar el volumen). Es idempotente: no duplica si ya hay usuarios.
    """
    db = SessionLocal()
    try:
        if db.query(UsuarioDB).count() == 0:
            # Las credenciales de demo se hashean igual que cualquier otra
            # (OWASP A02): ni siquiera el seed escribe texto plano en la BD.
            db.add_all([
                UsuarioDB(usuario="admin",     password=pwd.hashear("admin123"),   rol="ADMIN",   sede="LIMA"),
                UsuarioDB(usuario="caja01",    password=pwd.hashear("caja123"),    rol="CAJA",    sede="PIURA"),
                UsuarioDB(usuario="tecnico01", password=pwd.hashear("tecnico123"), rol="TECNICO", sede="PIURA"),
            ])
            db.commit()
            logger.info("🌱 Seed aplicado: usuarios base (admin, caja01, tecnico01) creados.")
        else:
            logger.info("Seed omitido: ya existen usuarios en la base de datos.")
    finally:
        db.close()


seed_usuarios_base()

app = FastAPI(
    title="Servicio de Autenticación",
    description="Microservicio emisor de tokens JWT con gestión de usuarios en PostgreSQL.",
    version="1.0.0"
)

app.add_exception_handler(Exception, global_exception_handler)
app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1/auth")


@app.on_event("startup")
async def startup_event():
    logger.info("El Servicio de Autenticación (JWT) ha arrancado exitosamente.")

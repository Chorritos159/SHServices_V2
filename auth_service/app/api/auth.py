from fastapi import APIRouter, HTTPException, Request, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
import jwt
import os
import datetime
from app.core.logger import get_logger
from app.core.database import get_db
from app.models.usuario import UsuarioDB

router = APIRouter()
logger = get_logger("auth-service")

# La llave maestra se lee de variable de entorno (JWT_SECRET_KEY).
# DEBE ser idéntica a la del api_gateway o los tokens no validarán.
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "super_secreto_shservices_2026")
ALGORITHM = "HS256"
ROLES_VALIDOS = {"ADMIN", "CAJA", "TECNICO"}

# Esquema de seguridad Bearer (para proteger el alta de usuarios).
security_scheme = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    usuario: str = Field(..., description="Usuario (ej: admin, caja01, tecnico01)")
    password: str = Field(..., description="Contraseña")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UsuarioCreate(BaseModel):
    usuario: str = Field(..., min_length=3, description="Identificador único del empleado")
    password: str = Field(..., min_length=4, description="Contraseña inicial")
    rol: str = Field(..., description="ADMIN, CAJA o TECNICO")
    sede: str = Field(..., description="Sede del empleado (PIURA, LIMA, etc.)")


class UsuarioOut(BaseModel):
    usuario: str
    rol: str
    sede: str


def _exigir_admin(credentials: HTTPAuthorizationCredentials | None) -> dict:
    """
    Valida el JWT y exige rol ADMIN.
    Nota: /auth NO pasa por el Gateway (lo bloquea), así que aquí NO llegan las
    cabeceras X-User-*; el auth-service debe validar el token por sí mismo.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Falta el token Bearer.")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="El token ha expirado.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido o corrupto.")
    if payload.get("rol") != "ADMIN":
        raise HTTPException(status_code=403, detail="Solo un ADMIN puede gestionar usuarios.")
    return payload


@router.post("/login", response_model=TokenResponse, tags=["Seguridad"])
async def login(credenciales: LoginRequest, request: Request, db: Session = Depends(get_db)):
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id

    empleado = db.query(UsuarioDB).filter(UsuarioDB.usuario == credenciales.usuario).first()
    if empleado is None or empleado.password != credenciales.password:
        logger.warning(f"Intento de login fallido para usuario: {credenciales.usuario}")
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    # Fabricamos el pasaporte (Token JWT) con rol Y sede.
    tiempo_expiracion = datetime.datetime.utcnow() + datetime.timedelta(hours=2)
    payload = {
        "sub": empleado.usuario,
        "rol": empleado.rol,
        "sede": empleado.sede,
        "exp": tiempo_expiracion,
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    logger.info(f"🔑 Token JWT generado exitosamente para '{empleado.usuario}'")

    return TokenResponse(access_token=token, expires_in=7200)


@router.get("/usuarios", response_model=list[UsuarioOut], tags=["Seguridad"])
async def listar_usuarios(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Security(security_scheme),
):
    """Lista los empleados (sin contraseñas). Solo ADMIN."""
    _exigir_admin(credentials)
    empleados = db.query(UsuarioDB).order_by(UsuarioDB.usuario).all()
    return [{"usuario": e.usuario, "rol": e.rol, "sede": e.sede} for e in empleados]


@router.post("/usuarios", response_model=UsuarioOut, status_code=201, tags=["Seguridad"])
async def registrar_usuario(
    nuevo: UsuarioCreate,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Security(security_scheme),
):
    """Da de alta un empleado con su rol y sede en PostgreSQL. Solo ADMIN."""
    admin = _exigir_admin(credentials)

    rol = nuevo.rol.upper()
    if rol not in ROLES_VALIDOS:
        raise HTTPException(status_code=422, detail=f"Rol inválido. Use: {', '.join(sorted(ROLES_VALIDOS))}.")
    if db.query(UsuarioDB).filter(UsuarioDB.usuario == nuevo.usuario).first():
        raise HTTPException(status_code=409, detail="El usuario ya existe.")

    empleado = UsuarioDB(
        usuario=nuevo.usuario,
        password=nuevo.password,
        rol=rol,
        sede=nuevo.sede.upper(),
    )
    db.add(empleado)
    db.commit()
    logger.info(f"👤 Usuario '{nuevo.usuario}' ({rol}/{nuevo.sede.upper()}) registrado por '{admin.get('sub')}'.")

    return {"usuario": empleado.usuario, "rol": empleado.rol, "sede": empleado.sede}

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import jwt
import datetime
from app.core.logger import get_logger

router = APIRouter()
logger = get_logger("auth-service")

# La llave maestra (En producción se lee de variables de entorno)
SECRET_KEY = "super_secreto_shservices_2026"
ALGORITHM = "HS256"

class LoginRequest(BaseModel):
    usuario: str = Field(..., description="Usuario (ej: admin, caja01, tecnico01)")
    password: str = Field(..., description="Contraseña")

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

@router.post("/login", response_model=TokenResponse, tags=["Seguridad"])
async def login(credenciales: LoginRequest, request: Request):
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    
    # Base de datos simulada de empleados
    usuarios_validos = {
        "admin": "admin123",
        "caja01": "caja123",
        "tecnico01": "tecnico123"
    }

    if usuarios_validos.get(credenciales.usuario) != credenciales.password:
        logger.warning(f"Intento de login fallido para usuario: {credenciales.usuario}")
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    # Si es correcto, fabricamos el pasaporte (Token JWT)
    tiempo_expiracion = datetime.datetime.utcnow() + datetime.timedelta(hours=2)
    payload = {
        "sub": credenciales.usuario,
        "rol": "ADMIN" if credenciales.usuario == "admin" else "OPERADOR",
        "exp": tiempo_expiracion
    }
    
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    logger.info(f"🔑 Token JWT generado exitosamente para '{credenciales.usuario}'")

    return TokenResponse(
        access_token=token,
        expires_in=7200
    )
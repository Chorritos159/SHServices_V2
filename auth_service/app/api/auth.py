from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import jwt
import os
import datetime
from app.core.logger import get_logger

router = APIRouter()
logger = get_logger("auth-service")

# La llave maestra se lee de variable de entorno (JWT_SECRET_KEY).
# DEBE ser idéntica a la del api_gateway o los tokens no validarán.
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "super_secreto_shservices_2026")
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
    
    # Base de datos simulada de empleados: cada uno con su ROL y su SEDE.
    # Roles del dominio: ADMIN (gobierna), CAJA (recepción/ventas), TECNICO (diagnóstico).
    usuarios_validos = {
        "admin":     {"password": "admin123",   "rol": "ADMIN",   "sede": "LIMA"},
        "caja01":    {"password": "caja123",     "rol": "CAJA",    "sede": "PIURA"},
        "tecnico01": {"password": "tecnico123",  "rol": "TECNICO", "sede": "PIURA"},
    }

    empleado = usuarios_validos.get(credenciales.usuario)
    if empleado is None or empleado["password"] != credenciales.password:
        logger.warning(f"Intento de login fallido para usuario: {credenciales.usuario}")
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    # Si es correcto, fabricamos el pasaporte (Token JWT) con rol Y sede.
    tiempo_expiracion = datetime.datetime.utcnow() + datetime.timedelta(hours=2)
    payload = {
        "sub": credenciales.usuario,
        "rol": empleado["rol"],
        "sede": empleado["sede"],
        "exp": tiempo_expiracion
    }
    
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    logger.info(f"🔑 Token JWT generado exitosamente para '{credenciales.usuario}'")

    return TokenResponse(
        access_token=token,
        expires_in=7200
    )
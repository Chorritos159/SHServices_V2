from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

# El esquema de seguridad Bearer (para que Swagger ponga el botón "Authorize")
security_scheme = HTTPBearer()

# Debe ser EXACTAMENTE la misma llave y algoritmo que usaste en auth_service
SECRET_KEY = "super_secreto_shservices_2026"
ALGORITHM = "HS256"

def validar_token(credentials: HTTPAuthorizationCredentials = Security(security_scheme)):
    """Verifica que la petición traiga un token JWT válido antes de dejarla pasar."""
    token = credentials.credentials
    try:
        # Intentamos decodificar el pasaporte
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Acceso denegado: El token ha expirado.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Acceso denegado: Token inválido o corrupto.")
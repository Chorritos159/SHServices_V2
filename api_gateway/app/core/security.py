from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import os

# El esquema de seguridad Bearer (para que Swagger ponga el botón "Authorize")
security_scheme = HTTPBearer()

# Debe ser EXACTAMENTE la misma llave/algoritmo que auth_service.
# Se lee de la misma variable de entorno (JWT_SECRET_KEY) en ambos servicios.
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "super_secreto_shservices_2026")
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


def requiere_rol(*roles_permitidos: str):
    """
    Factory de dependencia para RBAC. Exige que el JWT contenga uno de los roles
    permitidos. Uso en cualquier router:  Depends(requiere_rol("ADMIN"))
    """
    def verificador(payload: dict = Depends(validar_token)):
        rol = payload.get("rol")
        if rol not in roles_permitidos:
            raise HTTPException(
                status_code=403,
                detail="Permisos insuficientes: se requiere rol " + " o ".join(roles_permitidos),
            )
        return payload
    return verificador
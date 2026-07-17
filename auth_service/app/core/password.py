"""Hashing de contraseñas (OWASP A02/A07).

Antes, las contraseñas se guardaban y comparaban en TEXTO PLANO: cualquiera
con acceso de lectura a la tabla `usuarios` (un dump, un backup, una
inyección SQL en otro servicio que comparte la BD) se llevaba todas las
credenciales en claro, y los usuarios suelen reutilizar contraseñas en
otros sistemas.

bcrypt con salt por contraseña y factor de coste configurable: no se puede
"deshashear", y el coste hace inviable un ataque de fuerza bruta masivo
aunque se filtre la tabla.

`verificar()` es tolerante con los hashes que aún no lo son (texto plano de
antes de esta migración) para no dejar a nadie fuera del sistema: si detecta
uno, lo compara en tiempo constante y avisa al llamador para que lo
re-hashee al vuelo (ver `login` en `app/api/auth.py`).
"""
import hmac

import bcrypt

# Coste 12: ~250ms por verificación en hardware típico — suficiente para
# frenar fuerza bruta sin que el login se sienta lento.
COSTE = 12
_PREFIJOS_BCRYPT = ("$2a$", "$2b$", "$2y$")


def hashear(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=COSTE)).decode("utf-8")


def es_hash(valor: str) -> bool:
    """True si el valor almacenado ya es un hash bcrypt (y no texto plano legado)."""
    return valor.startswith(_PREFIJOS_BCRYPT)


def verificar(password: str, almacenado: str) -> bool:
    """Compara la contraseña contra lo guardado, sea hash bcrypt o texto
    plano legado. En ambos casos la comparación es de tiempo constante: un
    `!=` normal filtra información por timing (cuántos caracteres coinciden).
    """
    if es_hash(almacenado):
        try:
            return bcrypt.checkpw(password.encode("utf-8"), almacenado.encode("utf-8"))
        except ValueError:
            return False
    return hmac.compare_digest(password, almacenado)

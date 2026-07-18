"""Manejo de errores: legible para quien llama, accionable para quien opera.

Dos audiencias distintas y opuestas:

- El CLIENTE recibe un JSON estable y entendible, sin filtraciones: nunca un
  traceback, un nombre de tabla ni un mensaje de la BD (OWASP A05: los
  detalles internos ayudan a un atacante y no ayudan al usuario).
- El OPERADOR recibe en el log el traceback completo, el tipo de excepcion y
  el correlationId para ir a buscar el resto de la traza.

El `trace_id` de la respuesta es el hilo entre ambos: el usuario lo reporta y
con el se encuentra el error exacto en Loki/Dozzle.
"""
import traceback

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import TimeoutError as SQLAlchemyPoolTimeout
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logger import get_logger, ERROR, RECHAZADO

logger = get_logger("exception-handler")


def _correlation_id(request: Request) -> str:
    return request.headers.get("x-correlation-id", "N/A")


def global_exception_handler(request: Request, exc: Exception):
    """Ultimo recurso: algo reviento y nadie lo previo. 500 honesto."""
    correlation_id = _correlation_id(request)

    # Pool de conexiones agotado: el servicio esta SATURADO, no roto. Merece un
    # 503 con Retry-After (degradacion con contrato, reintentable) y no un 500,
    # que significa "fallo algo que nadie previo" e impide al circuit breaker y
    # al cliente distinguir sobrecarga de averia. Lo destapo la carga de 500k.
    if isinstance(exc, SQLAlchemyPoolTimeout):
        logger.error(
            f"Pool de conexiones agotado en {request.method} {request.url.path}: "
            "el servicio no pudo obtener una conexion a la base de datos.",
            extra={"campos": {
                "operation": f"{request.method} {request.url.path}",
                "result": ERROR, "errorType": "PoolTimeout", "httpStatus": 503,
            }},
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": "Servicio saturado",
                "detalle": ("El servicio esta atendiendo mas solicitudes de las que puede "
                            "en este momento. Vuelve a intentarlo en unos segundos."),
                "trace_id": correlation_id,
            },
            headers={"Retry-After": "5"},
        )
    logger.extra["correlation_id"] = correlation_id
    logger.error(
        f"Error no controlado en {request.method} {request.url.path}: {exc}",
        exc_info=True,
        extra={"campos": {
            "operation": f"{request.method} {request.url.path}",
            "result": ERROR,
            "errorType": type(exc).__name__,
            # El traceback va en su propio campo: asi la linea sigue siendo un
            # JSON valido de una sola linea y se puede filtrar/agrupar.
            "traceback": traceback.format_exc(),
        }},
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "Error interno del servidor",
            "detalle": ("Algo fallo de nuestro lado al procesar la solicitud. "
                        "Vuelve a intentarlo; si persiste, reporta el trace_id."),
            "trace_id": correlation_id,
        },
    )


def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Rechazos de negocio (404, 409, 401...): el detalle YA es legible."""
    correlation_id = _correlation_id(request)
    logger.extra["correlation_id"] = correlation_id
    # 4xx = el cliente pidio algo que no se puede: WARNING, sin traceback.
    # 5xx lanzado a mano (p. ej. 503 de dependencia caida): ERROR.
    es_cliente = exc.status_code < 500
    logger.log(
        30 if es_cliente else 40,
        f"{request.method} {request.url.path} -> {exc.status_code}: {exc.detail}",
        extra={"campos": {
            "operation": f"{request.method} {request.url.path}",
            "result": RECHAZADO if es_cliente else ERROR,
            "httpStatus": exc.status_code,
        }},
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": _titulo(exc.status_code),
            "detalle": exc.detail,
            "trace_id": correlation_id,
        },
        headers=getattr(exc, "headers", None),
    )


def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Payload invalido: se traduce el error de Pydantic a algo legible.

    Pydantic devuelve una estructura anidada ([{'loc': ['body', 'x'], 'msg':
    'Field required', ...}]) util para una libreria, ilegible para una
    persona. Se convierte a "el campo 'x' es obligatorio".
    """
    correlation_id = _correlation_id(request)
    logger.extra["correlation_id"] = correlation_id

    problemas = []
    for err in exc.errors():
        # loc = ('body', 'campo', 0, 'subcampo') -> "campo.subcampo[0]"
        partes = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
        campo = ".".join(partes) or "cuerpo de la peticion"
        problemas.append({"campo": campo, "problema": _traducir(err)})

    logger.warning(
        f"{request.method} {request.url.path} -> 422: {len(problemas)} campo(s) invalido(s).",
        extra={"campos": {
            "operation": f"{request.method} {request.url.path}",
            "result": RECHAZADO,
            "httpStatus": 422,
            "camposInvalidos": [p["campo"] for p in problemas],
        }},
    )
    return JSONResponse(
        status_code=422,
        content={
            "error": "Datos invalidos",
            "detalle": "; ".join(f"{p['campo']}: {p['problema']}" for p in problemas),
            "campos": problemas,
            "trace_id": correlation_id,
        },
    )


def _titulo(status_code: int) -> str:
    return {
        400: "Solicitud incorrecta",
        401: "No autenticado",
        403: "Sin permisos",
        404: "No encontrado",
        409: "Conflicto con el estado actual",
        422: "Datos invalidos",
        429: "Demasiadas solicitudes",
        503: "Servicio no disponible",
        504: "Tiempo de espera agotado",
    }.get(status_code, "Error")


def _traducir(err: dict) -> str:
    tipo = err.get("type", "")
    msg = err.get("msg", "valor invalido")
    traducciones = {
        "missing": "es obligatorio y no llego",
        "string_too_short": "es mas corto de lo permitido",
        "greater_than_equal": "debe ser mayor o igual al minimo",
        "int_parsing": "debe ser un numero entero",
        "float_parsing": "debe ser un numero",
        "value_error": msg.replace("Value error, ", ""),
    }
    return traducciones.get(tipo, msg)

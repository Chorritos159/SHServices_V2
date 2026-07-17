"""Logging estructurado (S34). Un JSON por linea, campos consistentes.

Formato minimo que exige la S34: el registro debe permitir RECONSTRUIR la
operacion sin abrir el codigo.

    service        que servicio actuo
    operation      que operacion ejecuto
    <entidad>      que entidad cambio (idTicket, idFactura, codigo...)
    durationMs     cuanto tardo
    result         que resultado dejo (ok | duplicado | timeout | error...)
    correlationId  con que correlationId (une la operacion entre servicios)

Uso normal (una linea por operacion de negocio):

    log = get_logger("ticket-service")
    with operacion(log, "crear_ticket", evento="TicketCreado.v1", idTicket=tk) as op:
        ...                       # si algo revienta, se loguea result=error solo
        op.campos["sede"] = sede  # campos extra que se descubren a mitad

El context manager mide `durationMs` y decide el `result` solo, para que
nadie tenga que acordarse de cronometrar ni de loguear el camino de error.
"""
import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone

# Resultados canonicos (evita que cada servicio invente el suyo y que
# filtrar por `result` en Loki/Grafana sea una loteria).
OK = "ok"
DUPLICADO = "duplicado"
NO_ENCONTRADO = "no_encontrado"
RECHAZADO = "rechazado"      # regla de negocio dijo que no
ERROR = "error"              # fallo inesperado


class JSONFormatter(logging.Formatter):
    """Serializa cada registro como un JSON de una sola linea."""

    # Orden fijo: los campos base primero, siempre igual -> los logs se leen
    # en diagonal y son estables para parsear.
    def format(self, record):
        log = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "service": getattr(record, "service_name", "servicio-base"),
            "correlationId": getattr(record, "correlation_id", "N/A"),
            "message": record.getMessage(),
        }
        campos = getattr(record, "campos", None)
        if campos:
            log.update({k: v for k, v in campos.items() if v is not None})
        if record.exc_info:
            # Solo el tipo y el mensaje: el traceback completo va aparte y no
            # revienta la linea JSON.
            exc = record.exc_info[1]
            log["errorType"] = type(exc).__name__
            log["errorMessage"] = str(exc)
        return json.dumps(log, ensure_ascii=False, default=str)


class AdaptadorContextual(logging.LoggerAdapter):
    """LoggerAdapter que FUSIONA el `extra` por-llamada con el contexto base.

    El LoggerAdapter estandar de la libreria REEMPLAZA kwargs["extra"] con
    self.extra, descartando en silencio los campos que se pasan en la
    llamada: por eso hace falta este.
    """

    def process(self, msg, kwargs):
        extra = dict(self.extra)
        extra.update(kwargs.get("extra") or {})
        kwargs["extra"] = extra
        return msg, kwargs

    def operacion(self, nombre, mensaje=None, **campos):
        return operacion(self, nombre, mensaje=mensaje, **campos)

    def evento(self, mensaje, operation, result=OK, nivel=logging.INFO, **campos):
        """Log estructurado suelto, cuando no hay una operacion que cronometrar."""
        self.log(nivel, mensaje, extra={"campos": {"operation": operation, "result": result, **campos}})


@contextmanager
def operacion(logger, nombre, mensaje=None, nivel_ok=logging.INFO, **campos):
    """Envuelve una operacion de negocio y emite UNA linea al terminar.

    Mide la duracion, marca el `result` y, si algo revienta, loguea
    result=error con el tipo de excepcion antes de re-lanzarla (no la traga:
    quien llama sigue decidiendo que hacer con el fallo).
    """
    inicio = time.perf_counter()
    ctx = _Operacion(nombre, campos)
    try:
        yield ctx
    except Exception as exc:
        # Un rechazo de negocio (HTTPException 4xx: stock insuficiente, no
        # encontrado, transicion ilegal...) NO es un error del sistema: es el
        # servicio haciendo su trabajo. Se loguea como WARNING, sin traceback,
        # conservando el `result` que fijo la operacion (rechazado /
        # no_encontrado / ...). Se detecta por duck-typing para no acoplar
        # este modulo a FastAPI.
        codigo = getattr(exc, "status_code", None)
        esperada = isinstance(codigo, int) and 400 <= codigo < 500
        logger.log(
            logging.WARNING if esperada else logging.ERROR,
            ctx.mensaje_error or ctx.mensaje or f"Fallo la operacion '{nombre}': {exc}",
            exc_info=not esperada,
            extra={"campos": {
                "operation": nombre,
                "result": (ctx.result if esperada and ctx.result != OK else
                           (RECHAZADO if esperada else ERROR)),
                "durationMs": _ms(inicio),
                **({"httpStatus": codigo} if esperada else {}),
                **ctx.campos,
            }},
        )
        raise
    else:
        logger.log(
            nivel_ok,
            ctx.mensaje or mensaje or f"Operacion '{nombre}' completada.",
            extra={"campos": {
                "operation": nombre,
                "result": ctx.result,
                "durationMs": _ms(inicio),
                **ctx.campos,
            }},
        )


class _Operacion:
    """Handle que devuelve `operacion()`: permite ajustar el resultado, el
    mensaje y agregar campos que se descubren a mitad de la operacion."""

    __slots__ = ("nombre", "campos", "result", "mensaje", "mensaje_error")

    def __init__(self, nombre, campos):
        self.nombre = nombre
        self.campos = dict(campos)
        self.result = OK
        self.mensaje = None
        self.mensaje_error = None


def _ms(inicio):
    return round((time.perf_counter() - inicio) * 1000, 1)


def get_logger(service_name: str):
    logger = logging.getLogger(service_name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        # Sin propagacion: uvicorn ya tiene su handler y duplicaria cada linea.
        logger.propagate = False
    return AdaptadorContextual(logger, {"service_name": service_name, "correlation_id": "N/A"})

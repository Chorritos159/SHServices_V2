import asyncio
import os
import random
import time
import uuid
import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from app.core.security import validar_token
from app.core.logger import get_logger
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.exceptions import (
    global_exception_handler, http_exception_handler, validation_exception_handler,
)
from app.core.resilience import CircuitBreaker
from app.core.bulkhead import Bulkhead
from app.core.ratelimit import TokenBucket
from app.core import metricas
from app.core import outbox
from app.api import health

# 1. Inicializar el Gateway
app = FastAPI(
    title="API Gateway - SHServices",
    description="Enrutador central, inyector de Correlation-ID y Circuit Breaker.",
    version="2.0.0"
)
logger = get_logger("api-gateway")
# Errores legibles y trazables (ver app/core/exceptions.py):
# 4xx/5xx explicitos, payloads invalidos y el ultimo recurso.
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# 1.b Política CORS para el frontend Next.js.
# Orígenes explícitos (NUNCA "*" junto con allow_credentials=True: el navegador lo rechaza
# y sería un agujero de seguridad). Se configura por variable de entorno CORS_ORIGINS.
origenes_permitidos = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origenes_permitidos,
    allow_credentials=True,   # necesario para cookies HttpOnly
    allow_methods=["*"],
    allow_headers=["*"],
)

# El health check se deja sin token para que Kubernetes o Docker puedan revisarlo.
# Se monta en /api/v1/health (compatibilidad) y en /health (usado por el HEALTHCHECK del Dockerfile).
app.include_router(health.router, prefix="/api/v1")
app.include_router(health.router)

# Observabilidad: expone /metrics para Prometheus (endpoint público, fuera del candado JWT
# porque el catch-all protegido vive bajo /api/v1/, no en la raíz).
#
# MODO MULTIPROCESO: con 8 workers de Gunicorn (ADR-0015) cada proceso tenía su
# propio registro en memoria y /metrics devolvía SOLO el del worker que
# contestara el scrape — los contadores subestimaban (medido: 30 peticiones
# enviadas, 21 reportadas). `prometheus_fastapi_instrumentator` lo resuelve
# solo cuando existe PROMETHEUS_MULTIPROC_DIR: los workers escriben sus
# muestras en archivos de ese directorio y el scrape las AGREGA.
#
# El directorio se limpia en el `command` del contenedor, ANTES de arrancar
# gunicorn — NO aquí. Hacerlo en este módulo fue un error que costó una
# iteración: este archivo lo importa CADA worker, así que cada uno borraba los
# ficheros que los otros ya habían escrito y los contadores quedaban a cero.
# Una variable de entorno como guarda tampoco sirve: cada proceso tiene su
# propia copia y ninguno ve la del vecino.
_DIR_MULTIPROC = os.getenv("PROMETHEUS_MULTIPROC_DIR")
if _DIR_MULTIPROC:
    os.makedirs(_DIR_MULTIPROC, exist_ok=True)

Instrumentator().instrument(app).expose(app)

# 2. Mapa de Microservicios para Docker
MICROSERVICIOS = {
    "tickets": "http://toxiproxy:8666",          # <-- vía Toxiproxy (Chaos Engineering)
    "almacen": "http://toxiproxy:8667",          # <-- vía Toxiproxy (Chaos Engineering)
    "auth": "http://auth-service:80",
    "diagnosticos": "http://toxiproxy:8669",     # <-- vía Toxiproxy (Chaos Engineering)
    "facturas": "http://toxiproxy:8668",         # <-- vía Toxiproxy (Chaos Engineering)
    "auditoria": "http://toxiproxy:8670",         # <-- vía Toxiproxy (Chaos Engineering)
    "notificaciones": "http://toxiproxy:8671"     # <-- vía Toxiproxy (Chaos Engineering)
}

# 2.b Política RBAC del Gateway.
# La verificación de rol vive en el BACKEND (nunca confíes en que el frontend oculte botones).
# Aquí: las operaciones de borrado sobre cualquier servicio exigen rol ADMIN.
METODOS_SOLO_ADMIN = {"DELETE"}

# 2.c Política de resiliencia (S34).
# Timeout por operación (segundos): estricto para lecturas, algo más laxo para
# escrituras que orquestan (diagnóstico llama a almacén). Un timeout corta la
# espera para no "colgarse" ante una dependencia lenta.
TIMEOUTS = {
    "auth": 3.0, "tickets": 3.0, "almacen": 3.0, "diagnosticos": 5.0,
    "facturas": 4.0, "auditoria": 3.0, "notificaciones": 3.0,
}
TIMEOUT_DEFAULT = 5.0

# Modo PRUEBA DE CARGA (Fase 5, S34), por variables de entorno:
# - TIMEOUT_FACTOR multiplica los timeouts para que un pico de latencia bajo
#   presión NO se convierta en 504 (que abriría el circuito y frenaría todo).
# - CIRCUIT_BREAKER_DISABLED=1 apaga el fail-fast del breaker, para medir el
#   throughput CRUDO del backend (atender todas). En producción/demo se dejan
#   en 1 y "" (breaker activo): son SOLO para las corridas de carga.
TIMEOUT_FACTOR = float(os.getenv("TIMEOUT_FACTOR", "1"))
_BREAKER_ON = os.getenv("CIRCUIT_BREAKER_DISABLED", "").strip().lower() not in ("1", "true", "yes")

# Métodos que MUTAN estado: son los que encolamos si el servicio está caído.
# Las lecturas (GET/HEAD) no se encolan (basta reintentarlas en vivo) y DELETE
# se deja fuera por ser destructivo y exclusivo de ADMIN.
METODOS_ESCRITURA = {"POST", "PUT", "PATCH"}

# Un circuit breaker por servicio destino (aísla el estado de salud de cada uno).
BREAKERS = {svc: CircuitBreaker(svc) for svc in MICROSERVICIOS}
_aperturas_vistas = dict.fromkeys(MICROSERVICIOS, 0)
# Último estado logueado por servicio: para emitir UNA línea por TRANSICIÓN
# (CLOSED->OPEN, OPEN->HALF_OPEN, HALF_OPEN->CLOSED) y no una por request.
_estado_visto = dict.fromkeys(MICROSERVICIOS, "CLOSED")

# Inicialización de TODAS las series de métricas al arranque (Fase 4/5, S34).
# Un Counter de prometheus_client no existe como serie hasta su primer .inc():
# sin esto, los paneles de Grafana muestran "No data" (en vez de 0) mientras
# no haya ocurrido nunca un retry/fallback/timeout/rechazo — lo que se lee
# como "la métrica está rota", cuando en realidad significa "no ha pasado
# nada malo todavía". Tocar .labels(...) crea la serie en 0.
_OUTCOMES = ("ok", "client_error", "server_error", "timeout", "unreachable", "circuit_open")
_RAZONES_BULKHEAD = ("saturado", "shed_baja_prioridad")
for _svc in MICROSERVICIOS:
    metricas.CIRCUIT_STATE.labels(service=_svc).set(0)   # arranca en CLOSED
    metricas.CIRCUIT_OPENS.labels(service=_svc)
    metricas.RETRIES.labels(service=_svc)
    metricas.FALLBACKS.labels(service=_svc)
    metricas.TIMEOUTS.labels(service=_svc)
    metricas.BULKHEAD_IN_FLIGHT.labels(service=_svc).set(0)
    for _outcome in _OUTCOMES:
        metricas.REQUESTS.labels(service=_svc, outcome=_outcome)
    for _razon in _RAZONES_BULKHEAD:
        metricas.BULKHEAD_REJECTS.labels(service=_svc, razon=_razon)


# Mensaje claro por cada transicion de estado del breaker. La clave es el
# par (estado_anterior -> estado_nuevo); asi el log DICE que mecanismo de
# resiliencia actuo y en que direccion, sin que haya que deducirlo.
_TRANSICIONES = {
    ("CLOSED", "OPEN"):
        ("error", "Circuit breaker ABIERTO para '{s}': demasiados fallos seguidos. "
                  "Se activa fail-fast (se deja de llamar a '{s}' durante el cooldown)."),
    ("OPEN", "HALF_OPEN"):
        ("warning", "Circuit breaker en HALF_OPEN para '{s}': cooldown vencido, "
                    "se prueba UNA sonda para ver si '{s}' ya se recupero."),
    ("HALF_OPEN", "CLOSED"):
        ("info", "Circuit breaker CERRADO para '{s}': la sonda respondio OK, "
                 "'{s}' se recupero y el trafico vuelve a fluir normal."),
    ("HALF_OPEN", "OPEN"):
        ("warning", "Circuit breaker REABIERTO para '{s}': la sonda volvio a fallar, "
                    "'{s}' sigue caido; se reinicia el cooldown."),
    # Fallback: si la sonda cierra el circuito tan rapido que no se observo el
    # estado HALF_OPEN intermedio, se registra la recuperacion igual.
    ("OPEN", "CLOSED"):
        ("info", "Circuit breaker CERRADO para '{s}': la sonda respondio OK, "
                 "'{s}' se recupero y el trafico vuelve a fluir normal."),
}


def _sincronizar_metricas_breaker(service: str, breaker: CircuitBreaker):
    """Refleja el estado del breaker en Prometheus y loguea las TRANSICIONES.

    El log de transiciones es lo que permite ver en Loki/Dozzle, para CADA
    servicio, cuando su circuito abre, cuando prueba recuperarse y cuando se
    cierra — una linea por cambio de estado, no una por request.
    """
    metricas.CIRCUIT_STATE.labels(service=service).set(breaker.estado_numerico())
    nuevas = breaker.aperturas - _aperturas_vistas[service]
    if nuevas > 0:
        metricas.CIRCUIT_OPENS.labels(service=service).inc(nuevas)
        _aperturas_vistas[service] = breaker.aperturas

    anterior = _estado_visto[service]
    actual = breaker.estado
    if actual != anterior:
        _estado_visto[service] = actual
        entrada = _TRANSICIONES.get((anterior, actual))
        if entrada:
            nivel, plantilla = entrada
            getattr(logger, nivel)(
                plantilla.format(s=service),
                extra={"campos": {
                    "operation": "circuit_breaker",
                    "event": service,
                    "circuitFrom": anterior,
                    "circuitTo": actual,
                    "result": "recuperado" if actual == "CLOSED" else "degradado",
                }},
            )

# Retry responsable (S34): reintentar NO es insistir ciegamente. Solo errores
# transitorios, solo lecturas (un POST con timeout tiene efecto incierto), y con
# BACKOFF ESCALONADO + JITTER.
#
# Politica de backoff del sistema (S34): 3s -> 5s -> 8s. Escalona la espera para
# no seguir golpeando una dependencia enferma, y el JITTER (hasta 1s extra)
# evita que muchos clientes reintenten sincronizados y la ahoguen justo cuando
# esta intentando recuperarse. La misma secuencia se usa en el worker del outbox
# (app/core/outbox.py) y en el generador de carga (pruebas/lib/carga_nodos.py).
BACKOFF_SEQ = (3.0, 5.0, 8.0)
MAX_INTENTOS = len(BACKOFF_SEQ) + 1   # 4 intentos = 3 esperas (3s, 5s, 8s)


def _backoff_jitter(intento: int) -> float:
    """Espera antes del reintento numero `intento`: 3s, 5s, 8s (+ jitter).

    En la practica el circuit breaker corta antes: tras 3 fallos seguidos abre y
    el reintento deja de permitirse (la condicion exige `estado == CLOSED`), asi
    que una dependencia caida NO se traduce en esperar los 16s completos.
    """
    base = BACKOFF_SEQ[min(intento - 1, len(BACKOFF_SEQ) - 1)]
    return base + random.uniform(0, 1.0)


def _explicar_circuito(breaker) -> str:
    """Frase que dice en qué punto está el circuito y qué pasa a continuación.

    El mensaje anterior era "Circuit breaker: el servicio X esta inaccesible
    (estado: CLOSED)" y se leía como que el breaker estaba roto: nombra al
    circuit breaker y a CLOSED junto a "inaccesible", que parecen
    contradecirse. En realidad CLOSED tras un fallo es lo correcto — el
    circuito abre al TERCER fallo consecutivo, no al primero.

    Quien lee el log en mitad de un incidente no debería tener que conocer el
    umbral de memoria para interpretarlo, así que la frase lo lleva dentro.
    """
    if breaker.estado == "OPEN":
        return (f"Circuito OPEN: las siguientes peticiones haran fail-fast "
                f"durante {breaker.cooldown_seg:.0f}s, sin gastar timeout.")
    if breaker.estado == "HALF_OPEN":
        return "Circuito HALF_OPEN: la sonda de recuperacion fallo, vuelve a abrirse."
    return (f"Circuito CLOSED: fallo {breaker.fallos_consecutivos} de "
            f"{breaker.umbral_consecutivos} consecutivos para abrir.")


def _log_retry(service: str, intento: int, motivo: str, espera: float):
    """Deja constancia de que el mecanismo de RETRY se activo (no solo la metrica).

    Un reintento significa que algo salio mal y la resiliencia esta
    compensando: debe verse en la traza, no solo en un contador de Grafana.
    """
    logger.warning(
        f"Retry a '{service}' (intento {intento}/{MAX_INTENTOS}) por {motivo}; "
        f"backoff {espera:.2f}s antes de reintentar.",
        extra={"campos": {"operation": "retry", "event": service,
                           "retryAttempt": intento, "motivo": motivo,
                           "backoffSeg": round(espera, 2), "result": "degradado"}},
    )


# ---------------------------------------------------------------------
# Contención de recursos (Fase 2, S34): bulkhead + rate limit + shedding.
# ---------------------------------------------------------------------

# Cupo de llamadas EN VUELO por servicio. "tickets" es el más transitado
# (recepción + técnico + garantías) y recibe más cupo; "auditoria" y
# "notificaciones" son de lectura/soporte y usan menos.
BULKHEAD_LIMITES = {
    "auth": 8, "tickets": 12, "almacen": 8, "diagnosticos": 8,
    "facturas": 8, "auditoria": 5, "notificaciones": 5,
}
BULKHEAD_LIMITE_DEFAULT = 8

# Override opcional del cupo del bulkhead (Fase 5, S34): en las PRUEBAS DE CARGA
# se amplía (junto con el rate limit) para medir el throughput real del backend
# y que TODAS las peticiones se atiendan, sin que el bulkhead rechace con 503.
# Vacío = límites normales de producción/demo.
_BULKHEAD_OVERRIDE = os.getenv("BULKHEAD_LIMITE_OVERRIDE", "").strip()


def _limite_bulkhead(svc: str) -> int:
    if _BULKHEAD_OVERRIDE:
        return int(_BULKHEAD_OVERRIDE)
    return BULKHEAD_LIMITES.get(svc, BULKHEAD_LIMITE_DEFAULT)


BULKHEADS = {svc: Bulkhead(svc, _limite_bulkhead(svc)) for svc in MICROSERVICIOS}

# Umbral de ocupación (S34, shedding): por encima de este %, el bulkhead
# todavía tiene cupo técnico pero ya se reserva para tráfico de prioridad
# alta — el tráfico de baja prioridad se rechaza preventivamente.
UMBRAL_SHED = 0.7

# Rate limit GLOBAL del Gateway (protege al proceso mismo, no a una
# dependencia): 40 peticiones de ráfaga, repuestas a 20/s en régimen por
# defecto. Configurable por entorno (Fase 5, S34) para poder AMPLIARLO
# temporalmente en las pruebas de carga 500k/1M — así se mide el throughput
# real del backend y no el techo del propio limitador.
RATE_LIMITER = TokenBucket(
    capacidad=int(os.getenv("RATE_LIMIT_BURST", "40")),
    tasa_por_seg=float(os.getenv("RATE_LIMIT_RPS", "20")),
)

global_client: httpx.AsyncClient | None = None


def _prioridad(service: str, metodo: str) -> str:
    """Bajo contención se protege primero lo crítico del negocio (S34)."""
    if metodo in ("POST", "PUT", "PATCH", "DELETE"):
        return "alta"      # crear/actualizar tickets, facturas, diagnósticos
    if service == "auditoria":
        return "baja"      # traza/reporting: puede esperar sin bloquear la operación
    return "media"         # listados y consultas generales


# Sampling de logs (S34): bajo carga alta, loguear cada request individual
# es I/O que compite con el tráfico real. Se conservan SIEMPRE los primeros
# N por segundo (visibilidad total en carga normal); del excedente, solo se
# muestrea 1 de cada TASA_MUESTREO. Los warnings/errors del gateway (circuito
# abierto, timeout, fallback) NO pasan por este muestreo: se loguean siempre.
UMBRAL_MUESTREO_RPS = 30
TASA_MUESTREO = 10
_ventana_muestreo = {"inicio": time.monotonic(), "contador": 0}


def _debe_loggear_rutina() -> bool:
    ahora = time.monotonic()
    if ahora - _ventana_muestreo["inicio"] >= 1.0:
        _ventana_muestreo["inicio"] = ahora
        _ventana_muestreo["contador"] = 0
    _ventana_muestreo["contador"] += 1
    if _ventana_muestreo["contador"] <= UMBRAL_MUESTREO_RPS:
        return True
    if _ventana_muestreo["contador"] % TASA_MUESTREO == 0:
        return True
    metricas.LOGS_MUESTREADOS.inc()
    return False


class _DummyContext:
    def __init__(self, client):
        self.client = client
    async def __aenter__(self):
        return self.client
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


async def _proxy_resiliente(service: str, path: str, url_destino: str, metodo: str,
                            body: bytes, headers: dict, correlation_id: str) -> JSONResponse:
    """Cadena de protección S34: circuit breaker -> timeout -> retry seguro -> fallback.

    Devuelve siempre una respuesta HTTP semántica (nunca un 500 opaco ni un
    cuelgue): 503 si el circuito está abierto o la dependencia cae, 504 si hay
    timeout. Actualiza las métricas Prometheus de resiliencia.
    """
    breaker = BREAKERS[service]
    timeout = TIMEOUTS.get(service, TIMEOUT_DEFAULT) * TIMEOUT_FACTOR
    # Solo GET/HEAD son seguros de reintentar ante timeout/5xx (idempotentes).
    # Un POST con timeout tiene efecto incierto: reintentarlo puede duplicar.
    es_lectura = metodo in ("GET", "HEAD")
    inicio = time.monotonic()

    def _duracion_ms() -> float:
        return round((time.monotonic() - inicio) * 1000, 1)

    # Fail-fast: si el circuito está OPEN, ni siquiera golpeamos a la dependencia.
    # permite() puede mover OPEN->HALF_OPEN al vencer el cooldown; se sincroniza
    # inmediatamente despues para que ESA transicion quede logueada aunque la
    # sonda siguiente cierre el circuito enseguida.
    permitido = breaker.permite() if _BREAKER_ON else True
    _sincronizar_metricas_breaker(service, breaker)
    if not permitido:
        metricas.REQUESTS.labels(service=service, outcome="circuit_open").inc()
        metricas.FALLBACKS.labels(service=service).inc()
        logger.warning(
            f"Circuito OPEN para '{service}': fail-fast (la dependencia está en recuperación).",
            extra={"campos": {"operation": "proxy_request", "event": service,
                               "result": "circuit_open", "durationMs": _duracion_ms()}},
        )
        error_503 = JSONResponse(
            status_code=503,
            content={"error": "Service Unavailable",
                     "detalle": f"El servicio '{service}' está en recuperación (circuito abierto).",
                     "circuito": "OPEN", "trace_id": correlation_id},
            headers={"Retry-After": "5"},
        )
        return _encolar_o_error(service, path, metodo, body, headers, error_503)

    intento = 0
    async with _DummyContext(global_client or httpx.AsyncClient()) as client:
        while True:
            intento += 1
            try:
                response = await client.request(
                    method=metodo, url=url_destino, content=body,
                    headers=headers, timeout=timeout,
                )
                ok = response.status_code < 500       # 4xx = error de negocio, no de salud
                breaker.registrar(ok)
                _sincronizar_metricas_breaker(service, breaker)

                if not ok and es_lectura and intento < MAX_INTENTOS and breaker.estado == "CLOSED":
                    metricas.RETRIES.labels(service=service).inc()
                    espera = _backoff_jitter(intento)
                    _log_retry(service, intento, f"respuesta {response.status_code}", espera)
                    await asyncio.sleep(espera)
                    continue

                outcome = "ok" if response.status_code < 400 else ("client_error" if ok else "server_error")
                metricas.REQUESTS.labels(service=service, outcome=outcome).inc()
                duracion_ms = _duracion_ms()
                if _debe_loggear_rutina():
                    logger.info(
                        f"Proxy {metodo} '{service}' -> {response.status_code} ({duracion_ms}ms).",
                        extra={"campos": {"operation": "proxy_request", "event": service,
                                           "result": outcome, "durationMs": duracion_ms}},
                    )
                try:
                    data = response.json()
                except Exception:
                    data = response.text
                return JSONResponse(status_code=response.status_code, content=data)

            # OJO con el orden: TimeoutException es subclase de TransportError,
            # asi que va primero o nunca se alcanzaria.
            except httpx.TimeoutException:
                breaker.registrar(False)
                _sincronizar_metricas_breaker(service, breaker)
                if es_lectura and intento < MAX_INTENTOS and breaker.estado == "CLOSED":
                    metricas.RETRIES.labels(service=service).inc()
                    espera = _backoff_jitter(intento)
                    _log_retry(service, intento, f"timeout de {timeout}s", espera)
                    await asyncio.sleep(espera)
                    continue
                metricas.TIMEOUTS.labels(service=service).inc()
                metricas.REQUESTS.labels(service=service, outcome="timeout").inc()
                metricas.FALLBACKS.labels(service=service).inc()
                logger.error(
                    f"Timeout: '{service}' supero su presupuesto de {timeout}s (circuito: {breaker.estado}).",
                    extra={"campos": {"operation": "proxy_request", "event": service,
                                       "result": "timeout", "durationMs": _duracion_ms()}},
                )
                error_504 = JSONResponse(
                    status_code=504,
                    content={"error": "Gateway Timeout",
                             "detalle": (f"El servicio '{service}' tardo mas de {timeout}s en responder. "
                                         "Vuelve a intentarlo en unos segundos."),
                             "circuito": breaker.estado, "trace_id": correlation_id},
                )
                # Un timeout en una escritura es ambiguo (¿llegó a procesarse?).
                # Encolar es seguro: el reintento lleva la MISMA Idempotency-Key,
                # así que si ya se había procesado NO se duplica.
                return _encolar_o_error(service, path, metodo, body, headers, error_504)

            # TODA la familia de fallos de transporte, no solo ConnectError:
            # ReadError, WriteError, RemoteProtocolError, ProxyError, PoolTimeout...
            # Enumerar dos casos dejaba el resto sin capturar: se escapaban al
            # manejador global (500 opaco) y el breaker NUNCA se enteraba del
            # fallo. Se veia justo con 'tickets', el unico servicio que va via
            # Toxiproxy: al caer el upstream, Toxiproxy sigue vivo y acepta la
            # conexion TCP, luego la cierra -> httpx.ReadError, no ConnectError.
            except httpx.TransportError as exc:
                breaker.registrar(False)
                _sincronizar_metricas_breaker(service, breaker)

                # ConnectError = la conexion nunca se establecio, el request no
                # llego a ejecutarse: reintentar es seguro para cualquier metodo.
                # El resto (ReadError, RemoteProtocolError...) = la conexion SI
                # se abrio; el servidor pudo haber procesado la escritura antes
                # de cortar, asi que reintentar un POST podria duplicarla.
                nunca_llego = isinstance(exc, httpx.ConnectError)
                if (nunca_llego or es_lectura) and intento < MAX_INTENTOS and breaker.estado == "CLOSED":
                    metricas.RETRIES.labels(service=service).inc()
                    espera = _backoff_jitter(intento)
                    _log_retry(service, intento, f"fallo de transporte ({type(exc).__name__})", espera)
                    await asyncio.sleep(espera)
                    continue

                metricas.REQUESTS.labels(service=service, outcome="unreachable").inc()
                metricas.FALLBACKS.labels(service=service).inc()
                logger.error(
                    f"El servicio '{service}' esta inaccesible. "
                    f"{_explicar_circuito(breaker)}",
                    extra={"campos": {"operation": "proxy_request", "event": service,
                                       "result": "unreachable", "durationMs": _duracion_ms(),
                                       "errorType": type(exc).__name__,
                                       "circuito": breaker.estado,
                                       "fallosConsecutivos": breaker.fallos_consecutivos,
                                       "umbralApertura": breaker.umbral_consecutivos}},
                )
                error_503 = JSONResponse(
                    status_code=503,
                    content={"error": "Service Unavailable",
                             "detalle": f"El servicio '{service}' se encuentra temporalmente fuera de linea.",
                             "circuito": breaker.estado, "trace_id": correlation_id},
                    headers={"Retry-After": "5"},
                )
                return _encolar_o_error(service, path, metodo, body, headers, error_503)

# Tareas de fondo (worker del outbox y sonda del breaker). Hay que GUARDAR la
# referencia: asyncio solo mantiene una referencia débil a la tarea, así que sin
# esto el recolector de basura puede matarla a medio camino y el worker dejaría
# de reintentar las escrituras encoladas sin ningún aviso.
_TAREAS_FONDO: set = set()


def _lanzar_en_fondo(corutina):
    tarea = asyncio.create_task(corutina)
    _TAREAS_FONDO.add(tarea)
    tarea.add_done_callback(_TAREAS_FONDO.discard)
    return tarea


# Sonda ACTIVA del circuit breaker (recuperación automática).
# Cada cuánto el prober revisa los circuitos que no están CLOSED.
SONDA_BREAKER_INTERVALO_S = 5


async def bucle_sonda_breakers():
    """Recupera los circuitos SOLOS, sin necesidad de tráfico del cliente.

    Un circuit breaker clásico es "lazy": solo pasa OPEN -> HALF_OPEN -> CLOSED
    cuando llega una petición del cliente después del cooldown. Si nadie manda
    tráfico, el circuito se queda OPEN para siempre. Esta sonda recorre los
    breakers cada pocos segundos y, para los que NO están CLOSED y ya cumplieron
    el cooldown, manda un probe al `/health` del servicio (por la MISMA ruta que
    el tráfico real). Si responde, el circuito se cierra por sí mismo — el
    usuario NO tiene que mandar peticiones para que se recupere.
    """
    await asyncio.sleep(3)  # deja arrancar el resto del sistema
    while True:
        for service, breaker in BREAKERS.items():
            try:
                if breaker.estado == "CLOSED":
                    continue  # los sanos no se molestan
                # permite() mueve OPEN->HALF_OPEN si el cooldown venció y reclama
                # la sonda; devuelve False si sigue en cooldown o ya hay una en vuelo.
                if not breaker.permite():
                    _sincronizar_metricas_breaker(service, breaker)
                    continue
                base = MICROSERVICIOS[service]
                ok = False
                try:
                    async with httpx.AsyncClient() as client:
                        r = await client.get(f"{base}/health", timeout=3.0)
                        ok = r.status_code < 500
                except httpx.HTTPError:
                    ok = False
                # registrar() cierra el circuito si el probe salió bien, o lo
                # reabre (con nuevo cooldown) si falló. La transición la loguea
                # _sincronizar_metricas_breaker (una línea por cambio de estado).
                breaker.registrar(ok)
                _sincronizar_metricas_breaker(service, breaker)
            except Exception as exc:
                logger.error(
                    f"Fallo en la sonda del breaker de '{service}': {exc}",
                    extra={"campos": {"operation": "circuit_probe", "event": service, "result": "error"}},
                )
        await asyncio.sleep(SONDA_BREAKER_INTERVALO_S)


# 2.d Outbox transaccional (store-and-forward) + sonda del breaker.
# Al arrancar: creamos la tabla del outbox, lanzamos el worker que reintenta las
# escrituras encoladas hasta que el microservicio caído vuelve, y la sonda que
# recupera los circuitos automáticamente. Así ninguna escritura se pierde y los
# circuitos se cierran solos cuando el servicio revive.
@app.on_event("startup")
async def _iniciar_outbox():
    global global_client
    # pool_size amplio para absorber la concurrencia de todos los workers sin bloquear.
    limits = httpx.Limits(max_connections=1000, max_keepalive_connections=500)
    global_client = httpx.AsyncClient(limits=limits)

    try:
        outbox.crear_tablas()
    except Exception as exc:
        logger.error(f"No se pudo preparar la tabla del outbox: {exc}",
                     extra={"campos": {"operation": "outbox_init", "result": "error"}})
    _lanzar_en_fondo(outbox.bucle_drenaje(MICROSERVICIOS, BREAKERS))
    _lanzar_en_fondo(bucle_sonda_breakers())


@app.on_event("shutdown")
async def _cerrar_cliente_global():
    global global_client
    if global_client:
        await global_client.aclose()


def _encolar_o_error(service: str, path: str, metodo: str, body: bytes,
                     headers: dict, respuesta_error: JSONResponse) -> JSONResponse:
    """Ante un fallo de INDISPONIBILIDAD (no de negocio): si es una escritura,
    la encola y responde 202 (se enviará sola); si no, devuelve el error tal cual.
    """
    if metodo not in METODOS_ESCRITURA:
        return respuesta_error
    clave = headers.get("idempotency-key")
    if not clave:
        # Sin clave no podemos garantizar "no duplicar"; devolvemos el error.
        return respuesta_error
    resumen = outbox.encolar(
        idempotency_key=clave, servicio=service, metodo=metodo,
        path=path, body=body, headers=headers,
        url_interna=f"{MICROSERVICIOS[service]}/api/v1/{path}",
    )
    return JSONResponse(status_code=202, content=resumen)


# 3. Middleware de Observabilidad (Genera el Rastro)
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """Inyecta el X-Correlation-ID a cada petición que entra al sistema."""
    correlation_id = request.headers.get("x-correlation-id", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id
    logger.extra["correlation_id"] = correlation_id

    # Rate limit GLOBAL (S34): protege al Gateway mismo antes de gastar
    # tiempo en JWT/RBAC/proxy. No se aplica a /health ni /metrics (monitoreo).
    if request.url.path.startswith("/api/v1/") and not RATE_LIMITER.consumir():
        metricas.RATE_LIMIT_REJECTS.inc()
        espera = max(1, round(RATE_LIMITER.segundos_hasta_proximo_token()))
        logger.warning(
            "Rate limit: ráfaga por encima de la capacidad del Gateway.",
            extra={"campos": {"operation": "rate_limit", "result": "rejected"}},
        )
        respuesta = JSONResponse(
            status_code=429,
            content={"error": "Too Many Requests",
                     "detalle": "El Gateway está al límite de su capacidad. Reintenta en breve.",
                     "trace_id": correlation_id},
            headers={"Retry-After": str(espera)},
        )
        respuesta.headers["X-Correlation-ID"] = correlation_id
        return respuesta

    if _debe_loggear_rutina():
        logger.info(f"[{request.method}] Petición entrante -> {request.url.path}")

    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response

# 3.b Swagger UNIFICADO de todo el proyecto.
#
# Cada servicio publica su propio /docs, lo que obliga a abrir 8 pestañas para
# ver la API completa. Aquí se sirve UN solo Swagger UI con un desplegable que
# lista los 8 contratos.
#
# Los OpenAPI se piden a través del Gateway (`/servicios/openapi/{n}.json`) y no
# directo a `localhost:800X` a propósito: así la página funciona aunque los
# puertos de los servicios no estén publicados al host, y el navegador habla
# siempre con un solo origen (sin CORS de por medio).

# Orden de presentación: primero por dónde entra todo, luego el ciclo del
# negocio, y al final lo transversal.
_ORDEN_SERVICIOS = [
    ("auth", "Auth · identidad, roles y sedes"),
    ("tickets", "Tickets · ciclo de vida del equipo"),
    ("diagnosticos", "Diagnóstico · asignación y diagnóstico técnico"),
    ("almacen", "Almacén · inventario, reservas y ventas"),
    ("facturas", "Facturación · cobros y garantías"),
    ("auditoria", "Auditoría · traza de eventos"),
    ("notificaciones", "Notificaciones · alertas y webhooks"),
]


@app.get("/servicios/openapi/{servicio}.json", include_in_schema=False)
async def openapi_de_servicio(servicio: str):
    """Devuelve el OpenAPI de un microservicio, pedido por el Gateway."""
    base = MICROSERVICIOS.get(servicio)
    if not base:
        return JSONResponse(
            status_code=404,
            content={"error": "No encontrado",
                     "detalle": f"No existe un servicio llamado '{servicio}'."},
        )
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base}/openapi.json", timeout=5.0)
        return JSONResponse(status_code=resp.status_code, content=resp.json())
    except httpx.HTTPError as exc:
        # Un servicio caído no debe romper la página entera: se devuelve un
        # OpenAPI mínimo y válido, para que el resto del desplegable siga usable.
        return JSONResponse(
            status_code=200,
            content={
                "openapi": "3.1.0",
                "info": {"title": f"{servicio} (no disponible)", "version": "0.0.0",
                         "description": f"El servicio no respondió: {type(exc).__name__}."},
                "paths": {},
            },
        )


@app.get("/docs-todos", include_in_schema=False, response_class=HTMLResponse)
async def swagger_unificado():
    """Un solo Swagger UI con los 8 contratos del sistema en un desplegable."""
    urls = ",".join(
        f'{{url:"/servicios/openapi/{clave}.json",name:"{nombre}"}}'
        for clave, nombre in _ORDEN_SERVICIOS
    )
    return HTMLResponse(f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>SHServices · API completa</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
  <style>
    body {{ margin:0; }}
    .cabecera {{ background:#0f172a; color:#e2e8f0; padding:14px 22px;
                 font-family:system-ui,sans-serif; }}
    .cabecera h1 {{ margin:0; font-size:17px; }}
    .cabecera p  {{ margin:4px 0 0; font-size:13px; color:#94a3b8; }}
  </style>
</head>
<body>
  <div class="cabecera">
    <h1>SHServices V2 — API completa</h1>
    <p>Los 8 contratos del sistema (API Gateway + 7 microservicios).
       Elige uno en el desplegable de arriba a la derecha.</p>
  </div>
  <div id="swagger"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
  <script>
    // El desplegable de contratos (`urls`) lo dibuja el StandaloneLayout: sin
    // el preset standalone, Swagger UI ignora `urls` y muestra "No API
    // definition provided".
    SwaggerUIBundle({{
      dom_id: "#swagger",
      urls: [{{url:"/openapi.json",name:"API Gateway · entrada única del sistema"}},{urls}],
      "urls.primaryName": "API Gateway · entrada única del sistema",
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
      layout: "StandaloneLayout",
      deepLinking: true
    }});
  </script>
</body>
</html>""")


# 3.c LOGIN a través del Gateway (cierra los hallazgos 3 y 4 de OWASP).
#
# Antes el Gateway bloqueaba `/api/v1/auth/*` con un 403 y el frontend hacía
# login DIRECTO contra el puerto 8003. Eso dejaba tres agujeros:
#
#   - El login era la única operación sin rate limit (el del Gateway no lo
#     tocaba), así que se podían probar contraseñas sin freno.
#   - No tenía circuit breaker: si auth-service caía, el usuario recibía un
#     error crudo de red del navegador en vez de un mensaje entendible.
#   - Obligaba a publicar el puerto 8003 al host, saltándose el Gateway.
#
# Esta ruta va ANTES del enrutador genérico y NO exige token —nadie lo tiene
# todavía—, pero sí pasa por rate limit, bloqueo por intentos y breaker.

# Cubo aparte, mucho más estrecho que el global (20 rps): un humano no hace
# 3 logins por segundo, así que este límite no molesta a nadie real y sí frena
# el goteo automatizado.
LOGIN_LIMITER = TokenBucket(
    capacidad=int(os.getenv("LOGIN_RATE_BURST", "10")),
    tasa_por_seg=float(os.getenv("LOGIN_RATE_RPS", "3")),
)

# Bloqueo temporal por usuario tras N fallos (hallazgo 4).
LOGIN_MAX_FALLOS = int(os.getenv("LOGIN_MAX_FALLOS", "5"))
LOGIN_VENTANA_S = float(os.getenv("LOGIN_VENTANA_S", "300"))    # 5 min
LOGIN_BLOQUEO_S = float(os.getenv("LOGIN_BLOQUEO_S", "300"))    # 5 min
_FALLOS_LOGIN: dict[str, list[float]] = {}


def _fallos_recientes(usuario: str) -> list[float]:
    """Fallos de ese usuario dentro de la ventana, descartando los viejos."""
    ahora = time.monotonic()
    recientes = [t for t in _FALLOS_LOGIN.get(usuario, []) if ahora - t < LOGIN_VENTANA_S]
    if recientes:
        _FALLOS_LOGIN[usuario] = recientes
    else:
        _FALLOS_LOGIN.pop(usuario, None)
    return recientes


def _segundos_bloqueo(usuario: str) -> float:
    """Segundos que le quedan bloqueados, o 0 si puede intentarlo."""
    recientes = _fallos_recientes(usuario)
    if len(recientes) < LOGIN_MAX_FALLOS:
        return 0.0
    return max(0.0, LOGIN_BLOQUEO_S - (time.monotonic() - recientes[-1]))


@app.post("/api/v1/auth/login", tags=["Seguridad"])
async def login_por_gateway(request: Request):
    """Login. Único endpoint público del Gateway (sin él nadie podría entrar)."""
    correlation_id = request.state.correlation_id
    breaker = BREAKERS["auth"]

    try:
        credenciales = await request.json()
    except Exception:
        return JSONResponse(
            status_code=422,
            content={"error": "Datos invalidos",
                     "detalle": "Envia un JSON con 'usuario' y 'password'.",
                     "trace_id": correlation_id},
        )
    usuario = str(credenciales.get("usuario", "")).strip().lower()

    # 1. Bloqueo por intentos fallidos de ESE usuario.
    if usuario:
        restante = _segundos_bloqueo(usuario)
        if restante > 0:
            logger.warning(
                f"Login bloqueado para '{usuario}': supero {LOGIN_MAX_FALLOS} intentos fallidos.",
                extra={"campos": {"operation": "login", "event": "auth",
                                  "result": "bloqueado", "usuario": usuario,
                                  "segundosRestantes": round(restante)}},
            )
            return JSONResponse(
                status_code=429,
                content={"error": "Demasiados intentos",
                         "detalle": (f"Se bloqueo el acceso por {LOGIN_MAX_FALLOS} intentos "
                                     f"fallidos. Vuelve a intentarlo en {round(restante / 60) or 1} "
                                     "minuto(s) o pide a un administrador que te ayude."),
                         "trace_id": correlation_id},
                headers={"Retry-After": str(round(restante))},
            )

    # 2. Rate limit propio del login (freno al goteo automatizado).
    if not LOGIN_LIMITER.consumir():
        metricas.RATE_LIMIT_REJECTS.inc()
        espera = max(1, round(LOGIN_LIMITER.segundos_hasta_proximo_token()))
        return JSONResponse(
            status_code=429,
            content={"error": "Demasiadas solicitudes",
                     "detalle": f"Hay demasiados intentos de inicio de sesion. Reintenta en {espera}s.",
                     "trace_id": correlation_id},
            headers={"Retry-After": str(espera)},
        )

    # 3. Circuito abierto: fail-fast con un mensaje que entienda una persona.
    if not breaker.permite():
        _sincronizar_metricas_breaker("auth", breaker)
        metricas.REQUESTS.labels(service="auth", outcome="short_circuit").inc()
        return _auth_no_disponible(correlation_id, breaker)

    try:
        async with _DummyContext(global_client or httpx.AsyncClient()) as client:
            resp = await client.post(
                f"{MICROSERVICIOS['auth']}/api/v1/auth/login",
                json=credenciales,
                headers={"X-Correlation-ID": correlation_id,
                         "Content-Type": "application/json"},
                timeout=TIMEOUTS.get("auth", TIMEOUT_DEFAULT) * TIMEOUT_FACTOR,
            )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        breaker.registrar(False)
        _sincronizar_metricas_breaker("auth", breaker)
        metricas.REQUESTS.labels(service="auth", outcome="unreachable").inc()
        logger.error(
            f"El servicio 'auth' esta inaccesible. {_explicar_circuito(breaker)}",
            extra={"campos": {"operation": "login", "event": "auth", "result": "unreachable",
                              "errorType": type(exc).__name__, "circuito": breaker.estado,
                              "fallosConsecutivos": breaker.fallos_consecutivos,
                              "umbralApertura": breaker.umbral_consecutivos}},
        )
        return _auth_no_disponible(correlation_id, breaker)

    # El 5xx del propio auth-service también cuenta como fallo para el circuito;
    # un 401 NO: la contraseña incorrecta es una respuesta sana del servicio.
    breaker.registrar(resp.status_code < 500)
    _sincronizar_metricas_breaker("auth", breaker)

    if usuario:
        if resp.status_code == 401:
            _FALLOS_LOGIN.setdefault(usuario, []).append(time.monotonic())
            quedan = LOGIN_MAX_FALLOS - len(_fallos_recientes(usuario))
            logger.warning(
                f"Login fallido de '{usuario}' ({quedan} intento(s) antes del bloqueo).",
                extra={"campos": {"operation": "login", "event": "auth",
                                  "result": "rechazado", "usuario": usuario,
                                  "intentosRestantes": max(quedan, 0)}},
            )
        elif resp.status_code < 400:
            _FALLOS_LOGIN.pop(usuario, None)   # entró bien: se limpia el historial

    if resp.status_code >= 500:
        return _auth_no_disponible(correlation_id, breaker)

    return JSONResponse(status_code=resp.status_code, content=resp.json())


def _auth_no_disponible(correlation_id: str, breaker) -> JSONResponse:
    """503 legible cuando no se puede validar la identidad.

    El usuario no tiene por qué saber qué es un microservicio: se le dice qué
    pasa, que no es culpa suya y qué hacer. El detalle técnico va al log.
    """
    return JSONResponse(
        status_code=503,
        content={"error": "Servicio de acceso no disponible",
                 "detalle": ("No podemos verificar tu usuario en este momento porque el "
                             "servicio de autenticacion no esta respondiendo. No es un "
                             "problema con tu contrasena. Vuelve a intentarlo en unos "
                             "segundos; si sigue igual, avisa a Soporte de TI."),
                 "circuito": breaker.estado, "trace_id": correlation_id},
        headers={"Retry-After": "5"},
    )


# 4. Enrutador Dinámico y Circuit Breaker (¡AHORA CON SEGURIDAD JWT!)
@app.api_route(
    "/api/v1/{service}/{path:path}", 
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    dependencies=[Depends(validar_token)] # <-- AQUÍ ESTÁ EL CANDADO REAL
)
async def gateway_router(service: str, path: str, request: Request, payload: dict = Depends(validar_token)):
    """Redirige el tráfico y protege el sistema si un microservicio cae."""

    # Excepción para el servicio de Auth (Nadie tiene token antes de loguearse)
    # `/auth/login` tiene su propia ruta publica (definida arriba, sin token).
    # El RESTO de /auth (gestion de usuarios) si pasa por aqui, o sea con JWT
    # validado y RBAC; el auth-service vuelve a exigir ADMIN por su cuenta.
    # Antes todo /auth se bloqueaba con un 403 y el frontend hablaba directo
    # con el puerto 8003, saltandose el Gateway entero.
    if service == "auth" and path.strip("/") == "login":
        return JSONResponse(
            status_code=404,
            content={"error": "No encontrado",
                     "detalle": "Usa POST /api/v1/auth/login."},
        )

    if service not in MICROSERVICIOS:
        return JSONResponse(status_code=404, content={"error": "Servicio no registrado en el Gateway."})

    # RBAC: bloqueamos operaciones sensibles si el rol del token no es ADMIN.
    if request.method in METODOS_SOLO_ADMIN and payload.get("rol") != "ADMIN":
        return JSONResponse(
            status_code=403,
            content={"error": "Permisos insuficientes: solo un ADMIN puede realizar esta operación."},
        )

    # El QUERY STRING se reenvía con la petición. Sin esto, el Gateway lo
    # descartaba en silencio y ningún parámetro llegaba al servicio: pedir
    # `?limite=10` devolvía el valor por defecto y `?limite=9999` no daba el
    # 422 del tope. Afectaba a TODOS los parámetros de consulta —paginación,
    # filtros, búsquedas—, y era invisible porque la respuesta seguía siendo
    # un 200 con datos plausibles.
    query = request.url.query
    url_destino = f"{MICROSERVICIOS[service]}/api/v1/{path}" + (f"?{query}" if query else "")
    correlation_id = request.state.correlation_id
    
    # Extraer el body y preparar cabeceras para el microservicio interno
    body = await request.body()
    headers = dict(request.headers)
    headers["x-correlation-id"] = correlation_id
    headers.pop("host", None) # Evita conflictos de enrutamiento interno

    # IDENTIDAD INYECTADA POR EL GATEWAY (separación de responsabilidades):
    # el Gateway es el único que valida el JWT; los microservicios confían en
    # estas cabeceras y NO vuelven a decodificar el token.
    headers["x-user-sub"] = payload.get("sub", "")
    headers["x-user-rol"] = payload.get("rol", "")
    headers["x-user-sede"] = payload.get("sede", "")

    # Idempotency-Key en TODA escritura: se respeta la del cliente si la envió
    # (permite reintentos del navegador sin duplicar); si no, se genera una
    # estable por petición. Es la clave que usa el outbox para no duplicar al
    # reintentar una escritura encolada.
    if request.method in METODOS_ESCRITURA and not headers.get("idempotency-key"):
        headers["idempotency-key"] = f"gw-{correlation_id}"

    # Bulkhead + shedding (Fase 2, S34): aísla la capacidad de este servicio y,
    # si ya está bajo presión, descarta primero el tráfico de baja prioridad
    # para reservar cupo a lo crítico (altas: POST/PUT/PATCH/DELETE).
    bulkhead = BULKHEADS[service]
    prioridad = _prioridad(service, request.method)

    if bulkhead.ocupacion() >= UMBRAL_SHED and prioridad == "baja":
        metricas.BULKHEAD_REJECTS.labels(service=service, razon="shed_baja_prioridad").inc()
        logger.warning(
            f"Shed: '{service}' al {bulkhead.ocupacion():.0%} de cupo, se descarta tráfico de baja prioridad.",
            extra={"campos": {"operation": "bulkhead", "event": service, "result": "shed_baja_prioridad"}},
        )
        return JSONResponse(
            status_code=503,
            content={"error": "Service Unavailable",
                     "detalle": f"'{service}' está bajo presión; esta petición de baja prioridad se "
                                "descarta para proteger el tráfico crítico.",
                     "trace_id": correlation_id},
            headers={"Retry-After": "3"},
        )

    if not bulkhead.intentar_entrar():
        metricas.BULKHEAD_REJECTS.labels(service=service, razon="saturado").inc()
        logger.warning(
            f"Bulkhead saturado para '{service}' ({bulkhead.en_vuelo}/{bulkhead.limite} en vuelo).",
            extra={"campos": {"operation": "bulkhead", "event": service, "result": "saturado"}},
        )
        return JSONResponse(
            status_code=503,
            content={"error": "Service Unavailable",
                     "detalle": f"'{service}' alcanzó su límite de llamadas concurrentes.",
                     "trace_id": correlation_id},
            headers={"Retry-After": "2"},
        )

    metricas.BULKHEAD_IN_FLIGHT.labels(service=service).set(bulkhead.en_vuelo)
    try:
        # Cadena de protección S34: circuit breaker + timeout + retry seguro + fallback.
        return await _proxy_resiliente(service, path, url_destino, request.method, body, headers, correlation_id)
    finally:
        bulkhead.salir()
        metricas.BULKHEAD_IN_FLIGHT.labels(service=service).set(bulkhead.en_vuelo)
import asyncio
import os
import random
import time
import uuid
import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from app.core.security import validar_token
from app.core.logger import get_logger
from app.core.exceptions import global_exception_handler
from app.core.resilience import CircuitBreaker
from app.core.bulkhead import Bulkhead
from app.core.ratelimit import TokenBucket
from app.core import metricas
from app.api import health

# 1. Inicializar el Gateway
app = FastAPI(
    title="API Gateway - SHServices",
    description="Enrutador central, inyector de Correlation-ID y Circuit Breaker.",
    version="2.0.0"
)
logger = get_logger("api-gateway")
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
Instrumentator().instrument(app).expose(app)

# 2. Mapa de Microservicios para Docker
MICROSERVICIOS = {
    "tickets": "http://toxiproxy:8666",          # <-- vía Toxiproxy (Chaos Engineering)
    "almacen": "http://almacen-service:80",
    "auth": "http://auth-service:80",
    "diagnosticos": "http://diagnostico-service:80",
    "facturas": "http://facturacion-service:80",
    "auditoria": "http://auditoria-service:80",   # <-- lectura de la traza de eventos
    "notificaciones": "http://notificacion-service:80"  # <-- alertas internas por rol
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

# Un circuit breaker por servicio destino (aísla el estado de salud de cada uno).
BREAKERS = {svc: CircuitBreaker(svc) for svc in MICROSERVICIOS}
_aperturas_vistas = {svc: 0 for svc in MICROSERVICIOS}

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


def _sincronizar_metricas_breaker(service: str, breaker: CircuitBreaker):
    """Refleja el estado y las aperturas del breaker en Prometheus tras cada llamada."""
    metricas.CIRCUIT_STATE.labels(service=service).set(breaker.estado_numerico())
    nuevas = breaker.aperturas - _aperturas_vistas[service]
    if nuevas > 0:
        metricas.CIRCUIT_OPENS.labels(service=service).inc(nuevas)
        _aperturas_vistas[service] = breaker.aperturas

# Retry responsable (S34): reintentar NO es insistir ciegamente. Presupuesto de
# 1 reintento corto, solo para errores transitorios, con backoff + JITTER
# (el jitter evita que muchos clientes reintenten sincronizados).
MAX_INTENTOS = 2

def _backoff_jitter(intento: int) -> float:
    return 0.2 * intento + random.uniform(0, 0.15)


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
BULKHEADS = {svc: Bulkhead(svc, BULKHEAD_LIMITES.get(svc, BULKHEAD_LIMITE_DEFAULT))
             for svc in MICROSERVICIOS}

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


async def _proxy_resiliente(service: str, url_destino: str, metodo: str,
                            body: bytes, headers: dict, correlation_id: str) -> JSONResponse:
    """Cadena de protección S34: circuit breaker -> timeout -> retry seguro -> fallback.

    Devuelve siempre una respuesta HTTP semántica (nunca un 500 opaco ni un
    cuelgue): 503 si el circuito está abierto o la dependencia cae, 504 si hay
    timeout. Actualiza las métricas Prometheus de resiliencia.
    """
    breaker = BREAKERS[service]
    timeout = TIMEOUTS.get(service, TIMEOUT_DEFAULT)
    # Solo GET/HEAD son seguros de reintentar ante timeout/5xx (idempotentes).
    # Un POST con timeout tiene efecto incierto: reintentarlo puede duplicar.
    es_lectura = metodo in ("GET", "HEAD")
    inicio = time.monotonic()

    def _duracion_ms() -> float:
        return round((time.monotonic() - inicio) * 1000, 1)

    # Fail-fast: si el circuito está OPEN, ni siquiera golpeamos a la dependencia.
    if not breaker.permite():
        metricas.REQUESTS.labels(service=service, outcome="circuit_open").inc()
        metricas.FALLBACKS.labels(service=service).inc()
        _sincronizar_metricas_breaker(service, breaker)
        logger.warning(
            f"⛔ Circuito OPEN para '{service}': fail-fast (la dependencia está en recuperación).",
            extra={"campos": {"operation": "proxy_request", "event": service,
                               "result": "circuit_open", "durationMs": _duracion_ms()}},
        )
        return JSONResponse(
            status_code=503,
            content={"error": "Service Unavailable",
                     "detalle": f"El servicio '{service}' está en recuperación (circuito abierto).",
                     "circuito": "OPEN", "trace_id": correlation_id},
            headers={"Retry-After": "5"},
        )

    intento = 0
    async with httpx.AsyncClient() as client:
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
                    await asyncio.sleep(_backoff_jitter(intento))
                    continue

                outcome = "ok" if response.status_code < 400 else ("client_error" if ok else "server_error")
                metricas.REQUESTS.labels(service=service, outcome=outcome).inc()
                duracion_ms = _duracion_ms()
                if _debe_loggear_rutina():
                    logger.info(
                        f"↔️ Proxy {metodo} '{service}' → {response.status_code} ({duracion_ms}ms).",
                        extra={"campos": {"operation": "proxy_request", "event": service,
                                           "result": outcome, "durationMs": duracion_ms}},
                    )
                try:
                    data = response.json()
                except Exception:
                    data = response.text
                return JSONResponse(status_code=response.status_code, content=data)

            except httpx.ConnectError:
                breaker.registrar(False)
                _sincronizar_metricas_breaker(service, breaker)
                # El request nunca llegó: reintentar es seguro para cualquier método.
                if intento < MAX_INTENTOS and breaker.estado == "CLOSED":
                    metricas.RETRIES.labels(service=service).inc()
                    await asyncio.sleep(_backoff_jitter(intento))
                    continue
                metricas.REQUESTS.labels(service=service, outcome="unreachable").inc()
                metricas.FALLBACKS.labels(service=service).inc()
                logger.error(
                    f"🚨 CIRCUIT BREAKER: el servicio '{service}' está inaccesible (estado: {breaker.estado}).",
                    extra={"campos": {"operation": "proxy_request", "event": service,
                                       "result": "unreachable", "durationMs": _duracion_ms()}},
                )
                return JSONResponse(
                    status_code=503,
                    content={"error": "Service Unavailable",
                             "detalle": f"El servicio '{service}' se encuentra temporalmente fuera de línea.",
                             "circuito": breaker.estado, "trace_id": correlation_id},
                )
            except httpx.TimeoutException:
                breaker.registrar(False)
                _sincronizar_metricas_breaker(service, breaker)
                if es_lectura and intento < MAX_INTENTOS and breaker.estado == "CLOSED":
                    metricas.RETRIES.labels(service=service).inc()
                    await asyncio.sleep(_backoff_jitter(intento))
                    continue
                metricas.TIMEOUTS.labels(service=service).inc()
                metricas.REQUESTS.labels(service=service, outcome="timeout").inc()
                metricas.FALLBACKS.labels(service=service).inc()
                logger.error(
                    f"⏱️ TIMEOUT: '{service}' superó su presupuesto de {timeout}s (circuito: {breaker.estado}).",
                    extra={"campos": {"operation": "proxy_request", "event": service,
                                       "result": "timeout", "durationMs": _duracion_ms()}},
                )
                return JSONResponse(
                    status_code=504,
                    content={"error": "Gateway Timeout", "circuito": breaker.estado,
                             "trace_id": correlation_id},
                )

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
            "🚦 Rate limit: ráfaga por encima de la capacidad del Gateway.",
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
        logger.info(f"[{request.method}] Petición entrante ➔ {request.url.path}")

    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response

# 4. Enrutador Dinámico y Circuit Breaker (¡AHORA CON SEGURIDAD JWT!)
@app.api_route(
    "/api/v1/{service}/{path:path}", 
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    dependencies=[Depends(validar_token)] # <-- AQUÍ ESTÁ EL CANDADO REAL
)
async def gateway_router(service: str, path: str, request: Request, payload: dict = Depends(validar_token)):
    """Redirige el tráfico y protege el sistema si un microservicio cae."""

    # Excepción para el servicio de Auth (Nadie tiene token antes de loguearse)
    if service == "auth":
        return JSONResponse(status_code=403, content={"error": "Petición directa al auth-service bloqueada. Use Swagger local por ahora."})

    if service not in MICROSERVICIOS:
        return JSONResponse(status_code=404, content={"error": "Servicio no registrado en el Gateway."})

    # RBAC: bloqueamos operaciones sensibles si el rol del token no es ADMIN.
    if request.method in METODOS_SOLO_ADMIN and payload.get("rol") != "ADMIN":
        return JSONResponse(
            status_code=403,
            content={"error": "Permisos insuficientes: solo un ADMIN puede realizar esta operación."},
        )

    url_destino = f"{MICROSERVICIOS[service]}/api/v1/{path}"
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

    # Bulkhead + shedding (Fase 2, S34): aísla la capacidad de este servicio y,
    # si ya está bajo presión, descarta primero el tráfico de baja prioridad
    # para reservar cupo a lo crítico (altas: POST/PUT/PATCH/DELETE).
    bulkhead = BULKHEADS[service]
    prioridad = _prioridad(service, request.method)

    if bulkhead.ocupacion() >= UMBRAL_SHED and prioridad == "baja":
        metricas.BULKHEAD_REJECTS.labels(service=service, razon="shed_baja_prioridad").inc()
        logger.warning(
            f"🧹 Shed: '{service}' al {bulkhead.ocupacion():.0%} de cupo, se descarta tráfico de baja prioridad.",
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
            f"🧱 Bulkhead saturado para '{service}' ({bulkhead.en_vuelo}/{bulkhead.limite} en vuelo).",
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
        return await _proxy_resiliente(service, url_destino, request.method, body, headers, correlation_id)
    finally:
        bulkhead.salir()
        metricas.BULKHEAD_IN_FLIGHT.labels(service=service).set(bulkhead.en_vuelo)
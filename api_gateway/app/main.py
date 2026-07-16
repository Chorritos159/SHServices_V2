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
for _svc in MICROSERVICIOS:
    metricas.CIRCUIT_STATE.labels(service=_svc).set(0)  # inicializa las series en CLOSED


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

    # Fail-fast: si el circuito está OPEN, ni siquiera golpeamos a la dependencia.
    if not breaker.permite():
        metricas.REQUESTS.labels(service=service, outcome="circuit_open").inc()
        metricas.FALLBACKS.labels(service=service).inc()
        _sincronizar_metricas_breaker(service, breaker)
        logger.warning(
            f"⛔ Circuito OPEN para '{service}': fail-fast (la dependencia está en recuperación).",
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
                    f"🚨 CIRCUIT BREAKER: el servicio '{service}' está inaccesible (estado: {breaker.estado}).",                )
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
                    f"⏱️ TIMEOUT: '{service}' superó su presupuesto de {timeout}s (circuito: {breaker.estado}).",                )
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

    # Cadena de protección S34: circuit breaker + timeout + retry seguro + fallback.
    return await _proxy_resiliente(service, url_destino, request.method, body, headers, correlation_id)
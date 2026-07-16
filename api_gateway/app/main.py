import os
import uuid
import httpx

# Modo multiproceso de prometheus_client (gunicorn con varios workers):
# el directorio debe existir ANTES de crear cualquier métrica.
_MP_DIR = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
if _MP_DIR:
    os.makedirs(_MP_DIR, exist_ok=True)

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter
from app.core.security import validar_token
from app.core.logger import get_logger
from app.core.exceptions import global_exception_handler
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

# Métrica DEDICADA del Circuit Breaker (el status agrupado 5xx no distingue el motivo).
# motivo="conexion" (503, servicio caído) | motivo="timeout" (504, servicio lento > 5s).
CIRCUIT_BREAKER = Counter(
    "gateway_circuit_breaker_total",
    "Cortes del Circuit Breaker del API Gateway por servicio y motivo",
    ["service", "motivo"],
)

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
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.request(
                method=request.method,
                url=url_destino,
                content=body,
                headers=headers,
                timeout=5.0 # Timeout estricto: Si tarda más de 5s, cortamos.
            )
            
            # Devuelve los datos transparentemente al frontend
            try:
                data = response.json()
            except Exception:
                data = response.text
                
            return JSONResponse(status_code=response.status_code, content=data)
            
        except (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError):
            # ¡CIRCUIT BREAKER EN ACCIÓN! El microservicio está apagado o cortó la conexión.
            # httpx.ReadError/RemoteProtocolError ocurren cuando el TCP con Toxiproxy se
            # establece bien pero el upstream (el servicio real) cae a mitad de la respuesta
            # (Toxiproxy resetea la conexión): sin esto, caía al handler genérico (500).
            CIRCUIT_BREAKER.labels(service=service, motivo="conexion").inc()
            logger.error(f"🚨 CIRCUIT BREAKER: El servicio '{service}' está inaccesible.")
            return JSONResponse(
                status_code=503, 
                content={
                    "error": "Service Unavailable", 
                    "detalle": f"El servicio '{service}' se encuentra temporalmente fuera de línea.",
                    "trace_id": correlation_id
                }
            )
        except httpx.TimeoutException:
            CIRCUIT_BREAKER.labels(service=service, motivo="timeout").inc()
            logger.error(f"⏱️ TIMEOUT: El servicio '{service}' tardó demasiado en responder.")
            return JSONResponse(
                status_code=504,
                content={"error": "Gateway Timeout", "trace_id": correlation_id}
            )
import os
import uuid
import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
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

# El health check se deja sin token para que Kubernetes o Docker puedan revisarlo
app.include_router(health.router, prefix="/api/v1")

# 2. Mapa de Microservicios para Docker
MICROSERVICIOS = {
    "tickets": "http://toxiproxy:8666",          # <-- vía Toxiproxy (Chaos Engineering)
    "almacen": "http://almacen-service:80",
    "auth": "http://auth-service:80",
    "diagnosticos": "http://diagnostico-service:80",
    "facturas": "http://facturacion-service:80"
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
            
        except httpx.ConnectError:
            # ¡CIRCUIT BREAKER EN ACCIÓN! El microservicio está apagado.
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
            logger.error(f"⏱️ TIMEOUT: El servicio '{service}' tardó demasiado en responder.")
            return JSONResponse(
                status_code=504, 
                content={"error": "Gateway Timeout", "trace_id": correlation_id}
            )
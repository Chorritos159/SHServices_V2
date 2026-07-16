"""Métricas de resiliencia del Gateway expuestas a Prometheus (S34).

Se registran en el registry por defecto de prometheus_client, el mismo que el
Instrumentator ya publica en /metrics — asi Prometheus las scrapea sin cambios
de configuracion y Grafana puede graficar circuit state, retries y fallbacks.
"""
from prometheus_client import Counter, Gauge

# Estado del circuito por servicio destino (0=CLOSED, 1=HALF_OPEN, 2=OPEN).
CIRCUIT_STATE = Gauge(
    "gateway_circuit_state",
    "Estado del circuit breaker por servicio (0=CLOSED,1=HALF_OPEN,2=OPEN)",
    ["service"],
)

# Aperturas acumuladas del circuito (cuantas veces se abrio).
CIRCUIT_OPENS = Counter(
    "gateway_circuit_opens_total",
    "Numero de veces que el circuit breaker paso a OPEN",
    ["service"],
)

# Resultado de cada request proxied: exito / error de negocio / fallo de dependencia.
REQUESTS = Counter(
    "gateway_proxy_requests_total",
    "Requests proxied por el gateway, por servicio y desenlace",
    ["service", "outcome"],   # outcome: ok | client_error | server_error | timeout | unreachable | circuit_open
)

# Reintentos ejecutados (presion adicional; la S34 pide 'retry rate').
RETRIES = Counter(
    "gateway_retries_total",
    "Reintentos ejecutados por el gateway",
    ["service"],
)

# Respuestas degradadas / fallback honesto entregadas.
FALLBACKS = Counter(
    "gateway_fallbacks_total",
    "Respuestas de fallback/degradadas entregadas por el gateway",
    ["service"],
)

# Timeouts hacia dependencias.
TIMEOUTS = Counter(
    "gateway_timeouts_total",
    "Timeouts del gateway hacia dependencias",
    ["service"],
)

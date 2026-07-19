"""Métricas de resiliencia del Gateway expuestas a Prometheus (S34).

Se registran en el registry por defecto de prometheus_client, el mismo que el
Instrumentator ya publica en /metrics — asi Prometheus las scrapea sin cambios
de configuracion y Grafana puede graficar circuit state, retries y fallbacks.

MODO MULTIPROCESO
El Gateway corre con 8 workers de Gunicorn (ADR-0015) y cada proceso tenia su
PROPIO registro en memoria: /metrics devolvia el del worker que contestara el
scrape, asi que los contadores subestimaban. Medido: 30 peticiones enviadas,
21 reportadas.

Con `PROMETHEUS_MULTIPROC_DIR` (lo fija docker-compose.yml), prometheus_client
escribe las muestras en archivos compartidos y las agrega al hacer el scrape.

Los CONTADORES se suman solos. Los GAUGES necesitan decir COMO agregarse,
porque sumar el estado de un circuito no significaria nada:
  - CIRCUIT_STATE  -> "max": si CUALQUIER worker lo ve OPEN, el circuito esta
                      OPEN. Es lo conservador y lo correcto: basta con que un
                      proceso este haciendo fail-fast para que el circuito lo
                      este.
  - BULKHEAD_IN_FLIGHT -> "livesum": las llamadas en vuelo SI se suman entre
                      los workers vivos; es el total real de trabajo en curso.
"""
from prometheus_client import Counter, Gauge

# Estado del circuito por servicio destino (0=CLOSED, 1=HALF_OPEN, 2=OPEN).
CIRCUIT_STATE = Gauge(
    "gateway_circuit_state",
    "Estado del circuit breaker por servicio (0=CLOSED,1=HALF_OPEN,2=OPEN)",
    ["service"],
    # "mostrecent" y NO "max": el estado del circuito es COMPARTIDO (vive en
    # Redis, ver ADR-0015), asi que todos los workers coinciden y lo correcto es
    # publicar el ultimo valor escrito. Con "max" bastaba que UN worker hubiera
    # anotado 2.0 (OPEN) para que la metrica se quedara clavada en OPEN para
    # siempre: los workers que no atienden a ese servicio nunca reescriben su
    # fichero, asi que el maximo jamas baja. Se detecto en Grafana, que mostraba
    # 'almacen' en OPEN mientras los logs decian "la sonda respondio OK" y el
    # servicio atendia con normalidad.
    multiprocess_mode="mostrecent",
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

# --- Contención de recursos (Fase 2, S34) ---------------------------------

# Llamadas en vuelo por servicio (bulkhead). Gauge: sube/baja en tiempo real.
BULKHEAD_IN_FLIGHT = Gauge(
    "gateway_bulkhead_in_flight",
    "Llamadas en vuelo hacia cada servicio (cupo del bulkhead)",
    ["service"],
    multiprocess_mode="livesum",
)

# Rechazos del bulkhead, separando saturación real de shedding preventivo.
BULKHEAD_REJECTS = Counter(
    "gateway_bulkhead_rejects_total",
    "Peticiones rechazadas por el bulkhead",
    ["service", "razon"],   # razon: saturado | shed_baja_prioridad
)

# Rechazos del rate limiter global del Gateway (token bucket).
RATE_LIMIT_REJECTS = Counter(
    "gateway_rate_limit_rejects_total",
    "Peticiones rechazadas por el rate limiter global (429)",
)

# Logs de rutina omitidos por sampling bajo carga (nunca se muestrean errores).
LOGS_MUESTREADOS = Counter(
    "gateway_logs_sampled_total",
    "Logs de entrada rutinarios omitidos por sampling bajo carga alta",
)

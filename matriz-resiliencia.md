# Matriz de Resiliencia — SHServices V2

> Gate **G8 · FF-DEP-08** · Estrategias de tolerancia a fallos y Chaos Engineering
> Última actualización: 2026-07-16 (Fase 2 del plan de integración S34)

## 1. Resumen de mecanismos

| Mecanismo | Dónde | Qué protege |
|---|---|---|
| **Circuit Breaker formal** (CLOSED/OPEN/HALF_OPEN) | API Gateway (`app/core/resilience.py`) | Aísla un microservicio caído o lento con fail-fast |
| **Timeouts por operación** | API Gateway (3–5 s según servicio) | Corta la espera ante dependencias lentas |
| **Retry + backoff + jitter** | API Gateway (máx. 1 reintento, solo lecturas) | Absorbe fallos transitorios sin duplicar escrituras |
| **Fallback honesto** | API Gateway (503/504 + `circuito` + `Retry-After`) | Respuesta degradada semántica, nunca 500 opaco |
| **Bulkhead por servicio** | API Gateway (`app/core/bulkhead.py`) | Una dependencia lenta no agota la capacidad de las demás |
| **Shedding por prioridad** | API Gateway (umbral 70% de ocupación) | Protege escrituras críticas descartando lecturas de baja prioridad primero |
| **Rate limiting global** | API Gateway (`app/core/ratelimit.py`, token bucket) | El Gateway mismo no colapsa ante una ráfaga, sin importar el destino |
| **Sampling de logs** | API Gateway (middleware de correlación) | Evita que el logging se vuelva cuello de botella bajo carga alta |
| **Métricas de resiliencia** | Gateway → `/metrics` → Prometheus | Circuit state, retries, fallbacks, bulkhead, rate limit, timeouts observables |
| **Toxiproxy** | Tráfico Gateway → Tickets | Simula latencia/caídas (prueba del breaker) |
| **`restart: always`** | Todos los contenedores | Auto-recuperación ante crash |
| **Health checks** | Dockerfile + `/health` | Detección de servicios no saludables |
| **`depends_on` + `condition`** | Compose | Orden de arranque controlado |
| **`connect_robust` + retry loop** | Consumidor de Auditoría | Sobrevive a RabbitMQ no disponible |
| **`pool_pre_ping` / `pool_recycle`** | Capa SQLAlchemy | Reconexión transparente a PostgreSQL |
| **Gunicorn (1 worker)** | API Gateway | Estado del circuit breaker y métricas consistentes (single-process) |

## 2. Circuit Breaker formal (API Gateway)

Un breaker **por servicio destino** con estados reales (no solo traducción de excepciones):

- **CLOSED → OPEN**: ≥ 3 fallos consecutivos, o error rate ≥ 50 % en ventana de 30 s (mín. 4 muestras).
- **OPEN**: fail-fast durante 15 s — el Gateway responde 503 con `Retry-After: 5` **sin llamar** a la dependencia enferma (le da aire para recuperarse).
- **OPEN → HALF_OPEN**: al vencer el cooldown deja pasar **una sonda**; si sale bien → CLOSED, si falla → OPEN de nuevo.

Cadena de protección por request: `circuit breaker → timeout por operación → retry (backoff+jitter, solo GET/HEAD) → fallback`.

| Fallo del microservicio | Detección | Respuesta del Gateway |
|---|---|---|
| Circuito abierto (fail-fast) | `breaker.permite() == False` | **503** + `circuito: OPEN` + `Retry-After: 5` + `trace_id` |
| Servicio apagado / inaccesible | `httpx.ConnectError` (reintento seguro: el request nunca salió) | **503** Service Unavailable + `circuito` + `trace_id` |
| Servicio lento (supera su timeout) | `httpx.TimeoutException` (reintento solo lecturas) | **504** Gateway Timeout + `circuito` + `trace_id` |
| Respuesta 5xx | `status >= 500` cuenta como fallo del breaker | Se propaga (con 1 reintento si es lectura) |

**Regla de retry responsable (S34):** un POST con timeout tiene efecto incierto — reintentarlo
puede duplicar el ticket/la factura. Por eso solo se reintentan lecturas (GET/HEAD) ante
timeout/5xx; un `ConnectError` sí se reintenta con cualquier método (el request nunca llegó).
Backoff: `0.2·intento + jitter U(0, 0.15)` para desincronizar clientes.

**Métricas expuestas en `/metrics`** (las scrapea el Prometheus ya configurado):
`gateway_circuit_state` (0=CLOSED, 1=HALF_OPEN, 2=OPEN), `gateway_circuit_opens_total`,
`gateway_proxy_requests_total{outcome}`, `gateway_retries_total`, `gateway_fallbacks_total`,
`gateway_timeouts_total`.

**Nota de diseño — por qué el Gateway corre con 1 worker:** el breaker y las
métricas viven en memoria del proceso Python. Se probó primero con Gunicorn a
4 workers (config original) y se detectó en vivo que el estado del circuito
"parpadeaba" entre CLOSED/OPEN según a qué worker caía cada request/scrape,
porque cada proceso mantiene su propio breaker y su propio registro
Prometheus. Sin un backend de estado compartido (p. ej. Redis) entre
procesos, un breaker por-worker no es un circuit breaker real: distintas
fracciones del tráfico verían estados distintos de la misma dependencia. Se
bajó a 1 worker para garantizar una fuente de verdad única y consistente;
el Gateway es I/O-bound (reenvía llamadas async), así que el costo en
throughput es limitado. Si la Fase 5 (carga 100k/500k/1M) revela que 1
worker es insuficiente, la solución correcta es mover el estado del breaker
a Redis (no volver a múltiples workers en memoria).

## 3. Contención de recursos (Fase 2)

A diferencia del circuit breaker (que reacciona a fallos), la contención
actúa **antes** de que algo falle: limita cuánto tráfico entra al sistema
y hacia cada dependencia, para que una ráfaga no lo tumbe.

### 3.1 Bulkhead por servicio

Cada microservicio destino tiene un cupo de llamadas **en vuelo** (no una
cola oculta: al llegar al límite se rechaza de inmediato con 503, sin
esperar). Aísla la capacidad: si `tickets` se pone lento, no consume la
capacidad reservada para `almacen` o `facturas`.

| Servicio | Cupo (en vuelo) |
|---|---|
| tickets | 12 |
| auth, almacen, diagnosticos, facturas | 8 |
| auditoria, notificaciones | 5 |

### 3.2 Shedding por prioridad

Al 70% de ocupación del bulkhead, el Gateway empieza a **descartar
primero** el tráfico de baja prioridad, reservando el cupo restante para
lo crítico:

| Prioridad | Criterio | Ejemplo |
|---|---|---|
| Alta | Escrituras (`POST`/`PUT`/`PATCH`/`DELETE`) | Crear ticket, cerrar factura |
| Media | Lecturas generales | Listar tickets, ver inventario |
| Baja | Servicio de auditoría (reporting/traza) | `GET /auditoria/*` |

**Verificado en vivo** (40 llamadas concurrentes reales vía `httpx.AsyncClient`
a `auditoria`, cupo=5): 4 pasaron, 36 fueron descartadas por
`shed_baja_prioridad` (ninguna llegó a `saturado`, porque el shedding actúa
antes de la saturación dura). El bulkhead volvió a 0 en vuelo al terminar y
`tickets` no se vio afectado — el aislamiento por servicio funciona.

### 3.3 Rate limiting global (token bucket)

Protege al **Gateway mismo** (no a una dependencia particular) de una
ráfaga que supere su propia capacidad de atender tráfico: capacidad 40,
repuesto a 20 tokens/s. Sin tokens disponibles, responde **429** con
`Retry-After`. No se aplica a `/health` ni `/metrics` (monitoreo siempre
disponible).

**Verificado en vivo**: 100 peticiones con 40 en paralelo → 88×200, 12×429,
consistente con el tamaño del bucket.

### 3.4 Sampling de logs bajo carga

Por encima de 30 requests/s, el log de entrada rutinario (`[MÉTODO]
Petición entrante`) se muestrea 1 de cada 10 en el excedente — evita que el
logging compita por I/O con el tráfico real bajo carga alta. Los
`warning`/`error` del Gateway (circuito abierto, timeout, fallback,
bulkhead saturado) **nunca** se muestrean: la señal de fallo siempre se ve
completa.

## 4. Chaos Engineering con Toxiproxy

- El Gateway apunta a Tickets mediante `http://toxiproxy:8666` (no directo).
- Toxiproxy reenvía a `ticket-service:80` y permite **inyectar toxinas** (latencia, corte de
  conexión, ancho de banda) a través de su API de control en `:8474`.
- Sirve para **demostrar el Circuit Breaker en vivo**: al inyectar un corte, el Gateway responde
  503; al inyectar latencia > 3 s (timeout de tickets), responde 504. Tras 3 fallos seguidos el
  circuito pasa a **OPEN** (visible en `gateway_circuit_state`) y el Gateway hace fail-fast
  durante 15 s; al quitar la toxina, la sonda de HALF_OPEN lo cierra solo.

**Ejemplo (inyectar latencia de 8 s):**
```bash
curl -X POST http://localhost:8474/proxies/ticket_proxy/toxics \
  -d '{"type":"latency","attributes":{"latency":8000}}'
# → leer tickets devuelve 504; tras 3 seguidos, 503 con "circuito": "OPEN" (fail-fast)

# quitar la toxina y esperar el cooldown (15 s) → la sonda HALF_OPEN recupera el circuito
curl -X DELETE http://localhost:8474/proxies/ticket_proxy/toxics/latency_downstream
```

## 5. Matriz de dependencias y arranque

| Servicio | Depende de | Condición | Nota de resiliencia |
|---|---|---|---|
| api-gateway | auth-service, toxiproxy | `service_started` | Arranca aunque un servicio esté caído (para probar el breaker) |
| ticket-service | postgres-db, rabbitmq | `service_healthy` | No arranca sin sus dependencias sanas |
| almacen-service | postgres-db | `service_healthy` | — |
| diagnostico-service | postgres-db, rabbitmq | `service_healthy` | — |
| facturacion-service | postgres-db, rabbitmq | `service_healthy` | — |
| auditoria-service | rabbitmq, **postgres-db** | `service_healthy` | Persiste la traza (Fase 4) |

## 6. Resiliencia del consumidor de eventos

El `auditoria-service` consume de RabbitMQ dentro de un **bucle de reintento**:

- El healthcheck de RabbitMQ (`rabbitmq-diagnostics ping`) puede reportar "healthy" **antes** de
  aceptar conexiones AMQP. Si el primer `connect_robust` fallaba, la tarea moría sin reintentar.
- **Corrección:** `while True: try … except: sleep(5)` — reintenta el arranque y reconecta si la
  conexión cae. Los mensajes durables quedan en la cola hasta que el consumidor vuelve.

## 7. Resiliencia de datos

- **`pool_pre_ping=True`**: valida cada conexión con un `SELECT 1` antes de usarla (descarta
  conexiones muertas si PostgreSQL se reinició).
- **`pool_recycle=280`**: recicla conexiones viejas antes de que el servidor las cierre.
- **Mensajería durable**: exchange y colas `durable=True`; los eventos no se pierden si un
  consumidor está temporalmente caído.

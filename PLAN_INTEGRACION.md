# Plan de Integración Final — SHServices V2 (S34)

> Rama de trabajo: `main`.
> Objetivo: cerrar las brechas que la **Sesión 34 (Prevalidación técnica)** exige
> como criterios críticos, sobre todo **resiliencia de aplicación** y su
> **observabilidad** (el dashboard debe mostrar circuit state, retry/fallback,
> queue depth, consumer lag). El flujo funcional ya opera; aquí se lo hace
> **resistente, observable bajo presión y demostrable ante fallas**.

## Regla de oro (todas las fases)

Cada cambio de código sube una **nueva versión en el changelog del servicio**
afectado (`documentacion/<servicio>.md`, cuadro `Versión | Cambio | Tipo | Acción
para consumidores`), clasificando Compatible/Breaking. Cada mecanismo de
resiliencia se **verifica en vivo** (con Toxiproxy o apagando contenedores) y se
deja evidencia.

## Diagnóstico de partida (qué hay y qué falta)

| Mecanismo S34 | Estado actual | Acción |
| :-- | :-- | :-- |
| Timeout | ✅ 5s fijo en el gateway | Ajustar a por-operación |
| Retry + backoff + jitter | ❌ | Fase 1 |
| Circuit breaker con **estados** (CLOSED/OPEN/HALF_OPEN) | ❌ (solo captura excepciones) | Fase 1 |
| Fallback honesto | ⚠️ parcial (503/504) | Fase 1 |
| Bulkhead | ❌ | Fase 2 |
| Backpressure (rate limit 429) | ❌ | Fase 2 |
| Buffering + dropping/sampling | ❌ | Fase 2 |
| Idempotencia | ❌ | Fase 3 |
| Logs estructurados S34 (operation/durationMs/event/result) | ⚠️ básico | Fase 3 |
| **Dashboard: circuit state, retry/fallback, queue depth, consumer lag** | ❌ | Fase 4 |
| Carga 100k/500k/1M + fallas controladas | ❌ | Fase 5 |
| Ya presente: Toxiproxy, Loki+Promtail, Prometheus, Grafana, RBAC, Gunicorn | ✅ | reutilizar |

## Fases

### FASE 1 — Resiliencia núcleo en el gateway ⭐ (esta fase)
Circuit breaker **formal** (CLOSED → OPEN → HALF_OPEN con umbral, cooldown y
sonda), timeouts por operación, **retry con backoff + jitter** (solo lecturas
seguras), **fallback honesto**, y **métricas Prometheus custom** para que
Grafana pueda graficarlas: `gateway_circuit_state`, `gateway_retries_total`,
`gateway_fallbacks_total`, `gateway_timeouts_total`, `gateway_requests_total`.
Se reutiliza `/metrics` del Instrumentator (mismo scrape de Prometheus).
**Verificación:** con Toxiproxy inyectar corte/latencia a `ticket_proxy` →
observar el circuito abrir (fail-fast), el retry y el fallback, y las métricas
subir. Changelog: api_gateway.

### FASE 2 — Contención de recursos
Bulkhead por dependencia (límite de llamadas en vuelo → 503 controlado),
rate limiting global (token bucket → 429 con Retry-After), shed de baja
prioridad, y sampling de logs bajo carga. Métricas: `gateway_bulkhead_in_flight`,
`gateway_bulkhead_rejects_total`, `gateway_rate_limit_rejects_total`.
**Verificación:** ráfaga concurrente → 429/503 controlados sin caída.

### FASE 3 — Idempotencia + logs S34 + estados degradados
Idempotencia en las escrituras (`POST /tickets`, `POST /facturas`) por
`Idempotency-Key`/clave natural (webhook duplicado no duplica estado). Logs
al formato mínimo S34 (`service, correlationId, operation, event, result,
durationMs`). Estado degradado honesto ante dependencia caída.
**Verificación:** reintento del mismo evento → un solo registro; log operable.

### FASE 4 — Dashboard de resiliencia en Grafana
Provisionar un dashboard versionado con: throughput, latencia p50/p95/p99,
error rate, **circuit breaker state**, retry/fallback count, bulkhead,
**queue depth** y **consumer lag** de RabbitMQ (agregar `rabbitmq_exporter` o
scrape del plugin Prometheus de RabbitMQ). Cierra la observabilidad que exige
la pág. 16/18 de la S34.

### FASE 5 — Carga y fallas controladas
Scripts de carga progresiva (100k / 500k / 1M) que miden throughput, p95/p99,
error rate, y **fichas de falla controlada** con Toxiproxy (servicio caído,
latencia, 503, webhook duplicado, cola saturada). Llenar el "Registro de carga"
y la "Matriz de revisión de resiliencia" de la S34.

### FASE 6 — Gobierno y paquete de defensa
Actualizar `matriz-resiliencia.md`, `matriz-auditoria.md`, catálogo, runbook,
ADRs y README operativo; consolidar changelogs; tabla de **brechas finales**
(riesgo, acción, responsable) para el dictamen.

```
Fase 1 (resiliencia núcleo) → Fase 2 (contención) → Fase 3 (idempotencia+logs)
   → Fase 4 (dashboard) → Fase 5 (carga+fallas) → Fase 6 (gobierno)
```
Cada fase se entrega, se verifica y se documenta antes de la siguiente.

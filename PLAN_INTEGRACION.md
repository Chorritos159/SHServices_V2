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
| Retry + backoff + jitter | ✅ Fase 1 | — |
| Circuit breaker con **estados** (CLOSED/OPEN/HALF_OPEN) | ✅ Fase 1 | — |
| Fallback honesto | ✅ Fase 1 | — |
| Bulkhead | ✅ Fase 2 | — |
| Backpressure (rate limit 429) | ✅ Fase 2 | — |
| Buffering + dropping/sampling | ✅ Fase 2 (sampling de logs; shedding de tráfico) | — |
| Idempotencia | ✅ Fase 3 | — |
| Logs estructurados S34 (operation/durationMs/event/result) | ✅ Fase 3 | — |
| **Dashboard: circuit state, retry/fallback, queue depth, consumer lag** | ✅ Fase 4 | — |
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

### FASE 3 — Idempotencia + logs S34 + estados degradados ✅ COMPLETA
Idempotencia en las escrituras: `POST /tickets` con `Idempotency-Key` opt-in
(no hay clave natural — el mismo cliente puede traer el mismo equipo en
visitas distintas y legítimas); `POST /facturas` por clave natural
`id_ticket` (un ticket tiene, a lo sumo, una factura). Idempotencia de
consumidores RabbitMQ (auditoria-service, notificacion-service) por índice
único `(trace_id, evento[, rol_destino])` — un redelivery no duplica la
traza ni la alerta. Logs de los 9 servicios migrados al formato mínimo S34
(`service, correlationId, operation, event, result, durationMs`), con un
`LoggerAdapter` que ahora SÍ fusiona campos por-llamada (antes los
descartaba silenciosamente). Estado degradado honesto: ya cubierto por el
fallback de Fase 1 (503/504 + `circuito` + `trace_id`).
**Verificado en vivo:** POST duplicado de ticket con la misma
`Idempotency-Key` → mismo `idTicket`, 1 sola fila en BD. POST duplicado de
factura para el mismo ticket → misma `idFactura`, 1 sola fila. Insert
directo duplicado en `auditoria_eventos` (simulando redelivery) → rechazado
por el índice único `ux_auditoria_trace_evento`. Changelog por servicio.

### FASE 4 — Dashboard de resiliencia en Grafana ✅ COMPLETA
Dashboard versionado (`grafana/dashboards/resiliencia_s34.json`, provisionado
por archivo — no se arma a mano en la UI) con 16 paneles en 6 filas:
throughput, latencia p50/p95/p99 y error rate del Gateway; **estado del
circuit breaker por servicio** (state-timeline CLOSED/HALF_OPEN/OPEN) y
aperturas acumuladas; retry/fallback/timeout por servicio; bulkhead en vuelo
y rechazos por razón (saturado vs. shed_baja_prioridad); rate limit global;
**queue depth** (`rabbitmq_queue_messages_ready`) y **consumer lag**
(`rabbitmq_queue_messages_unacked`) por cola vía el plugin
`rabbitmq_prometheus` (endpoint `/metrics/per-object`, el único que trae el
desglose por cola); desenlaces del proxy y logs muestreados. Se activó
además `prometheus-fastapi-instrumentator` en auditoria-service y
notificacion-service (ya tenían el paquete instalado pero sin conectar).
**Verificado:** los 6 targets de Prometheus en estado `up`; las queries de
cada panel devueltas por el datasource proxy de Grafana (mismo camino que
usa el frontend) confirmadas con datos reales — circuito de `tickets` en
OPEN tras la prueba de Toxiproxy, 26 rechazos `shed_baja_prioridad` de la
ráfaga a auditoría, 16 rechazos de rate limit, colas `auditoria_tickets_queue`
y `notificaciones_queue` con su profundidad real.

### FASE 5 — Carga y fallas controladas 🔶 EN PROGRESO
Suite `pruebas/` (scripts + runner Python en `pruebas/lib/`), 5 pruebas:
traza única, 780 concurrentes con límites normales, carga sostenida 500k/1M
(rate limit ampliado temporalmente para medir el throughput real), y 5
fichas de falla controlada (servicio caído, latencia, cola saturada,
rate limit, evento duplicado). `Registro de carga` y `Matriz de revisión de
resiliencia` de la S34 llenados con el formato exacto del material (págs.
24 y 28) en `documentacion/registro_de_carga.md` y
`documentacion/matriz_revision_resiliencia.md`; fichas en
`documentacion/fichas_falla_controlada.md` (formato pág. 30).
**Completado y verificado en vivo:** pruebas 1, 2 y 5 (todas las fichas).
**En curso:** prueba 3 (500k), lanzada en background — corre ~1.5-2h a la
tasa real medida (~85 rps, limitada por el Gateway de 1 solo worker, el
cuello de botella identificado). Prueba 4 (1M) queda para correr después,
por el mismo motivo de duración. Rate limit del Gateway hecho configurable
por entorno (`RATE_LIMIT_RPS`/`RATE_LIMIT_BURST`) para soportar estas
corridas — antes era un valor fijo en código.

### FASE 6 — Gobierno y paquete de defensa
Actualizar `matriz-resiliencia.md`, `matriz-auditoria.md`, catálogo, runbook,
ADRs y README operativo; consolidar changelogs; tabla de **brechas finales**
(riesgo, acción, responsable) para el dictamen.

```
Fase 1 (resiliencia núcleo) → Fase 2 (contención) → Fase 3 (idempotencia+logs)
   → Fase 4 (dashboard) → Fase 5 (carga+fallas) → Fase 6 (gobierno)
```
Cada fase se entrega, se verifica y se documenta antes de la siguiente.

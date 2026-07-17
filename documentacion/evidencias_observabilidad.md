# Evidencias obligatorias de observabilidad — S34

> Checklist de la S34 (pág. 16 "Evidencias obligatorias", pág. 17 "Log
> mínimo aceptable", pág. 18 "Dashboard mínimo durante pruebas") contra lo
> que este sistema tiene **verificado en vivo**, no planeado.

## 1. Evidencias obligatorias (pág. 16)

| Evidencia | Mínimo esperado | Estado | Dónde se ve |
| :-- | :-- | :-- | :-- |
| Logs estructurados | JSON o formato consistente | ✅ | JSON, un evento por línea, en los 9 servicios (`app/core/logger.py`). Dozzle (`:9999`) en vivo o Grafana→Loki |
| CorrelationId | presente en todo el flujo | ✅ | `correlationId` en cada línea; el Gateway lo genera/propaga y viaja hasta RabbitMQ (`message.correlation_id`) y la BD de auditoría. Prueba: `python pruebas/01_traza_unica.py` |
| Métricas | requests, errores, latencia | ✅ | `/metrics` de Gateway, ticket, auditoría y notificaciones → Prometheus (`:9090`) |
| Trazas | relación entre servicios | ✅ | El `correlationId` es la traza: una operación se reconstruye completa uniendo los logs de los 4 servicios que tocó + la tabla `auditoria_eventos`. Ver §4 |
| Dashboard | salud, latencia y errores | ✅ | Grafana (`:3000`) → *SHServices — Resiliencia (S34)*, 20 paneles en 7 filas |
| Eventos auditables | registro del flujo crítico | ✅ | Tabla `auditoria_eventos` en PostgreSQL: `TicketCreado.v1`, `TicketListo.v1`, `DiagnosticoRegistrado.v1`, `FacturaGenerada.v1` (ver `matriz-auditoria.md`) |
| Queue depth | si usan colas | ✅ | `rabbitmq_queue_messages_ready` por cola (fila "RabbitMQ" del dashboard) |
| Consumer lag | si usan consumidores/eventos | ✅ | `rabbitmq_queue_messages_unacked` por cola + consumidores activos |
| Circuit state | si usan circuit breaker | ✅ | `gateway_circuit_state` (0/1/2) — panel *state-timeline* con CLOSED/HALF_OPEN/OPEN por servicio |
| Retry / fallback count | si reintentan o degradan | ✅ | `gateway_retries_total`, `gateway_fallbacks_total`, `gateway_timeouts_total` por servicio |

## 2. Log mínimo aceptable (pág. 17)

La slide pide que el registro permita **reconstruir la operación**. Log
real de este sistema (copiado tal cual de `docker logs ticket-service`):

```json
{
  "timestamp": "2026-07-17T05:50:40.005387Z",
  "level": "INFO",
  "service": "ticket-service",
  "correlationId": "prueba1-traza-1784267439",
  "message": "💾 Ticket TICK-LIM-4FCA guardado (sede LIMA, por admin).",
  "operation": "crear_ticket",
  "event": "TicketCreado.v1",
  "result": "ok",
  "durationMs": 11.8,
  "idTicket": "TICK-LIM-4FCA"
}
```

| La slide pide responder | Campo que lo responde |
| :-- | :-- |
| qué servicio actuó | `service` |
| qué operación ejecutó | `operation` |
| qué entidad cambió | `idTicket` (equivale al `orderId` del ejemplo) |
| cuánto tardó | `durationMs` |
| qué resultado dejó | `result` (`ok` / `duplicado` / `timeout` / `circuit_open` / `saturado`…) |
| con qué correlationId | `correlationId` |

> **Nota de lectura en Windows:** si ves los emojis como `â†"` o `ð..¾`, es
> tu consola decodificando con cp1252 — el log está bien. Léelo con
> `docker logs <servicio> | python -c "import sys;sys.stdin.reconfigure(encoding='utf-8');print(sys.stdin.read())"`,
> o simplemente míralo en **Dozzle** (`:9999`), que lo muestra correcto.

## 3. Dashboard mínimo durante pruebas (pág. 18)

| La slide pide | Fila del dashboard | Métrica |
| :-- | :-- | :-- |
| **Throughput** (req/s) | Throughput, latencia y error rate | `rate(http_requests_total)` |
| **Latencia** (p50/p95/p99) | idem | `histogram_quantile` sobre `http_request_duration_seconds_bucket` |
| **Errores** (rate y códigos) | idem | % de 5xx + desglose por código (`by (status)`) |
| **Saturación** (CPU/memoria/conexiones) | Saturación | `process_cpu_seconds_total`, `process_resident_memory_bytes`, `rabbitmq_connections`, `process_open_fds` |
| **Colas** (queue depth / consumer lag) | RabbitMQ | `rabbitmq_queue_messages_ready` / `..._unacked` |
| **Resiliencia** (retry, timeout, circuit state) | Circuit Breaker + Retry/fallback/timeouts | `gateway_circuit_state`, `gateway_retries_total`, `gateway_timeouts_total` |
| Muestreo de logs | Desenlaces y sampling | `gateway_logs_sampled_total` |

**Verificado:** los 20 paneles devuelven datos (0 "No data"), incluyendo un
error rate real del **37 %** medido durante una inyección de fallas
controlada con Toxiproxy.

### Dos bugs de observabilidad que se encontraron y corrigieron

1. **Counters sin serie:** los paneles de retry/fallback/timeout/aperturas/
   bulkhead mostraban `No data`. Un `Counter` de `prometheus_client` no
   existe como serie hasta su primer `.inc()` — se leía como "la métrica
   está rota" cuando en realidad significaba "no ha pasado nada malo".
   Ahora todas las series se inicializan en 0 al arranque del Gateway.
2. **Error rate imposible de matchear:** la query filtraba
   `status=~"5.."`, pero el instrumentator agrupa el status en **clases**
   (`2xx`/`4xx`/`5xx`), no en códigos exactos — el panel nunca podía
   mostrar nada. Corregido a `status="5xx"` + `or vector(0)` (para que
   muestre 0 y no "No data" cuando no hay errores).

## 4. Trazas: relación entre servicios

No se usa un tracer distribuido (Jaeger/Tempo); la relación entre servicios
se reconstruye con el **correlationId**, que es lo que pide la S34
("relación entre servicios"):

```
Cliente → Gateway (genera X-Correlation-ID)
        → ticket-service (lo lee de la cabecera y lo loguea)
        → RabbitMQ (viaja como message.correlation_id)
        → auditoria-service + notificacion-service (lo persisten como trace_id)
```

`python pruebas/01_traza_unica.py` lo demuestra de punta a punta: crea un
ticket con un correlationId conocido y confirma que aparece en auditoría,
en notificaciones y en los logs de los 4 contenedores del flujo.

**Brecha honesta:** no hay spans con jerarquía padre/hijo ni tiempos por
tramo como daría OpenTelemetry. Para el alcance de la S34 (relación entre
servicios + reconstrucción de la operación) el correlationId es
suficiente; migrar a OpenTelemetry queda registrado en
`documentacion/brechas_finales.md`.

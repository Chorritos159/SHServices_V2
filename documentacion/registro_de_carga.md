# Registro de carga — SHServices V2 (S34, Fase 5)

> Formato exacto de la S34 (pág. 24). Generado con `pruebas/03_carga_500k.sh`
> / `pruebas/04_carga_1M.sh` (mismo runner, `pruebas/lib/carga.py`), rate
> limit del Gateway ampliado temporalmente (`RATE_LIMIT_RPS=100000
> RATE_LIMIT_BURST=100000`) para medir el throughput **real** del backend y
> no el techo del propio limitador — se restaura al terminar cada corrida.
> Ruta bajo prueba: `GET /api/v1/tickets/tickets/` (lectura, la más
> transitada). 18 trabajadores concurrentes, alineados al bulkhead de
> tickets (cupo=12).

| Fase | Throughput | p95 | p99 | Error rate | CPU/Mem (api-gateway) | Queue depth | Resultado |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 100k | *(en progreso — ver nota)* | | | | | | |
| 500k | *(en progreso — corriendo en background al momento de este commit)* | | | | | | |
| 1M | *(pendiente — se ejecuta tras 500k con el mismo runner)* | | | | | | |

## Nota de estado (2026-07-16, al momento de este commit)

La corrida de **500k** se lanzó en background
(`bash pruebas/03_carga_500k.sh > pruebas/resultados/03_consola.log 2>&1 &`)
y sigue en curso. Con la muestra disponible hasta ahora (~10,300 peticiones
en 135 s):

- **Throughput sostenido:** ~80-90 rps servidos (estable, sin degradar con el tiempo).
- **CPU del Gateway durante la carga:** **~100%** de un núcleo (`docker stats`) — el
  Gateway corre con **1 solo worker Gunicorn** (fix de Fase 1: el circuit
  breaker necesita una única fuente de verdad en memoria; ver
  `matriz-resiliencia.md` §2). Con la carga ampliada, este único worker
  satura su núcleo antes que cualquier otra dependencia.
- **`ticket-service` durante la carga:** ~50% CPU — no es el cuello de botella.

**Primer cuello de botella identificado (regla de la S34, pág. 24):** el
**Gateway de 1 solo worker es el límite de throughput**, no la base de datos
ni `ticket-service`. Es una limitación **conocida y documentada**
(Fase 1): la alternativa (más workers) requeriría mover el estado del
circuit breaker a un backend compartido (Redis) para no romper la
consistencia del breaker entre procesos — evaluado y postergado
explícitamente por priorizar la corrección del mecanismo de resiliencia
sobre el throughput bruto en esta entrega.

Esta tabla se completa con los valores finales de `throughput_rps`,
`latencia_ms.p95/p99` y `tasa_exito` de cada reporte JSON en
`pruebas/resultados/03_carga500k_*.json` / `04_carga1M_*.json` en cuanto
terminan las corridas (quedan fuera de este commit por su duración: ~1.5-2h
la de 500k, ~3-4h la de 1M, a la tasa medida arriba).

## Referencia: corridas cortas ya verificadas (no reemplazan la tabla, la respaldan)

| Corrida | Total | Hilos | Límites | Resultado |
| :-- | :-- | :-- | :-- | :-- |
| Humo (límites normales) | 780 | 100 | normales (20/40) | 58×200, 693×429, 29×503 — p95=207ms, p99=259ms. Backpressure conteniendo, Gateway sano después |
| Humo (límites ampliados) | 3,000 | 18 | ampliados (100k/100k) | 2,722×200 (90.7%), 278×503 (bulkhead) — p50=208ms, p95=285ms, p99=376ms. Confirma que sin el rate limit, el bulkhead (cupo=12) es el siguiente límite real |

## Queue depth y consumer lag

Visibles en vivo en el dashboard de Grafana (Fase 4,
`grafana/dashboards/resiliencia_s34.json`, fila "RabbitMQ") vía
`rabbitmq_queue_messages_ready` / `rabbitmq_queue_messages_unacked` por
cola. Durante las corridas de carga sobre `GET /tickets` (una lectura
síncrona, no pasa por RabbitMQ) la cola no crece — la publicación de
eventos (`ticket.creado`, etc.) solo ocurre en las escrituras (`POST
/tickets`), que no son el foco de esta corrida de throughput.

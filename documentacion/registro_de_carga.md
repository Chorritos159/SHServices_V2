# Registro de carga — SHServices V2 (S34, Fase 5)

> Formato exacto de la S34 (pág. 24). Generado con `pruebas/03_carga_100k.sh`
> / `04_carga_500k.sh` / `05_carga_1M.sh` (runner `pruebas/lib/carga_nodos.py`).
> Rate limit del Gateway ampliado temporalmente
> (`RATE_LIMIT_RPS=100000 RATE_LIMIT_BURST=100000`) para medir el
> throughput **real** del backend y no el techo del propio limitador — se
> restaura al terminar cada corrida. Ruta bajo prueba: `GET
> /api/v1/tickets/tickets/` (lectura, la más transitada).

## Metodología (por qué no son conteos literales)

A la tasa real medida del sistema (~85-90 rps, ver nota de cuello de
botella abajo), completar 500,000 peticiones tomaría 1.5-2 horas y
1,000,000 tomaría 3-4 horas. En vez de eso, cada nivel corre en una
**ventana de tiempo fija de 10-15 minutos**, con varios **nodos**
concurrentes independientes mandando **bloques** sucesivos de peticiones
(no un solo hilo, no todo de golpe) y backoff escalonado 3s→5s→8s+jitter
cuando un bloque topa con 429/503. La etiqueta 100k/500k/1M es el **nivel
de carga ofrecida** (más nodos, bloques más grandes por nivel), no un
conteo a cumplir — se reporta el throughput real sostenido en la ventana.

| Nivel | Nodos | Bloque | Ventana |
| :-- | :-- | :-- | :-- |
| 100k | 6 | 40 | 10 min |
| 500k | 10 | 80 | 15 min |
| 1M | 15 | 120 | 15 min |

## Tabla de registro

| Fase | Throughput | p95 | p99 | Error rate | CPU/Mem (api-gateway) | Queue depth | Resultado |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 100k | *(pendiente de corrida)* | | | | | | |
| 500k | *(pendiente de corrida)* | | | | | | |
| 1M | *(pendiente de corrida)* | | | | | | |

> Esta tabla se completa con los valores de `throughput_rps`,
> `latencia_ms.p95/p99`, `tasa_exito` y `codigos` de cada reporte JSON en
> `pruebas/resultados/03_carga100k_*.json` / `04_carga500k_*.json` /
> `05_carga1M_*.json`, más `docker stats api-gateway` durante la corrida y
> `rabbitmq_queue_messages_ready` de Grafana en ese momento. Las tres
> corridas (30-40 min en total) se ejecutan y se revisan juntos.

## Cuello de botella identificado (corridas previas, diseño anterior)

Antes de este rediseño se corrió una prueba sostenida de conteo literal
(no por ventana de tiempo) durante ~17 min, alcanzando **79,275**
peticiones a un throughput estable de **~85 rps**, con:

- **CPU del Gateway durante la carga:** **~100%** de un núcleo
  (`docker stats`) — el Gateway corre con **1 solo worker Gunicorn** (fix
  de Fase 1: el circuit breaker necesita una única fuente de verdad en
  memoria; ver `matriz-resiliencia.md` §2).
- **`ticket-service` durante la carga:** ~50% CPU — no es el cuello de botella.

**Primer cuello de botella (regla de la S34, pág. 24):** el **Gateway de 1
solo worker** es el límite de throughput, no la base de datos ni
`ticket-service`. Es una limitación **conocida y documentada** (Fase 1): la
alternativa (más workers) requeriría mover el estado del circuit breaker a
un backend compartido (Redis) para no romper su consistencia entre
procesos — evaluado y postergado explícitamente por priorizar la
corrección del mecanismo de resiliencia sobre el throughput bruto en esta
entrega. Este número (~85 rps, 1 núcleo saturado) es la referencia contra
la que se leen los resultados de las corridas por nodos/bloques.

## Referencia: corridas cortas ya verificadas (no reemplazan la tabla, la respaldan)

| Corrida | Total | Configuración | Resultado |
| :-- | :-- | :-- | :-- |
| Humo (límites normales) | 780 | 100 hilos concurrentes | 58×200, 693×429, 29×503 — p95=207ms, p99=259ms. Backpressure conteniendo, Gateway sano después |
| Humo (límites ampliados) | 3,000 | 18 hilos concurrentes | 2,722×200 (90.7%), 278×503 (bulkhead) — p50=208ms, p95=285ms, p99=376ms. Confirma que sin el rate limit, el bulkhead (cupo=12) es el siguiente límite real |

## Queue depth y consumer lag

Visibles en vivo en el dashboard de Grafana (Fase 4,
`grafana/dashboards/resiliencia_s34.json`, fila "RabbitMQ") vía
`rabbitmq_queue_messages_ready` / `rabbitmq_queue_messages_unacked` por
cola. Durante las corridas de carga sobre `GET /tickets` (una lectura
síncrona, no pasa por RabbitMQ) la cola no crece — la publicación de
eventos (`ticket.creado`, etc.) solo ocurre en las escrituras (`POST
/tickets`), que no son el foco de esta corrida de throughput.

# Matriz de revisión de resiliencia — SHServices V2 (S34, Fase 5)

> Formato exacto de la S34 (pág. 28): cada mecanismo debe observarse o
> justificarse. La columna "Evidencia" apunta a la verificación en vivo
> concreta (Fases 1-3 y `pruebas/05_caos.sh`), no a intención de diseño.

| Mecanismo | Pregunta de revisión | Respuesta | Evidencia |
| :-- | :-- | :-- | :-- |
| **Timeout** | ¿Corta la espera o queda colgado? | Corta. Presupuesto por operación (3-5 s según servicio, no un timeout global fijo) | Ficha B: timeout real en 3084-6422 ms, nunca esperó los 8000 ms de la toxina |
| **Retry** | ¿Reintenta solo errores transitorios? | Sí. Solo GET/HEAD ante timeout/5xx (un POST con timeout no se reintenta: efecto incierto, riesgo de duplicar). `ConnectError` se reintenta para cualquier método (el request nunca llegó) | `api_gateway/app/main.py::_proxy_resiliente`, verificado en Fase 1 |
| **Backoff** | ¿Evita saturar más la dependencia? | Sí, con jitter: `0.2*intento + random.uniform(0,0.15)` — evita que reintentos sincronizados golpeen la dependencia enferma todos a la vez | `_backoff_jitter()`, Fase 1 |
| **Idempotencia** | ¿Evita duplicados? | Sí, por dos vías: `Idempotency-Key` (tickets, sin clave natural posible) y clave natural `id_ticket` (facturas, además de índice único en los consumidores RabbitMQ) | Ficha E + Fase 3 (verificado con inserts duplicados directos en BD, rechazados por el índice único) |
| **Circuit breaker** | ¿Deja de llamar a dependencia enferma? | Sí, formal (CLOSED/OPEN/HALF_OPEN), fail-fast medido en **58 ms** con el circuito abierto (sin tocar la red) | Fichas A y B; `gateway_circuit_state` en Grafana |
| **Bulkhead** | ¿Una falla no consume todos los recursos? | Sí, cupo por servicio (12 para tickets, 5-8 para el resto). Verificado que una ráfaga contra `auditoria` **no afectó** a `tickets` en paralelo | Ficha C; Fase 2, `gateway_bulkhead_in_flight` por servicio |
| **Backpressure** | ¿Regula entrada cuando no puede procesar? | Sí, rate limit global (token bucket) devuelve 429 + `Retry-After` antes de gastar tiempo en JWT/RBAC/proxy | Ficha D; Fase 2 |
| **Buffering** | ¿Acumula trabajo de forma controlada? | Sí — RabbitMQ con colas y exchange `durable=True`: los eventos no se pierden si un consumidor está temporalmente caído, se acumulan en la cola hasta que vuelve | `matriz-resiliencia.md` §7; verificado con `docker stop`/`start` de consumidores en fases previas |
| **Dropping / sampling** | ¿Descarta lo no crítico bajo presión? | Sí, dos formas: shedding de tráfico de baja prioridad al 70% de ocupación del bulkhead (Ficha C), y sampling de logs de rutina por encima de 30 req/s (los `warning`/`error` NUNCA se muestrean) | Fase 2; `gateway_logs_sampled_total` |
| **Fallback** | ¿Entrega respuesta degradada útil? | Sí — siempre JSON con `error`, `detalle`, `circuito`/`razon` y `trace_id`; nunca un 500 opaco ni una respuesta ambigua | Fichas A-D; Fase 1 (`_proxy_resiliente`) |

## Límites del desacoplamiento y estados degradados

- **Single point of coordination**: el Gateway es el único punto de entrada; su caída (no simulada en esta fase — sería un SPOF de infraestructura, no de lógica de negocio) tumbaría todo el sistema. Mitigado parcialmente por `restart: always`, no por redundancia (fuera de alcance para un solo host de demo).
- **Estado del circuit breaker es por-proceso**: con Gunicorn a 1 worker (fix de Fase 1) hay una única fuente de verdad; si el sistema alguna vez necesitara escalar el Gateway a más de un worker/réplica, el estado del breaker tendría que moverse a un backend compartido (Redis) — documentado como brecha conocida en `matriz-resiliencia.md`.
- **Estados degradados/compensados**: un ticket SOPORTE con `almacen-service` caído durante el diagnóstico queda con el repuesto marcado según lo que `_mover_stock` pudo confirmar (try/except por repuesto, sin bloquear el flujo completo) — comportamiento honesto, no una compensación formal tipo saga.

# Fichas de falla controlada — SHServices V2 (S34, Fase 5)

> Formato exacto de la S34 (pág. 30): cada falla se diseña con hipótesis y
> evidencia esperada, y se ejecuta con el sistema **operando** (no en frío).
> Las 6 fichas corresponden a `pruebas/06_caos.py`, corrida el 2026-07-16
> (versión Bash original; migrado a Python puro después, mismo comportamiento).
> Reporte completo: `pruebas/resultados/05_caos_20260716_225158.txt`.

## Ficha A — Servicio caído

| Elemento | Respuesta |
| :-- | :-- |
| Falla inducida | `docker stop almacen-service` con el sistema operando |
| Servicio afectado | `almacen-service` (vía API Gateway) |
| Hipótesis esperada | El circuito abre tras fallos consecutivos y el Gateway deja de intentar contactar al servicio (fail-fast), sin colgarse ni propagar el fallo a otros servicios |
| Métrica observada | `gateway_circuit_state{service="almacen"}`: 0 (CLOSED) → 2 (OPEN) tras 3 fallos consecutivos. 4 llamadas de sondeo devolvieron 503 |
| Estado esperado del negocio | 503 honesto con `circuito` y `trace_id` en el cuerpo — nunca un 500 opaco ni un timeout colgado |
| Tiempo de recuperación esperado | Cooldown de 15 s + arranque del contenedor; sonda HALF_OPEN cierra el circuito sola |
| Evidencia de auditoría | Fail-fast medido en **58 ms** con el circuito abierto (sin tocar la red). Sonda tras `docker start` → HTTP 200, `circuit_state` vuelto a 0 (CLOSED), **sin intervención manual** |

## Ficha B — Latencia artificial

| Elemento | Respuesta |
| :-- | :-- |
| Falla inducida | Toxiproxy: toxina `latency` de 8000 ms en `ticket_proxy` (timeout configurado del Gateway para `tickets`: 3 s) |
| Servicio afectado | `ticket-service` (único servicio detrás de Toxiproxy) |
| Hipótesis esperada | El Gateway corta la espera al presupuesto configurado (504), reintenta una vez en operaciones de lectura, y tras fallos repetidos abre el circuito |
| Métrica observada | Intento 1: HTTP 504 en 6422 ms (timeout + 1 reintento con backoff). Intento 2: HTTP 504 en 3084 ms. Intento 3: HTTP 503 en 63 ms (circuito ya OPEN). `gateway_circuit_state{service="tickets"}`: 0 → 2 |
| Estado esperado del negocio | 504 con `trace_id` en los primeros intentos; 503 con `circuito` una vez abierto — nunca una espera indefinida |
| Tiempo de recuperación esperado | Cooldown de 15 s tras quitar la toxina; sonda HALF_OPEN cierra el circuito |
| Evidencia de auditoría | Sonda tras `DELETE .../toxics/latencia_caos` → HTTP 200, `circuit_state` vuelto a 0 (CLOSED) |

## Ficha C — Cola saturada (bulkhead + shedding)

| Elemento | Respuesta |
| :-- | :-- |
| Falla inducida | Ráfaga de 40 peticiones **realmente concurrentes** (asyncio, no procesos separados) contra `auditoria` (bulkhead: cupo=5, prioridad de lectura = "baja") |
| Servicio afectado | `auditoria-service` (vía Gateway) — el resto de servicios no se ven afectados (bulkhead aislado por servicio) |
| Hipótesis esperada | Al superar el 70% de ocupación del bulkhead, el tráfico de baja prioridad se descarta preventivamente (503) antes de llegar a la saturación dura, protegiendo cupo para escrituras críticas |
| Métrica observada | 4×200, 36×503 — **los 36 rechazos fueron `shed_baja_prioridad`** (ninguno llegó a `saturado`: el shedding actuó antes de la saturación real). `gateway_bulkhead_in_flight{service="auditoria"}` volvió a 0 al terminar (sin fugas de cupo) |
| Estado esperado del negocio | 503 con detalle explícito ("está bajo presión... se descarta para proteger el tráfico crítico") y `Retry-After` |
| Tiempo de recuperación esperado | Inmediato: en cuanto baja la ocupación, el siguiente request pasa sin esperar cooldown (no es un circuit breaker, es contención en tiempo real) |
| Evidencia de auditoría | `gateway_bulkhead_rejects_total{razon="shed_baja_prioridad",service="auditoria"}` = 36 tras la ráfaga |

## Ficha D — Rate limit 429 (backpressure)

| Elemento | Respuesta |
| :-- | :-- |
| Falla inducida | Ráfaga de 100 peticiones realmente concurrentes contra `tickets`, con los límites normales del Gateway (token bucket: 40 de ráfaga, 20/s en régimen) |
| Servicio afectado | Ninguno "afectado" — la protección es del **Gateway mismo**, no de una dependencia |
| Hipótesis esperada | El Gateway rechaza con 429 + `Retry-After` en cuanto se agotan los tokens, antes de gastar tiempo en JWT/RBAC/proxy, protegiendo su propia capacidad de proceso |
| Métrica observada | 17×200, 61×429, 22×503 (el resto cayó en el bulkhead de tickets, cupo=12, también saturado por la misma ráfaga) |
| Estado esperado del negocio | 429 con `Retry-After` calculado a partir de la tasa de repuesto del bucket |
| Tiempo de recuperación esperado | Continuo: el bucket se rellena a 20 tokens/s: no hay "cooldown" fijo |
| Evidencia de auditoría | `gateway_rate_limit_rejects_total` = 61 tras la ráfaga (contador acumulado, Prometheus) |

## Ficha E — Webhook/evento duplicado (idempotencia)

| Elemento | Respuesta |
| :-- | :-- |
| Falla inducida | Mismo `POST /tickets` reenviado dos veces con la **misma `Idempotency-Key`** (simula un reintento del cliente o un redelivery) |
| Servicio afectado | `ticket-service` |
| Hipótesis esperada | El segundo envío devuelve la respuesta original sin crear un segundo ticket |
| Métrica observada | Ambas respuestas devolvieron el mismo `idTicket` (`TICK-LIM-7DF5`) |
| Estado esperado del negocio | 1 sola fila en la tabla `tickets` (verificado también en la Fase 3 con consulta directa a PostgreSQL) |
| Tiempo de recuperación esperado | N/A — no hay degradación que recuperar, es prevención |
| Evidencia de auditoría | Log estructurado `operation=crear_ticket result=duplicado` en `ticket-service` para el segundo envío |

## Fallas de la S34 no cubiertas en esta fase

| Falla (pág. 27 S34) | Por qué no aplica / queda pendiente |
| :-- | :-- |
| Consumidor lento | No hay un mecanismo para regular la velocidad de un consumidor RabbitMQ en este sistema (los consumidores procesan a la velocidad que llegan los mensajes) |
| Base o almacenamiento lento | Requeriría un proxy/mock delante de PostgreSQL (no está en el alcance de esta fase) |
| Error de contrato | Cubierto parcialmente por la validación Pydantic de cada servicio (422 ante payload inválido), pero no se diseñó como ficha de caos explícita |
| Fallo parcial (ejecutar una parte y fallar la siguiente) | El flujo diagnóstico→almacén (`_mover_stock`) ya maneja este caso en el código (try/except por repuesto), pero no se verificó como ficha de caos dedicada en esta fase |

---

## Ficha F — Degradación funcional: la VENTA sobrevive sin ticket-service

**Añadida el 2026-07-18**, junto con la venta de mostrador.

| Campo | Valor |
| :-- | :-- |
| **Falla inyectada** | `docker pause ticket-service` (caída dura: acepta la conexión TCP y no responde nunca) |
| **Operación bajo prueba** | Venta directa de mostrador: 2 unidades de un producto de la sede |
| **Comportamiento esperado** | La venta se completa igual. El ticket es *best-effort* |
| **Mecanismo** | Degradación funcional + outbox del Gateway |

### Por qué esta ficha existe

Las fichas A-E prueban que una falla **no se propaga**. Esta prueba algo
distinto y más exigente: que una falla **no detiene el negocio** cuando la
operación no depende de verdad del servicio caído.

Una venta de mostrador necesita dos cosas: que salga el stock y que el cliente
se lleve su comprobante. El ticket es un registro de conveniencia. Tratarlo
como obligatorio significaría que una caída de `ticket-service` cierra la caja
—y eso no es resiliencia, es acoplamiento disfrazado.

### Resultado medido (2026-07-18)

```
Producto elegido: PRD-003 (23 en stock, S/.80.0)
ticket-service PAUSADO

1. Alta del ticket   -> HTTP 202 (encolado en el outbox); la venta NO se detiene aquí
2. Descuento de stock -> HTTP 200
3. Cobro              -> HTTP 201, comprobante FAC-PIU-6F6B por S/.160.00

OK: VENTA COMPLETADA con ticket-service caído (referencia VENTA-PIU-CAOS...,
    sin ticket). El cliente se llevó su producto y su comprobante.
```

El **202 del paso 1** es la parte interesante y no estaba planeada: el Gateway
no solo dejó pasar la venta, además **encoló el alta del ticket en su outbox**,
así que cuando `ticket-service` vuelve el registro se crea solo. La venta no se
degradó a "se perdió el ticket", sino a "el ticket llega más tarde".

### Qué se restaura al terminar

La prueba hace `docker unpause` en un `finally`, así que el servicio vuelve
aunque la ficha falle a mitad.

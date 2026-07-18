# ADR-0011 — Outbox transaccional en el Gateway: ninguna escritura se pierde ni se duplica

**Estado:** Aceptada · **Fecha:** 2026-07-18 · **Fase:** S34, Fase 8

## Contexto

Si un microservicio estaba caído, la escritura del usuario se perdía: el Gateway devolvía
503/504 y el operador tenía que volver a enviarla a mano. En una recepción real eso significa
un ticket no registrado o un cobro que hay que rehacer. Además, reintentar a ciegas una
escritura puede **duplicarla** (dos tickets, dos cobros).

Los mecanismos que ya teníamos no cubrían este caso:

- El **retry** del Gateway solo aplica a lecturas (un POST con timeout tiene efecto incierto).
- El **circuit breaker** hace fail-fast: protege al sistema, pero la petición del usuario se pierde igual.
- RabbitMQ resuelve la comunicación **entre servicios**, no la del **cliente hacia** el sistema.

## Decisión

Implementar un **outbox transaccional (store-and-forward)** en el API Gateway, que es el punto
único por donde pasan todas las escrituras:

1. Toda escritura (`POST`/`PUT`/`PATCH`) lleva una **`Idempotency-Key`** (la del cliente o una
   generada por el Gateway). Es la garantía de "no duplicar".
2. Si la escritura falla por **indisponibilidad** (circuito abierto, servicio inaccesible o
   timeout) —y **no** por un error de negocio 4xx— el Gateway la persiste en la tabla durable
   `gateway_outbox` (PostgreSQL) junto con la identidad ya validada (`X-User-*`) y responde
   **`202 {"encolado": true, "mensaje": …}`** en vez de un error.
3. Un **worker de fondo** drena el outbox: reintenta cada pendiente contra el servicio interno
   con la **misma `Idempotency-Key`**. `2xx` → ENTREGADO; `4xx` de negocio → DESCARTADO (no se
   reintenta en vano); caída/5xx → backoff exponencial y sigue pendiente.
4. Se guarda la identidad ya validada en vez del JWT: el token puede expirar antes de que el
   worker consiga entregar, y los servicios internos confían en las cabeceras `X-User-*`.

Las **lecturas no se encolan** (basta reintentarlas en vivo) y los **errores de negocio tampoco**
(un 422 no mejora por reintentar).

## Consecuencias

**A favor**
- El usuario no pierde su trabajo: registra el ticket, ve "quedó en cola y se enviará solo",
  y cuando el servicio vuelve la operación se completa sin que nadie reintente nada.
- No se duplica: la `Idempotency-Key` viaja en el primer intento y en todos los reintentos.
- Cubre **todas** las escrituras (ticket, diagnóstico, inventario, cobro) con un solo mecanismo,
  porque vive en el proxy y no en cada servicio.
- Un timeout de escritura —el caso ambiguo clásico— pasa a ser seguro: si llegó a procesarse,
  el reintento se deduplica; si no llegó, el reintento lo completa.

**En contra / límites**
- El contrato de respuesta cambia: el frontend debe entender el `202 encolado` (implementado).
- El Gateway pasa a tener estado en BD (antes era sin estado). Es un acoplamiento aceptado a
  cambio de no perder escrituras.
- Si el Gateway completo cae con pendientes en la tabla, se reanudan al arrancar (están en
  PostgreSQL, no en memoria), pero mientras esté caído no se drena nada.

## Verificación

```bash
docker pause ticket-service
# POST /api/v1/tickets/tickets/  -> 202 {"encolado": true}
docker unpause ticket-service
# el worker lo entrega solo (HTTP 201) y queda UNA sola fila en la tabla tickets
```
Repetir el envío con la misma `Idempotency-Key` devuelve el ticket original, sin duplicar.

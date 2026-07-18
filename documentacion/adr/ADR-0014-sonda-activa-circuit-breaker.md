# ADR-0014 — Sonda activa del circuit breaker (recuperación sin tráfico)

**Estado:** Aceptada · **Fecha:** 2026-07-18 · **Fase:** S34, Fase 8

## Contexto

El circuit breaker era **"lazy"**, como la mayoría de implementaciones: solo transicionaba
`OPEN → HALF_OPEN → CLOSED` cuando llegaba una petición del cliente después del cooldown. Efecto
práctico: si un servicio se recuperaba pero **nadie le mandaba tráfico**, su circuito se quedaba
`OPEN` indefinidamente, y en el dashboard parecía que seguía roto. La primera petición del
usuario tras la recuperación pagaba el coste de ser la sonda.

## Decisión

Añadir una **sonda activa** en el Gateway: una tarea de fondo que cada 5 s recorre los breakers
que **no** están `CLOSED` y, si ya venció el cooldown, manda un probe al `/health` del servicio
**por la misma ruta que el tráfico real**. Si responde, el circuito se cierra solo.

- Solo se prueban circuitos degradados (a los sanos no se les molesta).
- La sonda reutiliza `permite()` / `registrar()` del breaker: reclama la sonda de HALF_OPEN, así
  que **no compite** con una petición real (solo una sonda a la vez).
- **Abrir** el circuito sigue requiriendo tráfico real: un fallo solo se observa si alguien llama
  al servicio caído. Lo que se automatiza es la **recuperación**, no la detección.

## Consecuencias

**A favor**
- Tras restaurar un servicio, el circuito vuelve a `CLOSED` en ~15-20 s (cooldown + intervalo)
  sin intervención ni tráfico — verificado.
- El dashboard refleja el estado real del sistema, no el último tráfico observado.
- El primer usuario después de una caída ya no paga el coste de la sonda.

**En contra / límites**
- Tráfico extra mínimo: un `GET /health` cada 5 s **solo** por servicio degradado.
- La sonda usa `/health`, que valida la BD pero no la ruta de negocio concreta: un servicio
  podría responder health y seguir fallando en un endpoint específico. Aceptado — en ese caso
  el circuito se reabre con el primer fallo real.

## Nota operativa importante

Durante las pruebas de carga se evaluó **desactivar** el breaker (`CIRCUIT_BREAKER_DISABLED`) y
subir los timeouts para "atender todas" las peticiones. **Se descartó**: sin el breaker, las
peticiones se acumulaban y **colgaban** los servicios de un solo proceso. El breaker los
**protege**. La forma correcta de atender el 100% bajo carga es ampliar el rate limit y el
bulkhead y mantener una **concurrencia moderada** (ver `documentacion/registro_de_carga.md`).

## Verificación

`python pruebas/10_demo_breaker.py <servicio>`: pausa el contenedor, le manda tráfico hasta abrir
el circuito (fail-fast visible), lo deja `OPEN` 15 s para verlo en Grafana y, al reanudar el
servicio, **el circuito se cierra solo sin enviar más tráfico**.

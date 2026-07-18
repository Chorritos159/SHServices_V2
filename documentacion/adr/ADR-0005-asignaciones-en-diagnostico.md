# ADR-0005 — La asignación de tickets vive en diagnostico-service, no en ticket-service

**Estado:** Aceptada · **Fecha:** 2026-07-18 · **Fase:** S34, Fase 8

## Contexto

El negocio necesita que un técnico **tome** un ticket y quede asignado **solo a él**: otro
técnico de la misma sede no debe poder tomarlo, y cada técnico necesita una bandeja
**"Mis Tickets"**. El administrador, además, debe ver **quién atiende qué**.

La opción natural era ponerlo en `ticket-service` (es "un campo del ticket"). Pero eso ata el
trabajo diario del técnico a la disponibilidad de ese servicio: si `ticket-service` cae, el
técnico **pierde de vista sus propios tickets** y no puede seguir trabajando — justamente el
escenario que la S34 pide sobrevivir.

## Decisión

`diagnostico-service` es el **dueño autoritativo** de las asignaciones:

- Tabla `asignaciones` con **`id_ticket` como clave primaria** → un ticket pertenece a un solo
  técnico (la exclusividad la garantiza la BD, no una validación en código).
- `POST /asignaciones/tomar` — exclusivo (409 si ya lo tomó otro), **idempotente** (si lo retoma
  el mismo técnico devuelve la asignación existente, no duplica).
- `GET /asignaciones/mias` — bandeja del técnico. **No consulta al ticket-service**: los datos
  del ticket se cachean al tomarlo.
- `GET /asignaciones/` — vista de administrador (403 para el resto).
- Avisar a `ticket-service` del cambio de estado (`EN_COLA → EN_DIAGNOSTICO`) es **best-effort
  y en segundo plano**: no bloquea la respuesta ni falla la operación.

## Consecuencias

**A favor**
- El técnico sigue viendo y trabajando sus tickets con `ticket-service` caído (verificado).
- La exclusividad es una restricción de base de datos: no depende de una carrera en código.
- "Tomar" responde en ~130 ms incluso con `ticket-service` caído, porque el sync no bloquea.
- Cohesión: el servicio que ejecuta el trabajo técnico es el que sabe quién lo está haciendo.

**En contra / límites**
- El estado del ticket queda **duplicado** entre dos servicios (el ticket dice
  `EN_DIAGNOSTICO`, la asignación dice `TOMADO`). Es duplicación deliberada a cambio de
  disponibilidad; la fuente de verdad de *quién atiende* es `asignaciones`.
- Si el sync best-effort se pierde, el ticket puede quedar `EN_COLA` aunque esté asignado. No
  rompe nada: la exclusividad la sigue garantizando `asignaciones` (el segundo técnico recibe
  409 igual), y el frontend filtra la cola con las asignaciones.
- Los datos del ticket cacheados en la asignación pueden quedar desactualizados si el ticket se
  edita. Aceptado: son datos de visualización, no de decisión.

## Verificación

`python pruebas/09_asignaciones.py` — 11 verificaciones: tomar, exclusividad (409), idempotencia,
"Mis Tickets" por técnico, vista admin (403 para técnico) y **"Mis Tickets" con `ticket-service`
pausado devolviendo 200**.

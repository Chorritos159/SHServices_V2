# ADR-0002 — Estrategia de idempotencia: clave natural vs. Idempotency-Key

**Estado:** Aceptada · **Fecha:** 2026-07-16 · **Fase:** S34, Fase 3

## Contexto

La S34 exige que las escrituras críticas sean idempotentes: un reintento
del cliente, un retry del Gateway, o un redelivery de RabbitMQ no deben
duplicar el efecto de negocio. El sistema tiene varias escrituras con
características distintas:

- `POST /tickets` — crea un ticket nuevo. Cada envío es, en principio, una
  operación de negocio legítima y distinta (el mismo cliente puede traer
  el mismo equipo en visitas separadas y reales).
- `POST /facturas` — emite un comprobante para un ticket. La regla de
  negocio existente es que un ticket tiene, **a lo sumo, una factura**.
- Los consumidores RabbitMQ (`auditoria-service`, `notificacion-service`)
  — procesan eventos que RabbitMQ entrega "al menos una vez" (redelivery
  posible si se pierde el ack después de persistir).

Aplicar una única estrategia de idempotencia a los tres casos no encaja:
no existe una clave natural confiable para "esto es un reintento y no una
segunda visita legítima" en la creación de tickets.

## Decisión

Usar la estrategia que corresponde a cada caso, no una única receta:

| Escritura | Estrategia | Por qué |
|---|---|---|
| `POST /tickets` | **`Idempotency-Key`** (cabecera opcional, opt-in, tabla `idempotencia` en `ticket_service`) | No hay clave natural del dominio que distinga "reintento" de "visita nueva legítima" — hace falta un token opaco por intento de envío, decisión del cliente |
| `POST /facturas` | **Clave natural** (`id_ticket`, ya `UNIQUE` en BD) | Es una regla de negocio durable (un ticket = una factura), no solo protección ante reintentos transitorios |
| Consumidores RabbitMQ | **Índice único** `(trace_id, evento[, rol_destino])` | El mismo mensaje redelivered trae el mismo `trace_id` + `evento` — es la clave natural del evento de negocio, generada una vez por el Gateway y propagada sin cambios |

En los tres casos, el conflicto (`IntegrityError` de la base de datos) se
captura y se resuelve devolviendo el registro ya existente — nunca se
propaga como error crudo ni se reintenta indefinidamente.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Clave natural para tickets (p. ej. `numero_serie` + `sede`) | Bloquearía para siempre un segundo ticket legítimo para el mismo equipo (una segunda falla real, meses después) |
| `Idempotency-Key` obligatoria en todas las escrituras | Rompe compatibilidad con clientes existentes sin cambios; para facturas y consumidores la clave natural ya es una garantía más fuerte (regla de negocio, no solo intención del cliente) |

## Consecuencias

- **Positivas:** cada mecanismo protege exactamente lo que debe proteger,
  sin bloquear casos de uso legítimos ni dejar huecos.
- **Negativas:** tres implementaciones distintas de manejar duplicados
  (aunque el patrón — capturar `IntegrityError`, devolver lo existente —
  es el mismo en los tres) en vez de una sola abstracción reutilizable.
- **Verificado en vivo:** ver `documentacion/fichas_falla_controlada.md`
  (Ficha E) y `documentacion/registro_de_carga.md`/Fase 3 del
  `PLAN_INTEGRACION.md`.

# ADR-0005 — Eventos para las tareas secundarias

**Estado:** Aceptada · **Fecha:** 2026-07-18 · **Fase:** Diseño (S34)

## Contexto

Auditoría, notificaciones internas y webhooks a terceros son obligaciones
reales del sistema, pero ninguna condiciona la operación que las dispara: un
ticket está bien creado tanto si la alerta al técnico salió en ese instante
como si sale dos segundos después.

Si esas tareas fueran llamadas síncronas, una caída del servicio de
notificaciones impediría registrar tickets — un servicio secundario tumbando
el negocio principal.

## Decisión

Publicar **eventos de dominio en RabbitMQ** para todo lo secundario, sobre un
exchange **topic** llamado `tickets.eventos`.

Catálogo actual (6 eventos):

| Routing key | Evento | Lo publica | Lo consume |
| :-- | :-- | :-- | :-- |
| `ticket.creado` | `TicketCreado.v1` | ticket-service | auditoría, notificaciones |
| `ticket.tomado` | `TicketTomado.v1` | diagnostico-service | auditoría, notificaciones |
| `ticket.diagnosticado` | `DiagnosticoRegistrado.v1` | diagnostico-service | auditoría, notificaciones |
| `ticket.listo` | `TicketListo.v1` | ticket-service | auditoría, notificaciones |
| `ticket.facturado` | `FacturaGenerada.v1` | facturacion-service | auditoría, notificaciones |
| `producto.registrado` | `ProductoRegistrado.v1` | almacen-service | auditoría, notificaciones |

Se eligió **topic** y no *direct* para poder suscribirse por patrón: los
consumidores hacen bind a `ticket.*` y `producto.*`, así que un evento nuevo
llega solo, sin tocar el consumidor.

## Alternativas consideradas

| Alternativa | Por qué no |
| :-- | :-- |
| Llamadas HTTP a auditoría y notificaciones | Acopla la operación principal a la disponibilidad de las secundarias, justo lo que se quiere evitar |
| Exchange *fanout* | Todo el mundo recibe todo y filtra en código; el enrutamiento deja de ser declarativo |
| Tabla de eventos con *polling* | Menos infraestructura, pero añade latencia y carga constante a la base de datos |

## Consecuencias

- **Positivas:** auditoría y notificaciones pueden caerse sin afectar al
  negocio; los mensajes quedan en la cola y se procesan al volver. Añadir un
  consumidor nuevo no toca a los productores.
- **Negativas:** consistencia eventual — la auditoría de una operación puede
  tardar un instante en aparecer. Aceptable: nadie decide nada mirando la
  auditoría en tiempo real.

## Riesgo identificado y mitigación

**Riesgo:** eventos duplicados, perdidos o sin trazabilidad.

**Mitigación aplicada, punto por punto:**

**Duplicados.** RabbitMQ garantiza *at-least-once*: un redelivery entrega el
mismo mensaje otra vez. Los consumidores son **idempotentes**:

- Notificaciones tiene índice único `(trace_id, evento, rol_destino)`; el INSERT
  repetido choca, se captura el `IntegrityError` y se descarta con un log de
  nivel `warning`. No se duplica la alerta.
- Auditoría aplica el mismo criterio sobre el evento y su `trace_id`.

**Perdidos.** Exchange y colas **durables**, y los mensajes se confirman
(`message.process()`) solo después de procesarlos: si el consumidor muere a
mitad, el mensaje vuelve a la cola en vez de darse por entregado.

**Trazabilidad.** Cada evento viaja con `trace_id` (el `correlationId` que nació
en el Gateway) y con su nombre versionado (`TicketCreado.v1`). El mismo
identificador está en los logs estructurados de los 8 servicios, así que una
operación se sigue de punta a punta: se toma el `trace_id` de la respuesta y se
filtra por él en Loki. La versión en el nombre permite publicar un `.v2` sin
romper a quien consume el `.v1`.

**Nota sobre el orden de publicación.** El evento se publica *después* de
confirmar la escritura en base de datos, con `BackgroundTasks`. Si el proceso
muriera entre el commit y la publicación, el evento se perdería: es la brecha
clásica que resuelve un outbox transaccional **por servicio**. Hoy el outbox
existe en el Gateway para las escrituras HTTP (ADR-0011), no para los eventos.
Está registrado como brecha conocida y no se oculta.

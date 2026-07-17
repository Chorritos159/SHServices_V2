# Servicio: ticket_service

## Contratos (API Síncrona)
El contrato es la frontera pública del servicio.

| Contrato / Endpoint | Propósito | Notas de gobierno |
| :--- | :--- | :--- |
| `POST /api/v1/tickets/` | Crear un nuevo ticket de soporte o venta | API v1, requiere datos de equipo si es SOPORTE |

## Menú de Eventos (Asíncronos)
Eventos que el servicio produce o consume.

| Evento | Tipo | Versión | Semántica / Propósito |
| :--- | :--- | :--- | :--- |
| `TicketCreado.v1` | Productor | `v1` | Notifica que se registró un nuevo ticket en el sistema central |
| `DiagnosticoRegistrado.v1` | Consumidor | `v1` | Escucha para avanzar el estado del ticket a "EN_REPARACION" o "ESPERANDO_REPUESTOS" |
| `FacturaGenerada.v1` | Consumidor | `v1` | Escucha la confirmación de pago para cerrar el ticket definitivamente (Estado "CERRADO") |

## Runbook Básico
Qué hacer cuando este servicio falla. Es operativo, breve y accionable.

| Sección | Pregunta | Acción/Detalle Específico |
| :--- | :--- | :--- |
| **Incidente cubierto** | ¿Qué problema atiende? | No se pueden crear tickets nuevos o el servicio no reacciona a eventos externos (se desincroniza el estado). |
| **Detección** | ¿Cómo sé que ocurre? | Quejas en mostrador (no pueden ingresar clientes) o dead-letters (DLQ) llenos en RabbitMQ. |
| **Primeras revisiones** | ¿Qué miro primero? | Conectividad con Postgres (para creación) y salud de la conexión a RabbitMQ (para asincronía). |
| **Acción** | ¿Qué puedo ejecutar? | Reintentar mensajes fallidos desde la cola DLQ. Escalar instancias si hay saturación por demanda alta. |
| **Escalamiento** | ¿A quién llamo? | Owner Técnico (tech-lead-tickets). |
| **Comunicación** | ¿A quién informo? | Recepción/Ventas (No pueden atender público), Operaciones. |

## Changelog Técnico
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa, es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v1.0` | feat(ticket-service): Integración asíncrona con RabbitMQ y publicación de eventos | Release | Suscribirse a eventos de tickets |
| `v1.1` | feat(ticket-service): Endpoint PATCH para reparar equipos y actualizar costos | Compatible | Opcional |
| `v1.2` | Mejora del servicio de ticket | Compatible | Opcional |
| `v1.3` | Flujo de tickets + notas de venta ok | Compatible | Opcional |
| `v2.0` | Adaptación a V2 (delegando facturación y diagnóstico a nuevos ms) | Breaking | Cambiar flujos a nuevos microservicios |
| `v2.1` | feat(resiliencia S34, Fase 3): idempotencia en `POST /tickets` vía cabecera `Idempotency-Key` opt-in — un reintento con la misma clave devuelve el ticket ya creado en vez de duplicarlo (no hay clave natural: el mismo cliente puede traer el mismo equipo en visitas legítimas distintas). Logs migrados al formato mínimo S34 | Compatible | Opcional: enviar `Idempotency-Key` para que los reintentos sean seguros |
| `v2.2` | fix(observabilidad): el servicio se identificaba como `ticket_service` (guion bajo) en sus logs, mientras los otros 8 usan guion (`ticket-service`) — rompía la consistencia del formato que exige la S34 y obligaba a filtrar por dos nombres distintos en Loki | Compatible | Ninguna (si filtrabas logs por `service="ticket_service"`, ahora es `ticket-service`) |

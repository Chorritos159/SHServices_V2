# Servicio: notificacion_service

## Contratos (API Síncrona)
El contrato es la frontera pública del servicio.

| Contrato / Endpoint | Propósito | Notas de gobierno |
| :--- | :--- | :--- |
| `GET /api/v1/notificaciones` | Bandeja de notificaciones dirigidas al rol del token | Filtra por `x-user-rol` inyectado por el Gateway |
| `GET /api/v1/health` | Verificar estado de salud del servicio | — |

## Menú de Eventos (Asíncronos)
Eventos que el servicio produce o consume.

| Evento | Tipo | Versión | Semántica / Propósito |
| :--- | :--- | :--- | :--- |
| `producto.registrado` | Consumidor | `v1` | Nuevo producto en almacén → alerta a ADMIN |
| `ticket.creado` | Consumidor | `v1` | Ticket SOPORTE en EN_COLA → alerta a TECNICO de la sede |
| `ticket.listo` | Consumidor | `v1` | Ticket diagnosticado → alerta a CAJA para cobro y entrega |

## Runbook Básico
Qué hacer cuando este servicio falla. Es operativo, breve y accionable.

| Sección | Pregunta | Acción/Detalle Específico |
| :--- | :--- | :--- |
| **Incidente cubierto** | ¿Qué problema atiende? | Los técnicos/caja dejan de recibir alertas de nuevos tickets o equipos listos. |
| **Detección** | ¿Cómo sé que ocurre? | Logs `service=notificacion-service` sin líneas `result: ok` recientes; cola `notificaciones_queue` con mensajes sin consumir en RabbitMQ. |
| **Primeras revisiones** | ¿Qué miro primero? | Estado del consumidor (`🎧 conectado y escuchando`), conexión a RabbitMQ y a PostgreSQL. |
| **Acción** | ¿Qué puedo ejecutar? | Reiniciar el contenedor (`restart: always` ya lo reintenta); los mensajes durables quedan en la cola hasta que el consumidor vuelve. |
| **Escalamiento** | ¿A quién llamo? | Owner Técnico de Plataforma. |
| **Comunicación** | ¿A quién informo? | Recepción y Técnicos de la sede afectada (dependen de esta bandeja para su flujo diario). |

## Changelog Técnico
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa, es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v2.0` | Creación del servicio: notificaciones internas por rol (ADMIN/TECNICO/CAJA) dirigidas por sede | Release | Consumir `GET /api/v1/notificaciones` |
| `v2.1` | feat(resiliencia S34, Fase 3): idempotencia del consumidor — índice único `(trace_id, evento, rol_destino)` evita duplicar una alerta ante un redelivery de RabbitMQ (ack perdido). Logs migrados al formato mínimo S34 (`service, correlationId, operation, event, result, durationMs`) | Compatible | Ninguna |
| `v2.2` | feat(observabilidad S34, Fase 4): se conecta `prometheus-fastapi-instrumentator` (ya estaba en requirements.txt sin usar) — expone `/metrics` con throughput/latencia propios, scrapeado por Prometheus para el dashboard de resiliencia | Compatible | Ninguna |

# Servicio: auditoria_service

## Contratos (API Síncrona)
El contrato es la frontera pública del servicio.

| Contrato / Endpoint | Propósito | Notas de gobierno |
| :--- | :--- | :--- |
| `GET /api/v1/health` | Verificar estado de salud del servicio | No expone endpoints de negocio |

## Menú de Eventos (Asíncronos)
Eventos que el servicio produce o consume.

| Evento | Tipo | Versión | Semántica / Propósito |
| :--- | :--- | :--- | :--- |
| `ticket.*` | Consumidor | `v1` | Trazabilidad y auditoría de todas las operaciones sobre un ticket (creado, diagnosticado, facturado) |
| `Seguridad.Acceso.*` | Consumidor | `v1` | Log de accesos no autorizados o ingresos de usuarios críticos emitidos por auth_service |
| `AlertaSistema.*` | Consumidor | `v1` | Eventos de fallos del circuit breaker o anomalías detectadas en cualquier parte del sistema |

## Runbook Básico
Qué hacer cuando este servicio falla. Es operativo, breve y accionable.

| Sección | Pregunta | Acción/Detalle Específico |
| :--- | :--- | :--- |
| **Incidente cubierto** | ¿Qué problema atiende? | Los eventos no se auditan, la cola en RabbitMQ crece indefinidamente (Cuello de botella). |
| **Detección** | ¿Cómo sé que ocurre? | Métrica de RabbitMQ `Unacked Messages` > 5000 o alertas de espacio en disco del log server. |
| **Primeras revisiones** | ¿Qué miro primero? | Logs del consumidor de RabbitMQ (posibles deadlocks o desconexiones AMQP), espacio en volumen de logs. |
| **Acción** | ¿Qué puedo ejecutar? | Purgar mensajes viejos si no son vitales (Dead Letter Queue), reiniciar el consumidor, agregar más nodos consumidores concurrentes. |
| **Escalamiento** | ¿A quién llamo? | Owner Técnico (tech-lead-auditoria). |
| **Comunicación** | ¿A quién informo? | Equipo de Compliance, Seguridad Informática. (No afecta a los usuarios finales directamente). |

## Changelog Técnico
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa, es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v2.0` | Creación inicial del servicio en la arquitectura V2 | Release | Ninguna (consumidor pasivo) |

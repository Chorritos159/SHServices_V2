# Servicio: almacen_service

## Contratos (API Síncrona)
El contrato es la frontera pública del servicio.

| Contrato / Endpoint | Propósito | Notas de gobierno |
| :--- | :--- | :--- |
| `POST /api/v1/almacen/productos` | Crear o actualizar stock de repuestos en una sede | Idempotente por código y sede |
| `POST /api/v1/almacen/reservar` | Reservar repuestos necesarios para una orden técnica | Síncrono, falla si no hay stock disponible |

## Menú de Eventos (Asíncronos)
Eventos que el servicio produce o consume.

| Evento | Tipo | Versión | Semántica / Propósito |
| :--- | :--- | :--- | :--- |
| `StockAgotado.v1` | Productor | `v1` | Notifica cuando el stock disponible de un repuesto crítico llega a cero, útil para reabastecimiento |
| `StockActualizado.v1` | Productor | `v1` | Evento emitido cada vez que ingresa mercadería, útil para notificar a sistemas de catálogo |
| `TicketDiagnosticado.v1` | Consumidor | `v1` | Escucha diagnósticos para preparar proactivamente posibles repuestos antes de la reserva oficial |

## Runbook Básico
Qué hacer cuando este servicio falla. Es operativo, breve y accionable.

| Sección | Pregunta | Acción/Detalle Específico |
| :--- | :--- | :--- |
| **Incidente cubierto** | ¿Qué problema atiende? | Diagnostico falla por timeout hacia Almacén o Base de datos de almacén inalcanzable. |
| **Detección** | ¿Cómo sé que ocurre? | Gateway arroja 503/504 en endpoints `/reservar`. Alertas de latencia > 2s. |
| **Primeras revisiones** | ¿Qué miro primero? | Estado del contenedor `almacen_service`, uso de CPU, y healthcheck de la base de datos de inventario. |
| **Acción** | ¿Qué puedo ejecutar? | Escalar réplicas si hay saturación. Reiniciar conexión a BD si hay pool exhausto. Rollback si hubo release reciente que rompe queries. |
| **Escalamiento** | ¿A quién llamo? | Owner Técnico (tech-lead-almacen) / Administrador de Base de Datos (DBA). |
| **Comunicación** | ¿A quién informo? | Soporte técnico, Equipo de Diagnóstico (consumers afectados). |

## Changelog Técnico
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa, es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v1.0` | feat(almacen-service): Consumidor de eventos RabbitMQ y gestión de stock por sedes | Release | N/A |
| `v2.0` | Refactorización V2 y actualización de arquitectura | Breaking | Actualizar URLs y contratos |
| `v2.1` | feat(observabilidad S34, Fase 3): logs migrados al formato mínimo S34 (`service, correlationId, operation, event, result, durationMs`), consistente con el resto de servicios | Compatible | Ninguna |

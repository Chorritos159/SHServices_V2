# Servicio: diagnostico_service

## Contratos (API Síncrona)
El contrato es la frontera pública del servicio.

| Contrato / Endpoint | Propósito | Notas de gobierno |
| :--- | :--- | :--- |
| `POST /api/v1/diagnosticos/` | Registrar el diagnóstico técnico de un equipo y solicitar repuestos si aplican | API v1, dependiente de almacen_service si se solicitan repuestos |

## Menú de Eventos (Asíncronos)
Eventos que el servicio produce o consume.

| Evento | Tipo | Versión | Semántica / Propósito |
| :--- | :--- | :--- | :--- |
| `DiagnosticoRegistrado.v1` | Productor | `v1` | Notifica que un ticket ha sido diagnosticado y su estado de reserva de repuestos |
| `StockAgotado.v1` | Consumidor | `v1` | Utilizado para bloquear temporalmente diagnósticos que requieran dicha pieza (Prevención de fallo síncrono) |
| `ReparacionCompletada.v1` | Productor | `v1` | Evento que indica que el área técnica finalizó el trabajo físico y está listo para cobro |

## Runbook Básico
Qué hacer cuando este servicio falla. Es operativo, breve y accionable.

| Sección | Pregunta | Acción/Detalle Específico |
| :--- | :--- | :--- |
| **Incidente cubierto** | ¿Qué problema atiende? | Fallos al guardar diagnósticos por timeout con almacén o caída propia. |
| **Detección** | ¿Cómo sé que ocurre? | Logs reportando "El Servicio de Almacén no está disponible" (503 HTTP) o técnicos no pueden avanzar tickets en la UI. |
| **Primeras revisiones** | ¿Qué miro primero? | Connectivity con `almacen_service`. ¿Está caído almacén o es problema de red interna? |
| **Acción** | ¿Qué puedo ejecutar? | Si almacén está caído, notificar a técnicos que se guardará localmente (si hay política fallback) o pausar integraciones. Reintentar. |
| **Escalamiento** | ¿A quién llamo? | Owner Técnico de Diagnósticos / Owner de Almacén. |
| **Comunicación** | ¿A quién informo? | Área de Técnicos (Centro de Servicios) y Soporte al Cliente. |

## Changelog Técnico
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa, es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v1.0` | Creación del servicio para aislar la lógica de diagnósticos | Release | Consumir nuevo contrato de diagnósticos |
| `v1.1` | feat(observabilidad S34, Fase 3): logs migrados al formato mínimo S34 (`service, correlationId, operation, event, result, durationMs`), consistente con el resto de servicios | Compatible | Ninguna |
| `v1.3` | feat(negocio): **dueno de las ASIGNACIONES** (ADR-0012): `POST /asignaciones/tomar` (exclusivo, 409 si otro tecnico lo tomo; idempotente), `GET /asignaciones/mias` (bandeja del tecnico, sin depender de ticket-service) y `GET /asignaciones/` (ADMIN: quien atiende que). feat(resiliencia): idempotencia por `Idempotency-Key` en el diagnostico (reserva stock: reintentar no debe duplicar). fix: registrar un diagnostico para un ticket que ya tenia devolvia 500 opaco -> ahora 409 legible, y se comprueba ANTES de reservar stock | **Aditivo** | Tomar tickets via `/asignaciones/tomar`; "Mis Tickets" desde `/asignaciones/mias` |

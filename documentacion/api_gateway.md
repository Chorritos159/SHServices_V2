# Servicio: api_gateway

## Contratos (API Síncrona)
El contrato es la frontera pública del servicio.

| Contrato / Endpoint | Propósito | Notas de gobierno |
| :--- | :--- | :--- |
| `* /api/v1/{service}/{path}` | Enrutador dinámico hacia microservicios internos | Inyecta X-Correlation-ID, Circuit Breaker, Validación JWT |

## Menú de Eventos (Asíncronos)
Eventos que el servicio produce o consume.

| Evento | Tipo | Versión | Semántica / Propósito |
| :--- | :--- | :--- | :--- |
| `PicoTraficoDetectado.v1` | Productor | `v1` | Notifica anomalías de peticiones por segundo (DDoS o picos legítimos) |
| `FalloCircuitoAbierto.v1` | Productor | `v1` | Alerta emitida cuando el circuit breaker bloquea un microservicio por fallos continuos |

## Runbook Básico
Qué hacer cuando este servicio falla. Es operativo, breve y accionable.

| Sección | Pregunta | Acción/Detalle Específico |
| :--- | :--- | :--- |
| **Incidente cubierto** | ¿Qué problema atiende? | Gateway responde HTTP 503 o 403 masivos, bloqueando toda la plataforma. |
| **Detección** | ¿Cómo sé que ocurre? | Gráficos de Error Rate en rojo absoluto. Alerta P1 de disponibilidad global. |
| **Primeras revisiones** | ¿Qué miro primero? | Validar si el servicio de auth está caído (provocando 403) o si los microservicios internos cambiaron de IP/puerto (provocando 503). |
| **Acción** | ¿Qué puedo ejecutar? | Aumentar el timeout temporalmente, reiniciar el pod del gateway, limpiar caché de resolución DNS interna. |
| **Escalamiento** | ¿A quién llamo? | Arquitecto Cloud / Owner Técnico de Plataforma / DevOps. |
| **Comunicación** | ¿A quién informo? | Todo el negocio, todos los equipos de desarrollo. |

## Changelog Técnico
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa, es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v1.0` | feat(api-gateway): Implementar escudo de seguridad JWT y proxy reverso | Release | Enviar header Authorization |
| `v1.1` | feat(infra): Dockerización completa de la arquitectura | Compatible | Ninguna |
| `v2.0` | Actualización de rutas para nuevos microservicios de la V2 | Compatible | Ninguna |
| `v2.1` | feat(resiliencia S34): circuit breaker formal (CLOSED/OPEN/HALF_OPEN) por servicio, timeouts por operación, retry con backoff+jitter (solo lecturas), fallback honesto (503/504 con estado del circuito y Retry-After) y métricas Prometheus (`gateway_circuit_state`, `gateway_circuit_opens_total`, `gateway_proxy_requests_total`, `gateway_retries_total`, `gateway_fallbacks_total`, `gateway_timeouts_total`) | Compatible | Ninguna (opcional: manejar `Retry-After` en 503 y el campo `circuito` del cuerpo de error) |
| `v2.2` | fix(infra): Gunicorn de 4 workers a 1 en el Gateway — verificación en vivo con Toxiproxy detectó que el circuit breaker y sus métricas "parpadeaban" entre CLOSED/OPEN porque cada worker mantenía su propio breaker y su propio registro Prometheus en memoria; con 1 worker el estado es una única fuente de verdad consistente | Compatible | Ninguna |

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
| `v2.3` | feat(resiliencia S34, Fase 2): contención de recursos — bulkhead por servicio (cupo de llamadas en vuelo, 503 sin cola oculta), shedding preventivo de tráfico de baja prioridad al 70% de ocupación (protege escrituras críticas: POST/PUT/PATCH/DELETE), rate limiting global con token bucket (429 + Retry-After) y sampling de logs de rutina bajo carga alta (errores/warnings nunca se muestrean). Métricas nuevas: `gateway_bulkhead_in_flight`, `gateway_bulkhead_rejects_total{razon}`, `gateway_rate_limit_rejects_total`, `gateway_logs_sampled_total` | Compatible | Ninguna (opcional: manejar 429 con `Retry-After` igual que el 503 del circuito) |
| `v2.4` | feat(resiliencia S34, Fase 3): logs migrados al formato mínimo S34 (`service, correlationId, operation, event, result, durationMs`) en cada proxy_request/bulkhead/rate_limit; fix del `LoggerAdapter` que descartaba silenciosamente los campos pasados por-llamada (ahora los fusiona con el contexto base) | Compatible | Ninguna |
| `v2.5` | feat(resiliencia S34, Fase 5): rate limit del Gateway configurable por entorno (`RATE_LIMIT_RPS`/`RATE_LIMIT_BURST`, default 20/40 — mismo comportamiento que antes) para poder ampliarlo temporalmente en las pruebas de carga 500k/1M sin tocar código | Compatible | Ninguna |
| `v2.6` | fix(observabilidad): se inicializan todas las series de métricas al arranque. Un Counter de `prometheus_client` no existe como serie hasta su primer `.inc()`, así que los paneles de Grafana mostraban "No data" (en vez de 0) mientras no hubiera ocurrido nunca un retry/fallback/timeout/rechazo — se leía como "la métrica está rota" cuando significaba "no ha pasado nada malo" | Compatible | Ninguna |
| `v2.7` | feat(observabilidad S34): el dashboard cubre el "dashboard mínimo" completo de la S34 (pág. 18) — nueva fila de **Saturación** (CPU/memoria/conexiones/fds, que faltaba por completo) y panel de **errores por código HTTP**. Fix del panel de error rate: filtraba `status=~"5.."` pero el instrumentator agrupa el status en clases (`5xx`), así que nunca podía mostrar datos | Compatible | Ninguna |

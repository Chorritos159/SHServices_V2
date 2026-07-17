# Plan de Integración Final — SHServices V2 (S34)

> Rama de trabajo: `main`.
> Objetivo: cerrar las brechas que la **Sesión 34 (Prevalidación técnica)** exige
> como criterios críticos, sobre todo **resiliencia de aplicación** y su
> **observabilidad** (el dashboard debe mostrar circuit state, retry/fallback,
> queue depth, consumer lag). El flujo funcional ya opera; aquí se lo hace
> **resistente, observable bajo presión y demostrable ante fallas**.

## Regla de oro (todas las fases)

Cada cambio de código sube una **nueva versión en el changelog del servicio**
afectado (`documentacion/<servicio>.md`, cuadro `Versión | Cambio | Tipo | Acción
para consumidores`), clasificando Compatible/Breaking. Cada mecanismo de
resiliencia se **verifica en vivo** (con Toxiproxy o apagando contenedores) y se
deja evidencia.

## Diagnóstico de partida (qué hay y qué falta)

| Mecanismo S34 | Estado actual | Acción |
| :-- | :-- | :-- |
| Timeout | ✅ 5s fijo en el gateway | Ajustar a por-operación |
| Retry + backoff + jitter | ✅ Fase 1 | — |
| Circuit breaker con **estados** (CLOSED/OPEN/HALF_OPEN) | ✅ Fase 1 | — |
| Fallback honesto | ✅ Fase 1 | — |
| Bulkhead | ✅ Fase 2 | — |
| Backpressure (rate limit 429) | ✅ Fase 2 | — |
| Buffering + dropping/sampling | ✅ Fase 2 (sampling de logs; shedding de tráfico) | — |
| Idempotencia | ✅ Fase 3 | — |
| Logs estructurados S34 (operation/durationMs/event/result) | ✅ Fase 3 | — |
| **Dashboard: circuit state, retry/fallback, queue depth, consumer lag** | ✅ Fase 4 | — |
| Carga 100k/500k/1M + fallas controladas | ❌ | Fase 5 |
| Ya presente: Toxiproxy, Loki+Promtail, Prometheus, Grafana, RBAC, Gunicorn | ✅ | reutilizar |

## Fases

### FASE 1 — Resiliencia núcleo en el gateway ⭐ (esta fase)
Circuit breaker **formal** (CLOSED → OPEN → HALF_OPEN con umbral, cooldown y
sonda), timeouts por operación, **retry con backoff + jitter** (solo lecturas
seguras), **fallback honesto**, y **métricas Prometheus custom** para que
Grafana pueda graficarlas: `gateway_circuit_state`, `gateway_retries_total`,
`gateway_fallbacks_total`, `gateway_timeouts_total`, `gateway_requests_total`.
Se reutiliza `/metrics` del Instrumentator (mismo scrape de Prometheus).
**Verificación:** con Toxiproxy inyectar corte/latencia a `ticket_proxy` →
observar el circuito abrir (fail-fast), el retry y el fallback, y las métricas
subir. Changelog: api_gateway.

### FASE 2 — Contención de recursos
Bulkhead por dependencia (límite de llamadas en vuelo → 503 controlado),
rate limiting global (token bucket → 429 con Retry-After), shed de baja
prioridad, y sampling de logs bajo carga. Métricas: `gateway_bulkhead_in_flight`,
`gateway_bulkhead_rejects_total`, `gateway_rate_limit_rejects_total`.
**Verificación:** ráfaga concurrente → 429/503 controlados sin caída.

### FASE 3 — Idempotencia + logs S34 + estados degradados ✅ COMPLETA
Idempotencia en las escrituras: `POST /tickets` con `Idempotency-Key` opt-in
(no hay clave natural — el mismo cliente puede traer el mismo equipo en
visitas distintas y legítimas); `POST /facturas` por clave natural
`id_ticket` (un ticket tiene, a lo sumo, una factura). Idempotencia de
consumidores RabbitMQ (auditoria-service, notificacion-service) por índice
único `(trace_id, evento[, rol_destino])` — un redelivery no duplica la
traza ni la alerta. Logs de los 9 servicios migrados al formato mínimo S34
(`service, correlationId, operation, event, result, durationMs`), con un
`LoggerAdapter` que ahora SÍ fusiona campos por-llamada (antes los
descartaba silenciosamente). Estado degradado honesto: ya cubierto por el
fallback de Fase 1 (503/504 + `circuito` + `trace_id`).
**Verificado en vivo:** POST duplicado de ticket con la misma
`Idempotency-Key` → mismo `idTicket`, 1 sola fila en BD. POST duplicado de
factura para el mismo ticket → misma `idFactura`, 1 sola fila. Insert
directo duplicado en `auditoria_eventos` (simulando redelivery) → rechazado
por el índice único `ux_auditoria_trace_evento`. Changelog por servicio.

### FASE 4 — Dashboard de resiliencia en Grafana ✅ COMPLETA
Dashboard versionado (`grafana/dashboards/resiliencia_s34.json`, provisionado
por archivo — no se arma a mano en la UI) con 16 paneles en 6 filas:
throughput, latencia p50/p95/p99 y error rate del Gateway; **estado del
circuit breaker por servicio** (state-timeline CLOSED/HALF_OPEN/OPEN) y
aperturas acumuladas; retry/fallback/timeout por servicio; bulkhead en vuelo
y rechazos por razón (saturado vs. shed_baja_prioridad); rate limit global;
**queue depth** (`rabbitmq_queue_messages_ready`) y **consumer lag**
(`rabbitmq_queue_messages_unacked`) por cola vía el plugin
`rabbitmq_prometheus` (endpoint `/metrics/per-object`, el único que trae el
desglose por cola); desenlaces del proxy y logs muestreados. Se activó
además `prometheus-fastapi-instrumentator` en auditoria-service y
notificacion-service (ya tenían el paquete instalado pero sin conectar).
**Verificado:** los 6 targets de Prometheus en estado `up`; las queries de
cada panel devueltas por el datasource proxy de Grafana (mismo camino que
usa el frontend) confirmadas con datos reales — circuito de `tickets` en
OPEN tras la prueba de Toxiproxy, 26 rechazos `shed_baja_prioridad` de la
ráfaga a auditoría, 16 rechazos de rate limit, colas `auditoria_tickets_queue`
y `notificaciones_queue` con su profundidad real.

### FASE 5 — Carga y fallas controladas 🔶 EN PROGRESO
Suite `pruebas/` (scripts + runners Python en `pruebas/lib/`), 6 pruebas:
traza única, 780 concurrentes con límites normales, 3 niveles de carga
sostenida por **nodos y bloques** (100k/500k/1M — ver metodología abajo), y
6 fichas de falla controlada (servicio caído, latencia, cola saturada,
rate limit, evento duplicado). `Registro de carga` y `Matriz de revisión de
resiliencia` de la S34 llenados con el formato exacto del material (págs.
24 y 28) en `documentacion/registro_de_carga.md` y
`documentacion/matriz_revision_resiliencia.md`; fichas en
`documentacion/fichas_falla_controlada.md` (formato pág. 30).

**Metodología de carga (rediseñada):** el generador original (un pool de
hilos disparando sin parar hasta completar el conteo literal) tomaba
1.5-4 horas para 500k/1M — poco práctico. Se reemplazó por
`pruebas/lib/carga_nodos.py`: varios **nodos** concurrentes independientes
mandan **bloques** sucesivos de peticiones (no un hilo, no todo de golpe),
con **backoff escalonado 3s→5s→8s + jitter** entre bloques que topan con
429/503, acotado a una **ventana de tiempo fija de 10-15 min** por nivel
(100k: 6 nodos x bloque 40 x 10min; 500k: 10 x 80 x 15min; 1M: 15 x 120 x
15min). La etiqueta 100k/500k/1M es el nivel de carga ofrecida, no un
conteo a cumplir — se reporta el throughput real sostenido y, si no se
alcanza la etiqueta, se explica el cuello de botella con métricas (regla
explícita de la S34).

**Completado y verificado en vivo:** pruebas 1, 2 y 6 (todas las fichas de
caos). **Pendiente, a ejecutar juntos:** pruebas 3-5 (100k/500k/1M, ~40 min
en total con el nuevo diseño) — los scripts están escritos y revisados
(se corrigió un bug real de concurrencia: `asyncio.Lock` usado con `with`
en vez de `async with`), pero no se corrieron todavía a pedido explícito.
Rate limit del Gateway hecho configurable por entorno
(`RATE_LIMIT_RPS`/`RATE_LIMIT_BURST`) para soportar estas corridas — antes
era un valor fijo en código; ya verificado que la ampliación funciona
(corrida previa con el diseño anterior, ver `registro_de_carga.md`). Toda
la suite migrada a Python puro después (cero `.sh` en `pruebas/`), a
pedido explícito.

### FASE 6 — Gobierno y paquete de defensa ✅ COMPLETA
- `matriz-resiliencia.md`: actualizada, referencia cruzada a los ADRs y a
  `brechas_finales.md`.
- `matriz-auditoria.md`: catálogo de eventos corregido (faltaba
  `TicketListo.v1`/`ticket.listo`), documentada la brecha de
  `producto.registrado` sin auditar, y la idempotencia del consumidor
  (Fase 3).
- `catalogo-servicios.md`: agregado `notificacion-service` (faltaba por
  completo del catálogo de microservicios), nueva sección §7 Resiliencia
  con el resumen de los mecanismos de las Fases 1-5.
- `runbook.md`: agregado `notificacion-service` a los health checks,
  corregido el nombre de la toxina de ejemplo (estaba desalineado con el
  comportamiento real de Toxiproxy), agregado `.env`/`RATE_LIMIT_*` a
  prerrequisitos, nuevas entradas de troubleshooting (429/503 de
  contención), pointer a `pruebas/06_caos.py` como verificación completa.
- `documentacion/adr/`: 3 ADRs nuevos (el proyecto no tenía ninguno) —
  ADR-0001 (Gateway 1 worker), ADR-0002 (estrategia de idempotencia),
  ADR-0003 (carga por nodos/bloques).
- `documentacion/brechas_finales.md`: tabla consolidada de 9 brechas reales
  (riesgo/acción/responsable) para el dictamen — todas con evidencia o
  razonamiento concreto, ninguna bloquea la demostración de los mecanismos
  de resiliencia exigidos.
- Changelogs verificados: los 8 servicios (+ gateway) sin huecos de
  versión, cada fase de resiliencia reflejada donde corresponde.
- `README.md` raíz: ya cubre el checklist operativo completo (Fase 4/5).

### FASE 7 — El circuit breaker de `tickets` no abre (BUG REAL) ✅ COMPLETA

**Síntoma observado:** al pausar `notificacion-service`, el circuito abre y
se ve en Grafana y en Dozzle. Al pausar `ticket-service`, **no pasa nada**:
el circuito sigue en CLOSED y el cliente recibe un **500 opaco** en vez del
503 con fallback honesto.

**Causa raíz (reproducida en vivo):** `tickets` es el único servicio que
el Gateway alcanza **a través de Toxiproxy** (`http://toxiproxy:8666`); los
demás van directo al contenedor.

- Servicio directo caído -> nadie escucha en el puerto -> `httpx.ConnectError`.
- `ticket-service` caído -> **Toxiproxy sigue vivo** y acepta la conexión
  TCP; al no poder hablar con el upstream muerto, cierra la conexión sin
  responder -> **`httpx.ReadError`**.

`_proxy_resiliente` solo captura `ConnectError` y `TimeoutException`, así
que el `ReadError` se escapa hasta el manejador global: 500, y el breaker
**nunca se entera del fallo**. El mecanismo de resiliencia queda ciego
justo para el servicio que se usa para demostrarlo.

**Corrección aplicada:** se captura toda la familia `httpx.TransportError`
(ConnectError, ReadError, WriteError, RemoteProtocolError, ProxyError...)
en vez de enumerar dos casos y dejar el resto al azar. `TimeoutException`
va primero en el `except` porque es subclase de `TransportError` (si no,
nunca se alcanzaría). Además se afinó el retry: solo `ConnectError`
garantiza que el request **nunca llegó** (reintentable con cualquier
método); con `ReadError` la conexión sí se abrió y el servidor pudo haber
procesado la escritura antes de cortar, así que un POST **no** se
reintenta (duplicaría).

**Verificado** con `pruebas/07_breaker_todos.py` (nueva, queda como
regresión): `docker stop` a los 6 servicios, uno por uno. Antes: `tickets`
daba 500 y el circuito seguía en CLOSED. Ahora los 6 dan **503 controlado,
circuito OPEN y recuperación automática a CLOSED** tras el cooldown.

### FASE 8 — Cobertura de logs y pruebas para TODOS los servicios 🔴

Dos huecos que la Fase 7 deja al descubierto:

1. **Logs:** la Fase 3 dejó los campos S34 en las operaciones de negocio,
   pero hay que verificar servicio por servicio que **toda** operación
   (incluidos health checks, consumidores y publicadores) emite log
   estructurado — no solo las rutas principales.
2. **Pruebas:** hoy `01_traza_unica.py` toca 4 servicios y las de carga
   solo golpean `tickets`. **Ninguna prueba ejercita los 8.** Un servicio
   sin tráfico en las pruebas es un servicio cuyo comportamiento bajo
   presión y ante fallas nadie verificó.

**Acción:**
- Prueba de traza: cubrir el flujo real completo (caja registra -> técnico
  diagnostica -> caja cobra y entrega) + los casos sueltos (admin agrega
  inventario, consulta de auditoría/notificaciones).
- Pruebas de carga (nodos/bloques y la corta): repartir el tráfico entre
  **todos** los servicios, no solo `tickets`.
- Caos: `docker stop` a cada servicio, no solo a `almacen`.

### FASE 9 — Swagger de todos los servicios + webhooks + seed 🔶 EN PROGRESO

- **Swagger:** hoy solo `api-gateway` (8000) y `auth-service` (8003)
  publican puerto; el `/docs` de los otros 6 es inalcanzable desde el host.
  Exponer un puerto por servicio y documentarlos. *(pendiente)*
- **Webhooks salientes:** ✅ **HECHO.** Implementados en `notificacion-service`
  (`app/core/webhooks.py` entrega, `app/api/webhooks.py` suscripciones,
  `app/models/webhook.py` tablas). Un tercero se suscribe con su URL a un
  evento (`ticket.creado`/`ticket.listo`/`producto.registrado`/`*`); al
  consumir el evento se hace POST **firmado con HMAC-SHA256** (`X-Firma`),
  con hasta 3 reintentos+backoff y bitácora en `webhook_entregas`. Var
  `WEBHOOK_SECRET`, `httpx` agregado a requirements, `extra_hosts` en el
  compose para poder entregar a un receptor del host.
  **Verificado en vivo:** suscripción -> ticket creado -> primer intento
  fallido (receptor caído) registrado con 3 reintentos y estado FALLIDO;
  con el receptor arriba, ENTREGADO en 1 intento (HTTP 200) y firma HMAC
  validada por el receptor.
- **Seed de inventario:** el almacén arranca vacío; sembrar productos
  iniciales de forma idempotente, como el seed de usuarios. *(pendiente)*

```
Fase 1 (resiliencia núcleo) → Fase 2 (contención) → Fase 3 (idempotencia+logs)
   → Fase 4 (dashboard) → Fase 5 (carga+fallas) → Fase 6 (gobierno)
   → Fase 7 (fix breaker tickets) → Fase 8 (cobertura logs+pruebas)
   → Fase 9 (swagger+webhooks+seed)
```
Cada fase se entrega, se verifica y se documenta antes de la siguiente.

# Changelog — SHServices V2

Registro de cambios relevantes del proyecto. Se documenta **qué cambió y por
qué**, no solo qué se tocó: un cambio sin motivo escrito es un cambio que nadie
podrá revisar dentro de seis meses.

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

---

## [2.5.0] — 2026-07-20 — Corrección de concurrencia y orden

Bloque dedicado a los fallos que solo aparecen bajo caída de servicios. Todos se
detectaron probando escenarios reales, no leyendo código.

### Corregido

- **El outbox no respetaba el orden de llegada.** Dos técnicos tomando el mismo
  ticket con `diagnostico-service` caído: ganaba el que pulsaba **después**.
  Tres causas encadenadas:
  1. `ORDER BY creado_en` sin desempate; se añade el `id` autoincremental.
  2. `creado_en` se fijaba **al encolar**, no al recibir. Con el destino caído
     el Gateway reintenta 4 veces (3+5+8 s) antes de encolar, y esos fallos
     abren el circuito: la petición siguiente lo encuentra abierto, falla al
     instante y se encolaba ~14 s **antes** que la primera.
  3. El bloqueo de cabeza de cola se saltaba por el *backoff*: al fallar, la
     cabeza recibía `proximo_reintento_en` futuro y desaparecía de la consulta,
     dejando que la siguiente se adelantara.
- **Idempotencia sujeta a carreras** en `almacen`, `tickets` y `diagnostico`.
  Comprobar-y-luego-guardar no es atómico: con el circuito abierto el Gateway
  reintenta 4 veces con la misma clave y se creaban 4 registros. Se sustituye
  por **reserva previa de la clave**, arbitrada por el índice único.
- **El cobro no cerraba el ticket ni consumía el stock** si `ticket-service`
  estaba caído: el BFF llamaba a `/entregar` con un `catch` vacío y nadie lo
  reintentaba. Ahora el cierre es por evento (`ticket.facturado`).
- **`message.process()` descartaba mensajes.** Su comportamiento por defecto
  rechaza sin devolver a la cola: al levantar todo a la vez, almacén aún
  arrancaba y el evento del cobro desaparecía. Corregido con `requeue=True`.
- **El ticket se cerraba aunque el stock no saliera.** `_mover_stock` ignoraba
  las respuestas de error (solo capturaba fallos de conexión). Ahora devuelve
  los fallidos y `/entregar` responde 503 sin cerrar: es preferible un ticket
  abierto reintentable a uno cerrado con stock colgado.
- **Circuito de facturas abriéndose y cerrándose sin parar** (652 aperturas en
  una corrida de 100k, p95 de 6,2 s, throughput de 203 a 106 rps).
  `listar_garantias` hacía `.all()` sin límite ordenando por un campo sin
  índice: escaneo completo en cada petición, por encima del timeout de 4 s.
- **Clave de idempotencia del Gateway compartida entre escrituras.** Era
  `gw-{correlation_id}` a secas, así que dos escrituras del mismo flujo
  compartían clave y la segunda recibía la respuesta guardada de la primera.
  Ahora incluye método y ruta.
- **Alta de productos sin precio**: el formulario no enviaba el campo y todo
  entraba a 0, incluidos los productos vendibles.
- **Notificación de diagnóstico sin llegar a CAJA**: el consumidor escuchaba
  `ticket.listo` pero quien publica es `diagnostico-service` con
  `ticket.diagnosticado`. Esa rama no se ejecutaba nunca.
- **Panel de usuarios roto**: el BFF no doblaba el path y el Gateway devolvía
  404 tanto al listar como al registrar.

### Añadido

- **Consumidor de eventos en `ticket-service`** (`app/core/consumer.py`). No
  existía: el diagnóstico publicaba y nadie escuchaba, así que el ticket se
  quedaba en `EN_COLA` para siempre. Cola durable, `connect_robust` y ACK solo
  si el handler termina bien.
- **Idempotencia en `almacen-service`** (tabla `idempotencia_almacen`) para
  altas y movimientos de stock.
- **Vista "Consulta de Garantías y Facturas"**: las ventas de mostrador no
  emiten garantía, así que sin el listado de facturas quedaban invisibles.
- **`pruebas/13_resiliencia_en_vivo.py`**: 6 demos cortas para la sustentación.
- **`pruebas/14_datos_demo.py`**: datos de demo por la API, idempotente.
- **`pruebas_k6/caos.py`**: caos bajo carga real con Toxiproxy.
- **Documentación**: `resiliencia.md` (los 12 mecanismos con archivo y línea),
  `fichas_contractuales.md` (11 endpoints), este `CHANGELOG.md`.

### Cambiado

- **Generador de carga a k6.** Se elimina `pruebas_reales/`: su generador en
  Python topaba en ~105 rps y **era él mismo el cuello de botella** (1 proceso
  → 105 rps, 2 → 171, 4 → 257), así que medía al cliente y no al sistema.
- **Esquema de red interna configurable** (`ESQUEMA_INTERNO`, `ESQUEMA_MQ`).
  Pasar a TLS es ahora un cambio de configuración, no de código en siete sitios.
- **Índices**: compuesto `(estado, fecha_registro)` en tickets, y por fecha en
  garantías, facturas y asignaciones. Se crean en el arranque con
  `IF NOT EXISTS`, porque `create_all` solo añade índices al crear la tabla.
- **Pool de `ticket-service`** a 30+15, y cierre explícito de la sesión antes de
  las tareas en segundo plano (FastAPI la mantiene viva hasta que terminan).

---

## [2.0.0] — 2026-07-19 — Resiliencia S34 y pruebas de carga

### Añadido

- Circuit breaker con estado compartido en Redis (ADR-0015), sonda activa
  (ADR-0014), bulkhead con shedding, rate limit por token bucket, outbox
  transaccional, retry con backoff y jitter.
- Observabilidad: Prometheus en modo multiproceso, dashboard de Grafana,
  agregación de logs con Loki, Dozzle para logs en vivo.
- Pruebas de carga con k6 (fases humo / 100k / 500k / 1M) y de caos.
- Venta de mostrador con degradación: si `ticket-service` cae, la venta se
  completa igual con su comprobante.

### Corregido

- Gateway a 8 workers con métricas multiproceso: el gauge del circuito usaba
  `multiprocess_mode="max"` y se quedaba clavado en OPEN para siempre.
- Códigos de producto con secuencia de PostgreSQL en vez de `MAX(codigo)+1`,
  que producía carreras y HTTP 500 bajo concurrencia.
- Colisiones de ID por entropía insuficiente (4 hex → 12 hex).
- El Gateway descartaba el query string: ningún parámetro llegaba a los
  servicios.
- Pool de conexiones agotado devolvía 500 en vez de 503.

---

## [1.0.0] — 2026-07-17 — Base del sistema

### Añadido

- Ocho microservicios (auth, tickets, almacén, diagnóstico, facturación,
  auditoría, notificaciones) tras un API Gateway como único punto de entrada.
- Coreografía por eventos sobre RabbitMQ (exchange `tickets.eventos`).
- Frontend Next.js con BFF y cookies HttpOnly.
- Gobierno: catálogo de servicios, matriz de auditoría, ADRs, SLA y runbook.

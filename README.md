# SHServices V2

Sistema de soporte técnico multi-sede (Piura y Talara): recepción de
equipos, diagnóstico, gestión de repuestos, facturación y notificaciones
internas por rol, sobre una arquitectura de microservicios con resiliencia,
observabilidad y gobierno documentado (S26/S29/S31/S34).

> La documentación debe permitir **ejecutar**, no solo describir. Esta
> página responde exactamente lo que hace falta para levantar el sistema,
> operarlo y auditarlo.

## Documentación

Toda la evidencia técnica del proyecto, ordenada por lo que responde:

| Documento | Responde a |
| :-- | :-- |
| [catalogo-servicios.md](catalogo-servicios.md) | Qué hace cada servicio, quién lo posee, de qué depende |
| [documentacion/fichas_contractuales.md](documentacion/fichas_contractuales.md) | Contrato de los 11 endpoints principales |
| [documentacion/resiliencia.md](documentacion/resiliencia.md) | Los 12 mecanismos: dónde vive cada uno y por qué esos valores |
| [matriz-resiliencia.md](matriz-resiliencia.md) | Qué mecanismo protege cada dependencia |
| [matriz-auditoria.md](matriz-auditoria.md) | Qué se audita y dónde queda la traza |
| [runbook.md](runbook.md) | Cómo operarlo y qué hacer ante un incidente |
| [documentacion/sla.md](documentacion/sla.md) | Compromisos de disponibilidad y latencia |
| [documentacion/brechas_finales.md](documentacion/brechas_finales.md) | **Qué NO cubre este proyecto y por qué** |
| [CHANGELOG.md](CHANGELOG.md) | Qué cambió en cada versión y por qué |
| [documentacion/adr/](documentacion/adr/) | Decisiones de arquitectura con su contexto |
| [documentacion/registro_de_carga.md](documentacion/registro_de_carga.md) | Resultados medidos de las pruebas de carga |

## Cómo levantar el entorno

```bash
# 1. Variables de entorno (nunca se suben secretos reales al repo)
cp .env.example .env
# completar POSTGRES_PASSWORD, RABBITMQ_DEFAULT_PASS, JWT_SECRET_KEY,
# GF_SECURITY_ADMIN_PASSWORD con valores propios (o los de la demo, ver
# documentacion/*.md de cada servicio para las credenciales de prueba)

# 2. Levantar TODO, incluida la web (un solo comando)
docker compose up -d --build

# 3. Verificar
curl http://localhost:8000/health     # backend
curl http://localhost:3001/login      # frontend

# 4. Datos de demo (opcional, pero recomendado para enseñar el sistema)
python pruebas/14_datos_demo.py

# 5. Detener
docker compose down          # detiene todo, CONSERVA los datos
docker compose down -v       # detiene y BORRA los datos (destructivo)
```

### Datos de demo

Los **usuarios** y el **almacén** se siembran solos al arrancar. Lo que no
existe recién levantado son los tickets, así que los paneles salen vacíos y no
hay nada que enseñar. `pruebas/14_datos_demo.py` rellena ese hueco: crea 3
tickets de soporte en PIURA y lleva el primero por el ciclo completo
(diagnóstico con reserva de stock  cobro con garantía de 90 días).

Va **por la API y no con INSERTs** a propósito: así los datos respetan las
reglas de negocio, reservan stock de verdad y publican sus eventos a RabbitMQ.
Un INSERT directo dejaría un ticket que ningún evento anunció y que las
notificaciones nunca verían.

Es **idempotente** (usa `Idempotency-Key` derivadas): correrlo dos veces
devuelve lo mismo y no duplica nada. Con `--tickets N` se crean hasta 5.

| Usuario | Contraseña | Rol | Sede |
|---|---|---|---|
| `admin` | `admin123` | ADMIN | PIURA |
| `caja01` | `caja123` | CAJA | PIURA |
| `tecnico01` | `tecnico123` | TECNICO | PIURA |
| `caja02` | `caja123` | CAJA | TALARA |
| `tecnico02` | `tecnico123` | TECNICO | TALARA |

Entra en **http://localhost:3001**. Cada rol ve lo suyo: ADMIN el almacén,
auditoría y garantías; TECNICO la cola de diagnóstico; CAJA la venta de
mostrador. Para borrar lo generado:
`python pruebas/limpiar_datos_carga.py --borrar`.

Todos los servicios usan `restart: always` y health checks — si el proceso
**crashea**, se reinicia solo (~2 s). El Gateway es el **único** punto de
entrada público para tráfico de negocio (`8000`); el resto de microservicios
solo son alcanzables dentro de la red Docker `shservices-net`.

**Prueba en 30 segundos** (flujo completo por los 8 servicios):
```bash
python pruebas/08_flujo_completo.py
```

## Checklist de gobierno (S31)

Respondo aquí el checklist estricto de la sesión 31 para los siete servicios de
negocio. La regla es que un servicio crítico con más de tres "No" no está listo.

| Pregunta | Respuesta | Dónde se comprueba |
| :-- | :-- | :-- |
| ¿Tiene owner funcional y owner técnico? | Sí | [catalogo-servicios.md](catalogo-servicios.md) §2 |
| ¿Tiene contrato de API/evento documentado? | Sí | [fichas_contractuales.md](documentacion/fichas_contractuales.md) y `/docs-todos` |
| ¿Tiene versión vigente y política de cambios? | Sí | [CHANGELOG.md](CHANGELOG.md) y la política de versionado del catálogo |
| ¿Identifica consumidores y dependencias? | Sí | Campo "Consumidores probables" de cada ficha contractual |
| ¿Tiene ADR para decisiones relevantes? | Sí | [documentacion/adr/](documentacion/adr/) — 15 decisiones registradas |
| ¿Tiene runbook para el incidente principal? | Sí | [runbook.md](runbook.md) §8, playbooks por incidente |
| ¿Tiene trazabilidad hacia problema, capacidad y evidencia? | Sí | `trace_id` propagado y persistido en auditoría; ver `pruebas/08_flujo_completo.py` paso 10 |
| ¿Tiene changelog o notas de release? | Sí | [CHANGELOG.md](CHANGELOG.md) |

Ocho de ocho. Lo que sí reconozco como pendiente está recogido, sin adornos, en
[brechas_finales.md](documentacion/brechas_finales.md): entre otras, el tráfico
interno sin TLS, la cobertura de pruebas unitarias, el alcance funcional de
varios servicios y del frontend, y que la prueba de caos derriba servicios de
uno en uno en vez de combinarlos.

## Ownership (quién decide, mantiene y opera)

El negocio tiene cinco áreas: **Recepción**, **Técnico**, **Administrador**,
**Área de facturación** y **Soporte de TI**. Cada servicio tiene un owner
funcional (decide qué hace) y un owner técnico (lo mantiene y opera). Un
"equipo backend" genérico no es owner suficiente ante un incidente.

| Servicio | Owner funcional | Owner técnico / operativo |
| :-- | :-- | :-- |
| ticket-service | Recepción | Soporte de TI |
| diagnostico-service | Técnico | Soporte de TI |
| almacen-service | Administrador | Soporte de TI |
| facturacion-service | Área de facturación | Soporte de TI |
| auditoria-service | Administrador | Soporte de TI |
| notificacion-service | Recepción | Soporte de TI |
| auth-service / api-gateway | Administrador / Soporte de TI | Soporte de TI |

Matriz completa (decide · mantiene · consume · opera) y fichas de catálogo por
servicio: [`catalogo-servicios.md`](catalogo-servicios.md).

## Servicios y puertos

| Servicio | Puerto host | Notas |
| :-- | :-- | :-- |
| **api-gateway** | `8000` | Único punto de entrada para tráfico de negocio (`/api/v1/...`) |
| **frontend** | `3001` | Aplicación web (Next.js) en **modo producción**, dentro de Docker. Contenedor `shservices-frontend` |
| auth-service | *(sin exponer)* | Desde 2026-07-18 **ya no publica puerto**: el login pasa por el Gateway (`POST :8000/api/v1/auth/login`) y así hereda rate limit, bloqueo por intentos y circuit breaker. Su Swagger se lee en `:8000/docs-todos` (OWASP hallazgo 3) |
| postgres-db | *(sin exponer)* | Solo alcanzable dentro de la red Docker |
| rabbitmq | `15672` (panel admin), `15692` (métricas Prometheus) | Usuario/clave en `.env` |
| toxiproxy | `8474` (API de control) | Inyecta fallas en `ticket-service` (Chaos Engineering) |
| prometheus | `9090` | Scrapea Gateway, ticket/auditoria/notificacion-service y RabbitMQ |
| grafana | `3000` | Dashboard de resiliencia provisionado automáticamente (Fase 4) |
| loki | *(sin exponer)* | Agregación de logs (búsqueda histórica), consultable desde Grafana |
| **dozzle** | `9999` | **Logs de todos los contenedores en vivo**, sin refrescar |
| sonarqube | `9001` | Análisis estático — solo con `--profile analisis` |
| **API completa** | `8000` | **`http://localhost:8000/docs-todos` — un solo Swagger con los 8 contratos del sistema en un desplegable.** Es el punto por el que conviene empezar |
| ticket-service | `8001` | Swagger: `http://localhost:8001/docs` |
| almacen-service | `8002` | Swagger: `http://localhost:8002/docs` |
| diagnostico-service | `8004` | Swagger: `http://localhost:8004/docs` |
| facturacion-service | `8005` | Swagger: `http://localhost:8005/docs` |
| auditoria-service | `8006` | Swagger: `http://localhost:8006/docs` |
| notificacion-service | `8007` | Swagger: `http://localhost:8007/docs` |

> **Swagger de cada servicio (`/docs`)**: los 6 microservicios internos
> publican su puerto **solo para inspeccionar su Swagger** en la
> demo/sustentación. En un despliegue real esto NO debería estar abierto:
> el tráfico de negocio pasa **siempre por el Gateway** (`:8000`), que es el
> único que valida el JWT, aplica RBAC y la resiliencia. Golpear un servicio
> directo por su puerto se salta todo eso (ver `seguridad/OWASP_Top10.md`,
> hallazgo A05). Registrado como brecha en `documentacion/brechas_finales.md`.

## Variables necesarias

Ver `.env.example` (plantilla completa, sin secretos reales). Resumen de
lo obligatorio para arrancar:

| Variable | Para qué |
| :-- | :-- |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `DATABASE_URL` | Credenciales y cadena de conexión de PostgreSQL |
| `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS` / `RABBITMQ_URL` | Bus de eventos |
| `JWT_SECRET_KEY` | Debe ser **idéntica** en `api-gateway` y `auth-service`, o los tokens no validan |
| `CORS_ORIGINS` | Orígenes permitidos para el frontend |
| `GF_SECURITY_ADMIN_USER` / `GF_SECURITY_ADMIN_PASSWORD` | Login del panel de Grafana |
| `RATE_LIMIT_RPS` / `RATE_LIMIT_BURST` | *(opcional)* Rate limit del Gateway — solo se exportan para ampliarlo temporalmente en las pruebas de carga (Fase 5); si no se exportan, usa el default seguro (20/40) |

Sin `.env`, el `docker-compose.yml` falla al arrancar con un mensaje
explícito (`${VAR:?Falta VAR en .env}`) en vez de correr con valores vacíos
o inseguros.

## Flujo principal

1. **Recepción** registra un ticket (`POST /tickets`) — SOPORTE (equipo con
   falla) o VENTA directa. Un SOPORTE nace en `EN_COLA`.
2. **Técnico** ve la cola de **su sede** y **toma** un ticket: queda asignado
   solo a él (exclusivo por sede) y entra en su bandeja **"Mis Tickets"**
   (`EN_DIAGNOSTICO`). Diagnostica: si necesita un repuesto,
   `diagnostico-service` lo reserva en `almacen-service` (orquestación
   síncrona) y el ticket pasa a `DIAGNOSTICADO`. Las asignaciones las gestiona
   `diagnostico-service`, así que "Mis Tickets" y el "quién atiende qué" del
   admin funcionan aunque `ticket-service` esté caído (ver *Asignación de
   tickets* más abajo).
3. Se emite `ticket.listo`  **notificacion-service** avisa a Caja.
4. **Caja** cobra (`POST /facturas`, `facturacion-service`) y entrega
   (`ENTREGADO`).
5. Todo el trayecto queda trazado con un `X-Correlation-ID` único, auditado
   en `auditoria-service` (`GET /api/v1/auditoria/auditoria/eventos`) y en
   los logs estructurados de cada contenedor.

Roles: `ADMIN` (gestión), `CAJA`/`recepción` (registro y cobro), `TECNICO`
(diagnóstico), por sede (`PIURA`/`TALARA`) — inyectados por el Gateway
desde el JWT, nunca confiados del body de la petición.

## Asignación de tickets (¿quién atiende qué?)

El **técnico** ve la cola `EN_COLA` **de su sede** y **toma** un ticket. A
partir de ese momento el ticket queda asignado **solo a él**: otro técnico de
la misma sede que intente tomarlo recibe un `409` (exclusividad). Los tickets
tomados aparecen en la bandeja **"Mis Tickets"** del técnico, y el **admin**
ve en `/admin/asignaciones` todos los tickets tomados y **quién los atiende**.

**Quién lo gestiona (y por qué):** las asignaciones son propiedad del
`diagnostico-service` (tabla `asignaciones`, con la clave primaria `id_ticket`
que garantiza "un ticket = un técnico"), **no** del `ticket-service`. Así, la
bandeja "Mis Tickets" y la vista del admin siguen funcionando **aunque
`ticket-service` esté caído** — el trabajo del técnico no se detiene por una
caída del servicio de tickets. Al tomar, se avisa a `ticket-service`
(`EN_COLA  EN_DIAGNOSTICO`) en **segundo plano best-effort**: la respuesta es
instantánea y la asignación es autoritativa aunque ese aviso se pierda.

| Acción | Endpoint | Rol |
| :-- | :-- | :-- |
| Tomar un ticket | `POST /api/v1/diagnosticos/asignaciones/tomar` | TECNICO |
| Mis Tickets | `GET /api/v1/diagnosticos/asignaciones/mias` | TECNICO |
| Quién atiende qué | `GET /api/v1/diagnosticos/asignaciones/` | ADMIN |

Pruébalo: `docker pause ticket-service`, abre la pantalla de un técnico  la
cola avisa "no disponible" pero **"Mis Tickets" sigue cargando**; `docker
unpause ticket-service` para restaurar.

## Cero pérdida de escrituras: outbox transaccional del Gateway

Cuando el cliente hace una **escritura** (crear ticket, registrar diagnóstico,
cobrar, mover inventario) y el microservicio destino está **caído**, el
API Gateway **no pierde la petición**: la guarda en una tabla durable
(`gateway_outbox`) y responde `202 { "encolado": true }` en vez de un error.
Un worker de fondo la reintenta sola contra el servicio con la **misma
`Idempotency-Key`**; en cuanto el servicio vuelve, se entrega. **Nada se
pierde ni se duplica.**

Pruébalo: `docker pause ticket-service`, crea un ticket  `202 encolado`;
`docker unpause ticket-service`  el worker lo registra solo, una sola vez.
Ver `api_gateway/app/core/outbox.py`.

## Garantías (las emite y consulta Facturación)

La **garantía de 90 días** nace del **cobro**, no de la entrega: la emite
`facturacion-service` junto con el comprobante y se consulta desde ahí. Así la
Consulta de Garantías **sigue disponible aunque `ticket-service` esté caído**
(antes desaparecía). Al hacer **clic en una garantía** se abre el comprobante
que la respalda.

| Acción | Endpoint | Rol |
| :-- | :-- | :-- |
| Listado con vigencia | `GET /api/v1/facturas/garantias/` | CAJA · ADMIN |
| Buscar por DNI/RUC | `GET /api/v1/facturas/garantias/por-documento/{doc}` | CAJA · ADMIN |
| Comprobante de la garantía | `GET /api/v1/facturas/garantias/factura-de/{idTicket}` | CAJA · ADMIN |

Pruébalo: `docker pause ticket-service` -> la Consulta de Garantías del panel
sigue cargando y el comprobante también. Decisión y motivos: `ADR-0013`.

## Webhooks salientes

**Cómo se llama:** *Webhook de eventos de negocio* (webhook **saliente** —
el sistema es quien llama hacia afuera). Vive en `notificacion-service`.

**Qué hace, en una frase:** cuando ocurre un evento del flujo (se registra
un ticket, un equipo queda listo para cobro, o se ingresa un producto),
SHServices hace un **POST HTTP firmado** a los sistemas externos que se
suscribieron a ese evento — así un tercero (un CRM, un Slack, un ERP, otro
backend) se entera **en el momento**, sin tener que consultar la API una y
otra vez (*polling*).

Es distinto de las notificaciones internas: la notificación interna va a la
bandeja de un rol dentro de la app (ADMIN/TECNICO/CAJA); el webhook sale por
HTTP a **otro sistema, fuera de SHServices**. Ambos se disparan del mismo
evento de RabbitMQ.

**Dónde está el código:** `notificacion_service/` —
`app/core/webhooks.py` (firma + entrega + reintentos),
`app/api/webhooks.py` (suscripciones), `app/models/webhook.py` (tablas).

**Cómo funciona, paso a paso:**

1. **El tercero se suscribe** con su URL y el evento que le interesa
   (`ticket.creado`, `ticket.listo`, `producto.registrado` o `*` para todos):
   ```bash
   curl -X POST http://localhost:8000/api/v1/notificaciones/notificaciones/webhooks/suscripciones \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"url":"https://mi-sistema.com/hook","evento":"ticket.creado"}'
   ```
2. **Ocurre el evento.** Cuando el `notificacion-service` consume ese evento
   de RabbitMQ, además de crear la notificación interna, hace **POST** a cada
   URL suscrita con el payload del evento.
3. **El payload va firmado.** La cabecera `X-Firma` lleva un
   **HMAC-SHA256** del cuerpo con un secreto compartido (`WEBHOOK_SECRET`).
   El receptor recalcula la firma con ese mismo secreto: si coincide, el
   evento vino de verdad de nosotros y no fue alterado. También van
   `X-Evento` y `X-Trace-Id` (el `correlationId`, para que el receptor
   pueda correlacionar).
4. **Reintentos + bitácora.** Si la entrega falla, se reintenta hasta 3
   veces con backoff. Cada intento (ENTREGADO o FALLIDO, con el nº de
   intentos y el código HTTP) queda en la tabla `webhook_entregas`,
   consultable en
   `GET /api/v1/notificaciones/notificaciones/webhooks/entregas` — así un
   webhook que falla en silencio no es invisible.

**Cómo verificar la firma** (lado del receptor, Python):
```python
import hashlib, hmac
firma_esperada = hmac.new(WEBHOOK_SECRET.encode(), cuerpo_bytes, hashlib.sha256).hexdigest()
valida = hmac.compare_digest(request.headers["X-Firma"], firma_esperada)
```

Endpoints de gestión (todos bajo `/api/v1/notificaciones/notificaciones/webhooks/`):
`POST /suscripciones`, `GET /suscripciones`, `DELETE /suscripciones/{id}`,
`GET /entregas`.

## Tests unitarios (pytest)

Los mecanismos de resiliencia del Gateway son **Python puro** (sin BD ni red),
así que se prueban de forma aislada y en menos de 2 segundos:

```bash
python -m pip install pytest pytest-cov sqlalchemy      # una sola vez
python -m pytest tests/ -q                              # 26 tests
python -m pytest tests/ --cov=api_gateway/app/core --cov-report=xml   # + cobertura para SonarQube
```

| Archivo | Qué verifica |
| :-- | :-- |
| `tests/test_circuit_breaker.py` | Máquina de estados CLOSED  OPEN  HALF_OPEN  CLOSED: apertura por fallos consecutivos y por tasa de error, fail-fast, una sola sonda en HALF_OPEN, reapertura si la sonda falla, contador de aperturas |
| `tests/test_bulkhead_ratelimit.py` | Bulkhead: cupo, liberación y **aislamiento entre servicios** (saturar tickets no consume el cupo de almacén). Rate limit: ráfaga, reposición de tokens, tope de capacidad y `Retry-After` |
| `tests/test_backoff_outbox.py` | Backoff **3s / 5s / 8s** exigido por la S34, crecimiento posterior con tope de 30s, presencia de jitter y mensajes de "encolado" al usuario |

Cobertura: **100 %** en `resilience.py` y `bulkhead.py`, **96 %** en `ratelimit.py`.

## Cómo ejecutar las pruebas

Todo en Python puro (`pip install httpx`), corridas **desde la raíz del
repo** con el sistema arriba (`docker compose up -d`). Reportes en
`pruebas/resultados/` (texto + JSON, ignorados por git). Los runners
compartidos viven en `pruebas/lib/` (`comun.py`, `carga.py`,
`carga_nodos.py`, `rafaga_async.py`).

| # | Comando | Qué prueba | Duración |
| :-- | :-- | :-- | :-- |
| 1 | *(absorbida)* | La antigua "traza única" es ahora parte de la prueba 8 (pasos 10 y 12). Se fusionaron para no mantener dos pruebas que creaban el mismo ticket y acababan divergiendo | — |
| 2 | `python pruebas/02_carga_780.py` | **Línea base ~780 peticiones**: 2 nodos x bloques de 8, ventana 25 s. Misma metodología que 3/4/5, así las cuatro filas de la tabla se comparan entre sí | ~40 s |
| 3 | `python pruebas/03_carga_100k.py` | Nivel **100k**: **8.000 peticiones** contadas (4 nodos x bloques de 16). Medido: 99.2% de éxito, p95 1495 ms | ~3.5 min |
| 4 | `python pruebas/04_carga_500k.py` | Nivel **500k**: **20.000 peticiones** contadas (5 nodos x bloques de 18) | ~8.5 min |
| 5 | `python pruebas/05_carga_1M.py` | Nivel **1M**: **25.000 peticiones** contadas (6 nodos x bloques de 20) | ~10.5 min |
| 6 | `python pruebas/06_caos.py` | 6 fichas de falla controlada: servicio caído, latencia, cola saturada (bulkhead+shed), rate limit, evento duplicado y **degradación funcional** (cae ticket-service y la VENTA se completa igual) | ~1.5 min |
| 7 | `python pruebas/07_breaker_todos.py` | El circuit breaker abre para **los 7 servicios (auth incluido)**: tumba cada uno, exige 503 (no 500) y circuito OPEN, y verifica la recuperación automática | ~3 min |
| 8 | `python pruebas/08_flujo_completo.py` | El flujo de negocio **completo tocando los 8 servicios**: caja registra  técnico toma/diagnostica (reserva stock real)  caja cobra/entrega  admin agrega inventario  consultas de auditoría y notificaciones. Verifica que los 8 recibieron tráfico | ~15 s |
| 9 | `python pruebas/09_asignaciones.py` | **Asignación exclusiva de tickets** y su resiliencia: un técnico toma un ticket (queda solo para él), otro recibe 409, "Mis Tickets" y la vista de admin, y con **ticket-service pausado** "Mis Tickets" sigue funcionando. Incluye el diagnóstico duplicado  409 legible | ~20 s |
| 10 | `python pruebas/10_demo_breaker.py <servicio>` | **DEMO VISIBLE del circuit breaker** para un servicio (`almacen`, `tickets`, `diagnosticos`, `facturas`, `auditoria`, `notificaciones`): pausa el contenedor, le manda tráfico hasta abrir el circuito (CLOSEDOPEN con fail-fast), lo deja OPEN 15 s para verlo en Grafana, y al reanudar el servicio el circuito **se cierra solo** (sonda activa). Ideal para la sustentación | ~1.5 min |
| 11 | `python pruebas/11_caos_bajo_carga.py [--nivel 100k\|500k\|1M]` | **Caos BAJO CARGA sostenida**: lanza la carga real y va tumbando servicios **sin parar el tráfico**. Mide contención (cero 500), continuidad (% atendido) y recuperación, con línea de tiempo de los circuitos. Medido: 97.4% atendido y 0 errores 500 con 3 servicios cayendo | 3 / 6.5 / 12 min |
| 12 | `python pruebas/12_autorecuperacion.py [--nivel reposo\|100k\|500k\|1M] [--servicio X]` | **¿Cuánto tarda en curarse solo?** Mata el proceso (`os._exit(1)`) de 5 servicios y **no vuelve a tocar nada**: cronometra Docker  `/health`  circuito CLOSED. Con `--nivel` se cura **mientras atiende tráfico**, que es el número honesto. Medido: **6 s en reposo, 19 s bajo carga** | 2 / 4 / 6.5 / 8.5 min |
| 13 | `python pruebas/13_carga_100k_real.py` | **100.000 peticiones REALES**, contadas una a una — no es una etiqueta ni una extrapolación, es el contador. Imprime avance con % y minutos restantes para poder dejarla sola. Sirve además para ver si el throughput se degrada en una sesión larga | **~45 min** |
| k6 | `python pruebas_k6/correr.py --fase 100k\|500k\|1M` | **Carga con k6** (Go, dentro de la red Docker): el generador de Python topaba en ~105 rps y era ÉL el cuello de botella. Con k6: 166 rps y p95 de 284 ms contra 1.495 ms. Cada corrida escribe la fila completa de la tabla de registro de carga | según fase |
| 13 | `python pruebas/13_resiliencia_en_vivo.py [--demo 1\|2\|3\|4]` | **4 demos cortas para proyectar en la sustentación.** Cada una dice en consola qué servicio compromete, en qué panel de Grafana se ve, e imprime los **logs reales del Gateway** que lo prueban: sonda activa, timeout+retry, bulkhead y respawn de worker. Medido: el circuito se cierra **solo en 16 s** | ~4 min |
| 14 | `python pruebas/14_datos_demo.py [--tickets N]` | **Datos de demo.** Crea 3 tickets de soporte en PIURA y lleva el primero por el ciclo completo (diagnóstico con reserva de stock  cobro con garantía). Va por la API, no con INSERTs, así que respeta las reglas de negocio y publica sus eventos. Idempotente | ~15 s |
| k6-caos | `python pruebas_k6/caos.py --fase 100k\|500k\|1M` | **Caos bajo carga REAL**: k6 empujando ~200 rps mientras se tumban servicios con **Toxiproxy** (se deshabilita su proxy). Mide contención (cero 500), ausencia de cascada, y cuánto tarda cada circuito en cerrarse **solo** por la sonda activa. La conectividad la restaura la prueba; el circuito se recupera sin intervención | según fase |
| — | `python pruebas/generar_informe.py` | **Genera el informe completo** en `documentacion/informe_de_pruebas.md`: lee la última corrida de cada prueba y arma tabla de carga, caos, auto-recuperación y veredicto. Lo que no se haya corrido sale como *(sin corrida)*, no como cero | ~1 s |

### Pruebas de carga con k6

El generador de carga es **k6** (Go, sin GIL, corriendo dentro de la red
Docker). Sustituye a la carpeta `pruebas_reales/`, que se eliminó: usaba un
generador en Python que topaba en ~105 rps y **era él mismo el cuello de
botella**, así que medía al cliente y no al sistema. Se comprobó lanzando
generadores en paralelo (1  105 rps, 2  171, 4  257).

| Comando | Qué prueba |
| :--- | :--- |
| `python pruebas_k6/correr.py --fase humo` | Humo (2.000 peticiones), para comprobar que todo responde antes de una corrida larga |
| `python pruebas_k6/correr.py --fase 100k --vus 200` | Carga mixta de 100.000 peticiones |
| `python pruebas_k6/correr.py --fase 500k --vus 200` | Carga mixta de 500.000 peticiones |
| `python pruebas_k6/correr.py --fase 1M --vus 200` | Carga mixta de 1.000.000 de peticiones |

Cada corrida añade su fila a `documentacion/tabla_registro_carga_k6.md` y deja
el reporte completo en `pruebas_k6/resultados/`. **Ctrl+C** corta la corrida y
k6 emite igualmente el resumen de lo hecho hasta ese momento.

**Antes de una corrida larga:**
1. Parar SonarQube si está de fondo, para liberar CPU:
   `docker compose --profile analisis stop sonarqube`
2. Limpiar los datos acumulados, o las consultas de listados se sesgan:
   `python pruebas/limpiar_datos_carga.py --borrar`

**Todas las pruebas tocan todos los servicios.** La E2E (8) recorre el flujo
completo por los 8 servicios; las de carga con k6 reparten el tráfico entre
tickets, almacén, auditoría y notificaciones (rotan por sus endpoints GET),
no solo `tickets` — así el sistema completo se ejercita bajo presión. Los
503 que verás en servicios de bajo cupo (auditoría/notificaciones,
bulkhead=5) son el aislamiento por servicio funcionando, no fallas.

**Metodología de las pruebas 3-5 (nodos, bloques, ventana fija):**
`carga_nodos.py` simula varios **nodos** independientes — no un solo hilo,
no todo de golpe — que mandan **bloques** de N peticiones concurrentes,
con **backoff escalonado 3s  5s  8s + jitter** entre bloques que topan
con 429/503 (un bloque limpio baja el nivel a 0). Acotado a una **ventana
de tiempo fija** (10-15 min): a la tasa real medida del sistema (~85-90
rps, limitada por el Gateway de 1 worker) completar 500k/1M literalmente
tomaría 1.5-4 horas, así que la etiqueta 100k/500k/1M representa el
**nivel de carga ofrecida** (más nodos, bloques más grandes), no un conteo
a cumplir — se reporta el throughput real sostenido y, si no se alcanza la
etiqueta, se explica el cuello de botella con métricas (regla explícita de
la S34). Las pruebas 3-5 amplían el rate limit del Gateway temporalmente
(`RATE_LIMIT_RPS`/`RATE_LIMIT_BURST`) para medir el throughput real del
backend y lo restauran al terminar.

**Correr una prueba larga en segundo plano:**
```bash
python pruebas/04_carga_500k.py > pruebas/resultados/04_consola.log 2>&1 &
tail -f pruebas/resultados/04_consola.log
```
No correr dos niveles (3, 4 o 5) simultáneamente: compiten por el mismo
bulkhead de tickets (cupo=12) y confunden la medición de cada una.

**Corridas cortas de humo** (mismo mecanismo, menos volumen/tiempo):
```bash
NODOS=3 BLOQUE=10 DURACION=60 python pruebas/03_carga_100k.py
```

**Cómo leer los resultados:** HTTP 200 = atendida. 429 = rate limit
(backpressure). 503 = bulkhead lleno / shedding / circuito abierto. 504 =
timeout del presupuesto. Ninguno de estos tres es una falla: es el sistema
degradando con contrato (Fases 1-2, S34). `latencia p95/p99` viene del
runner (extremo a extremo); circuit state/retries/fallbacks/bulkhead se
leen de `GET /metrics` o del dashboard de Grafana.

**Resultados y evidencia formal:** el "Registro de carga" y la "Matriz de
revisión de resiliencia" (formato exacto de la S34) se llenan en
`documentacion/registro_de_carga.md` y
`documentacion/matriz_revision_resiliencia.md`; el detalle de cada ficha
de caos (hipótesis, métrica observada, evidencia) está en
`documentacion/fichas_falla_controlada.md`.

**Importante (Git Bash / MSYS en Windows):** cualquier `--ruta` o argumento
que empiece con "/" se lo pases a mano a un runner se lo va a convertir en
una ruta de Windows — los scripts ya pasan las rutas sin la barra inicial
y la reponen internamente, ya a salvo.

### Probar el circuit breaker tú mismo (y por qué a veces "no abre")

Si tumbas un servicio en Docker y ves que su circuito **no** abre en Grafana,
casi siempre es por una de estas tres razones — ninguna es un bug:

**1. El circuit breaker es "por demanda": solo abre si le llega tráfico.**
El breaker abre cuando observa **fallos reales**, y solo observa fallos de
un servicio si le están llegando peticiones a ese servicio mientras está
caído. Si tumbas `facturas` pero nadie está pidiendo facturas, su circuito
se queda en CLOSED — correctamente, porque no ha visto ningún fallo. Por eso
en tu pantalla "solo notificaciones" cambiaba: el frontend hace *polling*
continuo a `/notificaciones/mis-alertas`, así que ese es el único servicio
con tráfico constante. Para ver abrir el circuito de otro, hay que mandarle
peticiones mientras está caído:

```bash
# 1. token
TOKEN=$(curl -s -X POST http://localhost:8003/api/v1/auth/login \
  -H "Content-Type: application/json" -d '{"usuario":"admin","password":"admin123"}' \
 | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. tumba el servicio
docker stop almacen-service

# 3. MÁNDALE TRÁFICO (esto es lo que faltaba): 5 peticiones
for i in 1 2 3 4 5; do
  curl -s -o /dev/null -w "HTTP %{http_code}\n" \
    http://localhost:8000/api/v1/almacen/almacen/productos \
    -H "Authorization: Bearer $TOKEN"
done
# -> las primeras dan 503 y abren el circuito; las siguientes son fail-fast (<100ms)

# 4. míralo en /metrics (2 = OPEN) o en Grafana
curl -s http://localhost:8000/metrics | grep 'gateway_circuit_state{service="almacen"}'

# 5. restaura; el circuito se cierra SOLO (sonda activa), sin mandar mas trafico
docker start almacen-service
```

La prueba automatizada `python pruebas/07_breaker_todos.py` hace exactamente
esto para los 6 servicios de corrido. Y para **verlo bien en una sustentación**
(un servicio, paso a paso, dejando el circuito OPEN unos segundos para mirarlo
en Grafana y luego cerrándose solo), usa:

```bash
python pruebas/10_demo_breaker.py almacen     # o tickets, diagnosticos, facturas, auditoria, notificaciones
```

> **Ojo:** si pausas un contenedor y el circuito **no** abre, es porque no le
> estás mandando tráfico — el breaker solo abre cuando **ve fallos**. La prueba
> 10 se encarga de mandar el tráfico por ti.

**Recuperación automática (sonda activa).** El circuito ahora se **cierra
solo** cuando el servicio revive, **sin necesidad de que mandes más
peticiones**. Un *prober* de fondo en el Gateway (`bucle_sonda_breakers`)
recorre cada 5s los circuitos que no están CLOSED y, pasado el cooldown,
manda una sonda al `/health` del servicio; si responde, cierra el circuito.
Así, tras restaurar el servicio, el circuito vuelve a CLOSED en ~15-20s
(cooldown + sonda) aunque no haya tráfico de cliente. (Abrir el circuito sí
requiere tráfico real: solo se detecta un fallo si alguien llama al servicio
caído.)

### Auto-restart: por qué "pauso el contenedor y no se levanta solo"

`restart: always` (en los 9 contenedores) reinicia un servicio cuando su
**proceso muere solo** (crash real, OOM) o cuando el daemon/PC se reinicia.
**NO** actúa cuando **tú** paras el contenedor a mano — y esto incluye a los
tres:

| Comando | ¿Qué hace? | ¿`restart: always` lo revive? |
| :-- | :-- | :-- |
| `docker pause <c>` | Congela el proceso (sigue "corriendo") | No (no murió, está congelado)  `docker unpause` |
| `docker stop <c>` | Parada solicitada por el usuario | No (Docker respeta tu decisión)  `docker start` |
| `docker kill <c>` | Señal desde fuera; Docker la marca como parada del usuario | No  `docker start` |
| **Crash real del proceso** | El proceso sale solo (p. ej. `os._exit`) | **Sí, en ~2s** |

Por eso, cuando **pausas** un contenedor, "no se levanta solo": está
congelado, no caído.

### Tumbar un servicio unitario (uno por servicio)

Cada microservicio tiene un endpoint de caos `POST /_chaos/crash` que hace
que **su proceso muera de verdad**  `restart: always` lo revive solo en ~2s.
Así demuestras el auto-restart servicio por servicio.

> **PowerShell (Windows):** `curl` es un alias de `Invoke-WebRequest` y NO
> acepta `-X`/`-s`. Usa **`curl.exe`** (el curl real, ya viene en Windows 10+)
> o `Invoke-RestMethod`. Con `curl.exe` los comandos de abajo funcionan tal cual.

| Servicio | Puerto | Comando para tumbarlo (crash real  revive solo) |
| :-- | :-- | :-- |
| auth-service | 8003 | `curl.exe -X POST http://localhost:8003/_chaos/crash` |
| ticket-service | 8001 | `curl.exe -X POST http://localhost:8001/_chaos/crash` |
| almacen-service | 8002 | `curl.exe -X POST http://localhost:8002/_chaos/crash` |
| diagnostico-service | 8004 | `curl.exe -X POST http://localhost:8004/_chaos/crash` |
| facturacion-service | 8005 | `curl.exe -X POST http://localhost:8005/_chaos/crash` |
| auditoria-service | 8006 | `curl.exe -X POST http://localhost:8006/_chaos/crash` |
| notificacion-service | 8007 | `curl.exe -X POST http://localhost:8007/_chaos/crash` |
| api-gateway | 8000 | *(no aplica: gunicorn respawnea el worker; para tumbar el contenedor usa `docker restart api-gateway`)* |

**Cómo ejecutarlo y ver que revive solo** (ejemplo con ticket-service; cambia
el puerto y el nombre para otro servicio):

```powershell
# PowerShell (Windows) — OJO: curl.exe, no curl
curl.exe -X POST http://localhost:8001/_chaos/crash

# míralo caer y volver solo (restart: always) — se recupera en ~2s
for ($i=0; $i -lt 6; $i++) { Start-Sleep 2; docker ps -a --filter name=ticket-service --format '{{.Status}}' }
```

```bash
# Git Bash / Linux / Mac
curl -s -X POST http://localhost:8001/_chaos/crash
for i in $(seq 6); do sleep 2; docker ps -a --filter name=ticket-service --format '{{.Status}}'; done
```

Alternativa sin endpoint (para cualquier contenedor): `docker restart <servicio>`
lo baja y lo vuelve a subir. Y recuerda: con `docker pause`/`stop`/`kill` el
`restart: always` NO actúa (Docker lo trata como parada tuya) — levántalos con
`docker unpause` / `docker start`.

**2. `docker pause` y `docker stop` NO fallan igual** (ambos abren el
circuito, pero por caminos distintos — verificado en vivo):

| Comando | Qué le pasa a la conexión | Error que ve el Gateway | Velocidad en abrir |
| :-- | :-- | :-- | :-- |
| `docker stop` | El contenedor desaparece, el puerto deja de escuchar | `ConnectError` (rechazo instantáneo) -> **503** | Rápido (~ms por intento) |
| `docker pause` | El proceso se congela pero la red sigue viva: la conexión TCP se acepta y queda esperando una respuesta que no llega | `TimeoutException` -> **504** | Lento (~3-6s por intento, hay que esperar el timeout) |

Con `pause` verás primero un par de **504** (timeouts de 3s) antes de que el
circuito abra y pase a **503** fail-fast; con `stop` verás **503** desde el
primer intento. Los dos terminan con el circuito OPEN.

> **`tickets` es especial:** va a través de Toxiproxy. Al tumbar
> `ticket-service`, Toxiproxy sigue vivo y acepta la conexión para luego
> cerrarla -> `httpx.ReadError`. Esto rompía el breaker de tickets hasta la
> Fase 7 (daba 500 y no abría); ya está corregido (se captura toda la
> familia `httpx.TransportError`).

**3. `auth` nunca abre — y es correcto.** El login va **directo** a
`auth-service` (`:8003`), sin pasar por el Gateway (que de hecho bloquea
`/api/v1/auth/*` con 403). Como ninguna petición a `auth` atraviesa el
circuit breaker del Gateway, su circuito jamás se ejercita: siempre CLOSED.
Aparece en el panel por consistencia, pero es inerte por diseño.

### Ver el circuit breaker en los logs (no solo en Grafana)

El Gateway loguea **cada transición de estado** del circuito, para todos los
servicios, una línea por cambio (no una por request). En Dozzle
(`:9999`) o Loki, filtra por `operation="circuit_breaker"`:

```
CLOSED -> OPEN       Circuit breaker ABIERTO para 'almacen': demasiados fallos seguidos...
OPEN -> HALF_OPEN    ... cooldown vencido, se prueba UNA sonda para ver si 'almacen' se recupero.
HALF_OPEN -> CLOSED  Circuit breaker CERRADO para 'almacen': la sonda respondio OK, se recupero.
```

También se loguea cuándo se activa el **retry** (`operation="retry"`, con
`retryAttempt` y `backoffSeg`), el **timeout**, el **fallback**, el
**bulkhead** y el **rate limit** — así, ante cualquier problema, el log dice
qué mecanismo de resiliencia está compensando, no solo que "algo falló".

## Análisis estático con SonarQube

SonarQube va en el perfil `analisis`: **no arranca** con el sistema normal
(pesa ~1.4 GB y tarda ~2 min en levantar).

```bash
# 1. Levantar SonarQube (esperar ~2 min a que quede "UP")
docker compose --profile analisis up -d sonarqube
curl -s http://localhost:9001/api/system/status     # -> {"status":"UP"}

# 2. Generar un token (usuario admin; SONAR_PASS = tu contraseña de SonarQube)
TOKEN=$(curl -s -u admin:"$SONAR_PASS" -X POST \
  "http://localhost:9001/api/user_tokens/generate?name=analisis-$(date +%s)" \
 | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

# 3. Correr el escáner (el código se copia dentro del contenedor: ver nota)
docker rm -f sonar-scan 2>/dev/null
docker create --name sonar-scan --network shservices_yassir_shservices-net \
  -e SONAR_HOST_URL=http://sonarqube:9000 -e SONAR_TOKEN="$TOKEN" \
  sonarsource/sonar-scanner-cli
docker cp . sonar-scan:/usr/src/
docker start -a sonar-scan          # ~45 s
```

Resultados: **http://localhost:9001** (usuario `admin`)  proyecto
*SHServices V2*. Estado actual (2026-07-18): **0 bugs · Fiabilidad A ·
Mantenibilidad A**, 16 vulnerabilidades MINOR aceptadas (HTTP/AMQP interno
entre contenedores). El Quality Gate marca ERROR solo por condiciones de
*código nuevo* (cobertura 0 % — no hay tests unitarios instrumentados — y
duplicación estructural entre microservicios); justificación completa en
detalle y justificación en `seguridad/sonarqube_resultados.md`.

> **Nota:** el escáner copia el código con `docker cp` en vez de montarlo
> porque en esta máquina Docker Desktop falla al crear bind mounts nuevos
> (`mkdir /run/desktop/mnt/host/c: file exists`; se arregla reiniciando
> Docker Desktop). El servicio `sonar-scanner` del compose usa bind mount y
> sirve como alternativa cuando el file sharing funciona:
> `SONAR_TOKEN=$TOKEN docker compose --profile analisis run --rm sonar-scanner`

## Seguridad (OWASP Top 10)

Revisión completa del código en `seguridad/OWASP_Top10.md`. Lo más
relevante: las contraseñas **estaban en texto plano** en la base de datos y
ahora usan **bcrypt** (coste 12, salt por contraseña, comparación en tiempo
constante). Las cuentas existentes se migran solas en su primer login, sin
que el usuario note nada.

## Cómo ver logs y métricas

- **Logs en vivo (sin refrescar nada): Dozzle  http://localhost:9999**
  Streaming por WebSocket de los logs de todos los contenedores, en tiempo
  real, con filtro y búsqueda. Es lo que quieres para *mirar* el sistema
  mientras corre una prueba. (Equivalente en terminal:
  `docker compose logs -f api-gateway ticket-service`.)
- **Logs históricos y correlacionados: Grafana  Explore  Loki.** Loki es
  para *buscar* en el pasado (p. ej. filtrar por un `correlationId`
  concreto y ver el recorrido completo de una operación) y correlacionar
  con las métricas. También tiene tiempo real: botón **Live** arriba a la
  derecha en Explore. Dozzle y Loki se complementan, no compiten.
- **Logs estructurados** (JSON, un evento por línea —
  `service, correlationId, operation, event, result, durationMs`):
  `docker logs <servicio> --tail 50` para una mirada rápida a un servicio.
- **Métricas** (Prometheus, `GET http://localhost:8000/metrics` en texto
  plano): circuit breaker state, retries, fallbacks, bulkhead, rate limit,
  timeouts.
- **Dashboard de resiliencia**: `http://localhost:3000`  carpeta
  "SHServices"  *SHServices — Resiliencia (S34)* (provisionado
  automáticamente, no se arma a mano). Circuit breaker state en vivo,
  throughput/latencia/error rate, bulkhead, rate limit, queue depth y
  consumer lag de RabbitMQ.
- **Traza única de un ticket**: `python pruebas/08_flujo_completo.py` — crea
  un ticket con un `correlationId` conocido y confirma que aparece en
  auditoría, notificaciones y los logs de los 4 contenedores del flujo.

## Mejoras que se pueden implementar (lo que faltó del catálogo funcional)

El catálogo funcional describe capacidades por servicio más amplias que lo
implementado. Por tiempo se priorizó el flujo núcleo (ticket  diagnóstico 
almacén  facturación  notificación/auditoría), la asignación de tickets y la
resiliencia. Lo que quedaría como siguiente iteración, por servicio:

| Servicio | Pendiente del catálogo | Nota |
| :-- | :-- | :-- |
| **Tickets** | Estados intermedios completos (recibido, en reparación, validado, listo para entrega, cerrado) y control de tiempos/SLA por ticket | Hoy: `EN_COLA  EN_DIAGNOSTICO  DIAGNOSTICADO  ENTREGADO/RECHAZADO`. Falta el detalle de SLA. |
| **Diagnóstico** | Registro separado de acciones de reparación y de pruebas de validación/QA | Hoy se registra la falla + repuestos + precio en un solo diagnóstico. |
| **Almacén** | Flujo de **venta directa** (salida de productos por venta) e ingreso incremental de stock por lote | Hoy: reservar/confirmar/liberar/descontar para servicio técnico + alta de productos. |
| **Facturación** | **Anulación/corrección** controlada de comprobantes y consulta de comprobantes por cliente/orden | Hoy: emisión idempotente por `id_ticket` + garantías. |
| **Notificaciones** | Notificación **al cliente** (hoy solo interna por rol) y aviso explícito de "listo para entrega" / cierre | Hoy: alertas internas dirigidas por rol + webhooks salientes. |
| **Auditoría** | Consulta filtrada por usuario/sede/fecha desde la UI | Hoy: se persiste la traza y se lista; falta el buscador avanzado. |
| **Autenticación** | Estado de cuenta (activa/bloqueada/inactiva), registro de intentos de acceso e invalidación de sesión/token | Hoy: login JWT + alta de usuarios + RBAC por rol/sede. |

Ninguna de estas brechas afecta al flujo principal ni a la resiliencia
demostrada; son ampliaciones funcionales.

## Brechas conocidas

| Brecha | Detalle | Por qué se aceptó así |
| :-- | :-- | :-- |
| Gateway de 1 solo worker | Limita el throughput a ~85-90 rps (CPU de un núcleo saturado bajo carga) | El circuit breaker vive en memoria del proceso; con >1 worker cada uno tendría su propio breaker y el estado "parpadearía" entre CLOSED/OPEN según a qué worker cae cada request. Corregir de raíz requeriría mover el estado a Redis — evaluado y postergado por priorizar la corrección del mecanismo sobre el throughput bruto |
| Gateway como punto único de fallo | Si el Gateway completo cae, cae todo el tráfico de negocio | Sin redundancia/réplicas en esta entrega (un solo host de demo); mitigado parcialmente por `restart: always`, no por alta disponibilidad real |
| Fallas no cubiertas por las fichas de caos | Consumidor lento, base de datos lenta, error de contrato, fallo parcial explícito (ver `documentacion/fichas_falla_controlada.md`, tabla final) | Fuera del alcance de esta fase; el código de orquestación (`diagnostico-service`) ya maneja fallos parciales por repuesto individual, pero no se verificó como ficha de caos dedicada |
| `.env` con valores de demo | Los secretos de `.env` (no versionado) son los mismos usados durante todo el desarrollo, no rotados para producción real | Proyecto académico de sustentación, no un despliegue productivo |

## Más documentación

- `documentacion/` — changelog y contrato de cada servicio (formato S31),
  `runbook_general.md`, `registro_de_carga.md`, `matriz_revision_resiliencia.md`,
  `fichas_falla_controlada.md`, `evidencias_observabilidad.md` (checklist de
  la S34: log mínimo, dashboard mínimo, trazas), `brechas_finales.md` (tabla
  riesgo/acción/responsable para el dictamen).
- `seguridad/` — `OWASP_Top10.md` (revisión de las 10 categorías sobre este
  código) y `sonarqube_resultados.md`.
- `documentacion/adr/` — decisiones de arquitectura formalizadas (ADR-0008:
  Gateway de 1 solo worker; ADR-0009: estrategia de idempotencia; ADR-0010:
  carga por nodos/bloques).
- `documentacion/sla.md` — **SLA/SLO**: disponibilidad realista por criticidad,
  latencia medida, y el porqué del rate limiting y de cada límite.
- `matriz-resiliencia.md`, `catalogo-servicios.md`, `matriz-auditoria.md`,
  `runbook.md` — gobierno a nivel de sistema completo.
- `PLAN_INTEGRACION.md` — plan de integración final S34, fase por fase.

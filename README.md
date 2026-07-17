# SHServices V2

Sistema de soporte técnico multi-sede (Piura y Talara): recepción de
equipos, diagnóstico, gestión de repuestos, facturación y notificaciones
internas por rol, sobre una arquitectura de microservicios con resiliencia,
observabilidad y gobierno documentado (S26/S29/S31/S34).

> La documentación debe permitir **ejecutar**, no solo describir. Esta
> página responde exactamente lo que hace falta para levantar el sistema,
> operarlo y auditarlo.

## Cómo levantar el entorno

```bash
# 1. Variables de entorno (nunca se suben secretos reales al repo)
cp .env.example .env
# completar POSTGRES_PASSWORD, RABBITMQ_DEFAULT_PASS, JWT_SECRET_KEY,
# GF_SECURITY_ADMIN_PASSWORD con valores propios (o los de la demo, ver
# documentacion/*.md de cada servicio para las credenciales de prueba)

# 2. Levantar todo
docker compose up -d --build

# 3. Verificar
curl http://localhost:8000/health
```

Todos los servicios usan `restart: always` y health checks — si algo se
cae, se reinicia solo. El Gateway es el **único** punto de entrada público
para tráfico de negocio (`8000`); el resto de microservicios solo son
alcanzables dentro de la red Docker `shservices-net`.

## Servicios y puertos

| Servicio | Puerto host | Notas |
| :-- | :-- | :-- |
| **api-gateway** | `8000` | Único punto de entrada para tráfico de negocio (`/api/v1/...`) |
| auth-service | `8003` | Expuesto solo para generar tokens vía Swagger en demo/sustentación (`/docs`) — el Gateway bloquea `/api/v1/auth/*` |
| postgres-db | *(sin exponer)* | Solo alcanzable dentro de la red Docker |
| rabbitmq | `15672` (panel admin), `15692` (métricas Prometheus) | Usuario/clave en `.env` |
| toxiproxy | `8474` (API de control) | Inyecta fallas en `ticket-service` (Chaos Engineering) |
| prometheus | `9090` | Scrapea Gateway, ticket/auditoria/notificacion-service y RabbitMQ |
| grafana | `3000` | Dashboard de resiliencia provisionado automáticamente (Fase 4) |
| loki | *(sin exponer)* | Agregación de logs (búsqueda histórica), consultable desde Grafana |
| **dozzle** | `9999` | **Logs de todos los contenedores en vivo**, sin refrescar |
| sonarqube | `9001` | Análisis estático — solo con `--profile analisis` |
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
2. **Técnico** toma el ticket (`EN_DIAGNOSTICO`) y diagnostica: si necesita
   un repuesto, `diagnostico-service` lo reserva en `almacen-service`
   (orquestación síncrona) y el ticket pasa a `DIAGNOSTICADO`.
3. Se emite `ticket.listo` → **notificacion-service** avisa a Caja.
4. **Caja** cobra (`POST /facturas`, `facturacion-service`) y entrega
   (`ENTREGADO`).
5. Todo el trayecto queda trazado con un `X-Correlation-ID` único, auditado
   en `auditoria-service` (`GET /api/v1/auditoria/auditoria/eventos`) y en
   los logs estructurados de cada contenedor.

Roles: `ADMIN` (gestión), `CAJA`/`recepción` (registro y cobro), `TECNICO`
(diagnóstico), por sede (`PIURA`/`TALARA`) — inyectados por el Gateway
desde el JWT, nunca confiados del body de la petición.

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

## Cómo ejecutar las pruebas

Todo en Python puro (`pip install httpx`), corridas **desde la raíz del
repo** con el sistema arriba (`docker compose up -d`). Reportes en
`pruebas/resultados/` (texto + JSON, ignorados por git). Los runners
compartidos viven en `pruebas/lib/` (`comun.py`, `carga.py`,
`carga_nodos.py`, `rafaga_async.py`).

| # | Comando | Qué prueba | Duración |
| :-- | :-- | :-- | :-- |
| 1 | `python pruebas/01_traza_unica.py` | Una operación completa trazada de inicio a fin: auditoría + notificaciones + logs estructurados de 4 contenedores con UN correlationId | ~10 s |
| 2 | `python pruebas/02_carga_780.py` | 780 peticiones a la vez con límites normales: rate limit (429) y bulkhead (503) rechazando de forma controlada | ~5 s |
| 3 | `python pruebas/03_carga_100k.py` | Nivel **100k**: 6 nodos x bloques de 40, ventana de 10 min | 10 min |
| 4 | `python pruebas/04_carga_500k.py` | Nivel **500k**: 10 nodos x bloques de 80, ventana de 15 min | 15 min |
| 5 | `python pruebas/05_carga_1M.py` | Nivel **1M**: 15 nodos x bloques de 120, ventana de 15 min | 15 min |
| 6 | `python pruebas/06_caos.py` | 5 fichas de falla controlada: servicio caído, latencia, cola saturada (bulkhead+shed), rate limit, evento duplicado | ~1 min |
| 7 | `python pruebas/07_breaker_todos.py` | El circuit breaker abre para **los 6 servicios**: tumba cada uno, exige 503 (no 500) y circuito OPEN, y verifica la recuperación automática | ~3 min |

**Metodología de las pruebas 3-5 (nodos, bloques, ventana fija):**
`carga_nodos.py` simula varios **nodos** independientes — no un solo hilo,
no todo de golpe — que mandan **bloques** de N peticiones concurrentes,
con **backoff escalonado 3s → 5s → 8s + jitter** entre bloques que topan
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

# 5. restaura; tras el cooldown (15s) el circuito se cierra solo con una sonda
docker start almacen-service
```

La prueba automatizada `python pruebas/07_breaker_todos.py` hace exactamente
esto para los 6 servicios de corrido.

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

# 2. Generar un token de análisis (admin/admin)
TOKEN=$(curl -s -u admin:admin -X POST \
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

Resultados: **http://localhost:9001** (`admin` / `admin`) → proyecto
*SHServices V2*. Estado actual: **0 bugs, Quality Gate OK**, 15
vulnerabilidades MINOR aceptadas (HTTP/AMQP interno entre contenedores) —
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

- **Logs en vivo (sin refrescar nada): Dozzle → http://localhost:9999**
  Streaming por WebSocket de los logs de todos los contenedores, en tiempo
  real, con filtro y búsqueda. Es lo que quieres para *mirar* el sistema
  mientras corre una prueba. (Equivalente en terminal:
  `docker compose logs -f api-gateway ticket-service`.)
- **Logs históricos y correlacionados: Grafana → Explore → Loki.** Loki es
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
- **Dashboard de resiliencia**: `http://localhost:3000` → carpeta
  "SHServices" → *SHServices — Resiliencia (S34)* (provisionado
  automáticamente, no se arma a mano). Circuit breaker state en vivo,
  throughput/latencia/error rate, bulkhead, rate limit, queue depth y
  consumer lag de RabbitMQ.
- **Traza única de un ticket**: `python pruebas/01_traza_unica.py` — crea
  un ticket con un `correlationId` conocido y confirma que aparece en
  auditoría, notificaciones y los logs de los 4 contenedores del flujo.

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
- `documentacion/adr/` — decisiones de arquitectura formalizadas (ADR-0001:
  Gateway de 1 solo worker; ADR-0002: estrategia de idempotencia; ADR-0003:
  carga por nodos/bloques).
- `matriz-resiliencia.md`, `catalogo-servicios.md`, `matriz-auditoria.md`,
  `runbook.md` — gobierno a nivel de sistema completo.
- `PLAN_INTEGRACION.md` — plan de integración final S34, fase por fase.

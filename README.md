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
| loki | *(sin exponer)* | Agregación de logs, consultable desde Grafana |
| ticket-service, almacen-service, diagnostico-service, facturacion-service, auditoria-service, notificacion-service | *(sin exponer)* | Solo vía Gateway (`/api/v1/<servicio>/...`) |

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

## Cómo ver logs y métricas

- **Logs estructurados** (JSON, un evento por línea —
  `service, correlationId, operation, event, result, durationMs`):
  `docker logs <servicio> --tail 50`, o agregados en **Grafana → Explore →
  Loki** filtrando por `correlationId` para seguir una operación completa
  a través de todos los servicios que tocó.
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
  `fichas_falla_controlada.md`, `brechas_finales.md` (tabla riesgo/acción/
  responsable para el dictamen).
- `documentacion/adr/` — decisiones de arquitectura formalizadas (ADR-0001:
  Gateway de 1 solo worker; ADR-0002: estrategia de idempotencia; ADR-0003:
  carga por nodos/bloques).
- `matriz-resiliencia.md`, `catalogo-servicios.md`, `matriz-auditoria.md`,
  `runbook.md` — gobierno a nivel de sistema completo.
- `PLAN_INTEGRACION.md` — plan de integración final S34, fase por fase.

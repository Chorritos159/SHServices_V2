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

## Prueba de resiliencia

```bash
bash pruebas/06_caos.sh
```

Ejecuta 6 fichas de falla controlada con el sistema **operando**: servicio
caído (`docker stop almacen-service`), latencia inyectada (Toxiproxy),
cola saturada (bulkhead + shedding), backpressure (rate limit 429) y evento
duplicado (idempotencia) — ~1 minuto, con veredicto explícito al final.
Detalle de cada ficha (hipótesis, métrica observada, evidencia) en
`documentacion/fichas_falla_controlada.md`. El resto de la suite
(`pruebas/README.md`) cubre carga progresiva (100k/500k/1M) y trazabilidad
de punta a punta.

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
- **Traza única de un ticket**: `bash pruebas/01_traza_unica.sh` — crea un
  ticket con un `correlationId` conocido y confirma que aparece en
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
  `fichas_falla_controlada.md`.
- `matriz-resiliencia.md`, `catalogo-servicios.md`, `matriz-auditoria.md`,
  `runbook.md` — gobierno a nivel de sistema completo.
- `PLAN_INTEGRACION.md` — plan de integración final S34, fase por fase.
- `pruebas/README.md` — cómo correr toda la suite de pruebas.

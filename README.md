# SHServices V2

Sistema de Help Desk + POS basado en microservicios (FastAPI + PostgreSQL + RabbitMQ), con
API Gateway como único punto de entrada, resiliencia (Circuit Breaker + Toxiproxy) y
observabilidad completa (Prometheus + Grafana + Loki/Promtail).

## Cómo levantar el entorno
```bash
docker compose up -d --build
```
Espera ~20-30s a que todos los contenedores queden `healthy` (`docker compose ps`).

Frontend web (aparte, no está en el compose):
```bash
cd frontend && npm install && npm run dev   # http://localhost:3001
```

## Servicios y puertos

| Servicio | Puerto host | Notas |
| :--- | :--- | :--- |
| **api_gateway** | `:8000` | Único punto de entrada público de la API |
| **auth_service** | `:8003` | Expuesto aparte porque el Gateway **bloquea** `/api/v1/auth/*`; login va directo aquí |
| ticket_service | interno | Detrás de Toxiproxy (`:8666` interno) para pruebas de caos |
| almacen_service, diagnostico_service, facturacion_service, auditoria_service, notificacion_service | internos | Solo alcanzables vía el Gateway |
| PostgreSQL | interno (5432) | Una base compartida `shservices_db` |
| RabbitMQ | `:15672` (Management UI, guest/guest) | AMQP interno en `:5672` |
| Toxiproxy | `:8474` (API de control) | Inyección de fallos hacia `ticket_service` |
| **Prometheus** | `:9090` | Scrapea los 8 microservicios FastAPI |
| **Grafana** | `:3000` (admin/admin) | Dashboards provisionados automáticamente |
| Loki / Promtail | internos | Logs centralizados de todos los contenedores |

## Variables necesarias
Ver `.env.example` (plantilla comentada por microservicio). Las variables reales viven en
`docker-compose.yml`; `.env.example` es la referencia para clonar el proyecto o desplegarlo aparte.

## Flujo principal del negocio
1. **Login**: `POST http://localhost:8003/api/v1/auth/login` → JWT con `{sub, rol, sede}`.
2. **CAJA crea ticket**: `POST /api/v1/tickets/tickets/` (vía Gateway, con Bearer). `sede`/`usuario` los
   inyecta el Gateway desde el JWT — no van en el body.
3. **TECNICO diagnostica**: `POST /api/v1/diagnosticos/diagnosticos/` (reserva repuestos en almacén) +
   `POST /api/v1/tickets/tickets/{id}/diagnosticar` (transición de estado → DIAGNOSTICADO, emite
   `TicketListo.v1` para notificar a CAJA).
4. **CAJA entrega**: `POST /api/v1/tickets/tickets/{id}/entregar` (confirma el stock reservado y genera
   la garantía de 90 días) + `POST /api/v1/facturas/facturas/` (emite el comprobante).
5. **auditoria_service** y **notificacion_service** escuchan pasivamente en RabbitMQ (trazabilidad y
   alertas por rol) sin bloquear el flujo síncrono.

## 🛡️ Resiliencia: dónde vive en el código

| Patrón | Archivo · función | Qué hace |
| :--- | :--- | :--- |
| **Circuit Breaker** | [`api_gateway/app/main.py`](api_gateway/app/main.py) · `gateway_router()` | `try/except` sobre `httpx.ConnectError` (→503) y `httpx.TimeoutException` (→504, timeout de 5s). Reactivo por-request, no una máquina de estados con *half-open*. |
| **Métrica del breaker** | `api_gateway/app/main.py` · contador `CIRCUIT_BREAKER` (Prometheus `Counter`) | `gateway_circuit_breaker_total{service, motivo}` — incrementa en cada corte. `motivo=conexion` (503) o `timeout` (504). Multiproceso (`PROMETHEUS_MULTIPROC_DIR`) porque el Gateway corre con 4 workers gunicorn. |
| **Chaos proxy** | [`toxiproxy/toxiproxy.json`](toxiproxy/toxiproxy.json) + `docker-compose.yml` (servicio `toxiproxy`) | El tráfico Gateway→`ticket-service` pasa por Toxiproxy (`ticket_proxy`, control en `:8474`) para inyectar latencia o cortes. |
| **Consumidor resiliente** | [`auditoria_service/app/core/consumer.py`](auditoria_service/app/core/consumer.py) y [`notificacion_service/app/core/consumer.py`](notificacion_service/app/core/consumer.py) | Bucle `while True: try/except: sleep(5)` alrededor de `connect_robust` — sobrevive a que RabbitMQ no esté listo al arrancar. |
| **Reconexión a BD** | Cada `app/core/database.py` de los 8 servicios | `pool_pre_ping=True` + `pool_recycle=280` en el engine de SQLAlchemy. |
| **Health checks profundos** | Cada `app/api/health.py` | `GET /health` valida `SELECT 1` contra PostgreSQL, no solo "vivo" (`{"status","service","version","dependencies":{"database"}}`). |
| **Migraciones no destructivas** | Cada `app/main.py` (bloque `with engine.begin() as conn: ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) | Evita perder datos al agregar columnas nuevas entre versiones. |
| **Concurrencia en stock** | [`almacen_service/app/api/almacen.py`](almacen_service/app/api/almacen.py) · `.with_for_update()` | Bloqueo pesimista al reservar/confirmar/liberar/descontar stock (evita oversell). |
| **RBAC en profundidad** | [`api_gateway/app/main.py`](api_gateway/app/main.py) (`METODOS_SOLO_ADMIN`) + cada microservicio valida `X-User-Rol` | Defensa en dos capas: el Gateway y el propio servicio. |

## 🧪 Pruebas (carpeta `/pruebas`)

No hay tests unitarios (pytest); la validación es **funcional y de resiliencia**, contra el stack
real levantado. Requiere `pip install aiohttp requests` (fuera de los venvs de cada servicio).

> ⚠️ **¿Se necesita k6? No.** Los scripts `02/03/04` ya cubren carga concurrente y distribuida con
> `asyncio` + `aiohttp` (70 / 500k / 1M peticiones simuladas desde varios "nodos" con
> `multiprocessing`). k6 sería una herramienta redundante para lo que ya prueban estos scripts;
> solo tendría sentido si quisieras reportes HTML/percentiles nativos de k6, pero Grafana ya te da
> eso vía Prometheus mientras corren.

| Script | Qué hace | Cuándo usarlo |
| :--- | :--- | :--- |
| `01_flujo_e2e.py` | Recorre el flujo real completo: login → crear ticket → ingresar stock → diagnosticar → transición → entregar (genera garantía) → facturar. | Smoke test tras cualquier cambio de backend. |
| `02_carga_70_req.py` | 70 tickets VENTA concurrentes. | Verificar que el pool de conexiones aguanta ráfagas pequeñas. |
| `03_carga_500k_nodos.py` | 500,000 peticiones desde 5 procesos (`multiprocessing`), en bloques de 5000. | Prueba de carga sostenida (tarda varios minutos). |
| `04_carga_1m_nodos.py` | 1,000,000 de peticiones desde 10 procesos, en bloques de 10000. | Estrés extremo — usar en máquina dedicada. |
| `05_chaos_engineering.py` | Carga constante + apaga/enciende `almacen-service`, `ticket-service`, `facturacion-service`, `diagnostico-service` al azar (5 ciclos) usando los **nombres reales de contenedor** (`docker-compose.yml: container_name`). | Demostrar el Circuit Breaker EN VIVO. |

**Cómo correrlas** (con el stack arriba):
```bash
python pruebas/01_flujo_e2e.py
python pruebas/02_carga_70_req.py
python pruebas/03_carga_500k_nodos.py     # pesado
python pruebas/04_carga_1m_nodos.py       # muy pesado
python pruebas/05_chaos_engineering.py    # abre Grafana antes de correrlo
```

**Mientras corre `05_chaos_engineering.py`**, abre `http://localhost:3000` → dashboard
**"SHServices · Resiliencia"** y observa en vivo:
- **"Circuit Breaker · estado por servicio (30s)"** → pasa de `CERRADO` (verde) a `ABIERTO` (rojo)
  para el servicio que el script acaba de detener.
- **"Circuit Breaker por motivo"** → aparecen barras de `conexion` (503) mientras el contenedor está caído.
- **"Peticiones por status"** y **"Latencia p50/p95/p99"** reaccionan a la caída y a la recuperación.

También existe [`pruebas_resiliencia.py`](pruebas_resiliencia.py) (raíz del proyecto): una prueba
determinística vía Toxiproxy (sin depender de azar) que valida los 5 casos del Circuit Breaker
(sano → timeout/504 → recuperado → caído/503 → restaurado) y termina con un resumen PASS/FAIL.
```bash
python pruebas_resiliencia.py
```

## 📊 Cómo ver logs y métricas por Grafana

1. Entra a **http://localhost:3000** (usuario `admin`, contraseña `admin`).
2. Los datasources **Prometheus** y **Loki** ya están provisionados (no hay que configurarlos).
3. Dashboards → carpeta **SHServices** → **"SHServices · Resiliencia"** (8-9 paneles: cortes del
   breaker, disponibilidad, latencia, error rate, estado por servicio).

**Ver logs de un servicio específico** (Explore → datasource **Loki**):
```logql
{container="ticket-service"}
```

**Seguir una traza completa entre microservicios** (usa el `X-Correlation-ID` que devuelve el
Gateway en cada respuesta, o el `trace_id` de un error 503/504):
```logql
{stack="shservices"} | json | trace_id = "<PEGA_AQUI_EL_ID>"
```

**Ver solo errores/warnings de todo el stack**:
```logql
{stack="shservices"} | json | level =~ "ERROR|WARN"
```

**Alternativa por CLI** (sin Grafana): `docker compose logs -f ticket-service`.

## 🧨 Chaos Engineering manual con Toxiproxy

```bash
# Latencia de 8s (dispara 504 · Circuit Breaker por timeout)
curl -X POST http://localhost:8474/proxies/ticket_proxy/toxics \
  -d '{"name":"lat","type":"latency","attributes":{"latency":8000}}'

# Simular caída total (dispara 503 · Circuit Breaker por conexión)
curl -X POST http://localhost:8474/proxies/ticket_proxy -d '{"enabled":false}'

# Restaurar
curl -X DELETE http://localhost:8474/proxies/ticket_proxy/toxics/lat
curl -X POST   http://localhost:8474/proxies/ticket_proxy -d '{"enabled":true}'
```

## Documentación adicional
- [`documentacion/catalogo.md`](documentacion/catalogo.md) — ficha de catálogo por servicio (owner, criticidad, contratos, eventos, dependencias).
- [`documentacion/observabilidad_resiliencia.md`](documentacion/observabilidad_resiliencia.md) — guía extendida del dashboard y la traza.
- [`catalogo-servicios.md`](catalogo-servicios.md), [`matriz-resiliencia.md`](matriz-resiliencia.md), [`matriz-auditoria.md`](matriz-auditoria.md), [`runbook.md`](runbook.md) — gobernanza documental (gate G8).
- `CHANGELOG.md` en la raíz de cada microservicio — historial de versiones (Conventional Commits).
- `generar_doc.py` — genera `Documentacion_Integrador2.docx` a partir de los `.md` anteriores.

## Brechas conocidas
- **Single Point of Failure**: PostgreSQL no está replicado (sin Read-Replica ni failover automático).
- **Gateway sin réplicas**: una sola instancia (con 4 workers gunicorn internos); podría ser cuello de botella bajo ataque.
- **Circuit Breaker reactivo, no stateful**: corta por request tras 5s de timeout, pero no mantiene
  un estado *half-open* explícito ni un contador de fallos consecutivos compartido (ej. en Redis)
  para abrir el circuito de forma anticipada antes de que lleguen más requests fallidos.

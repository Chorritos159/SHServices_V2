# Catálogo de Servicios — SHServices V2

> Gate **G8 · FF-DEP-08** · Arquitectura de microservicios (FastAPI + PostgreSQL + RabbitMQ)
> Última actualización: 2026-07-16 (Fase 6 del plan de integración S34)

## 1. Visión general

Sistema de gestión de servicio técnico (recepción → diagnóstico → facturación → notificación)
construido sobre 7 microservicios de negocio FastAPI + el API Gateway, orquestados con Docker
Compose. El **API Gateway** es el único punto de entrada público, el único validador de
identidad (JWT), y desde la Fase 1-2 de la S34 también el punto donde vive **toda la
resiliencia del sistema**: circuit breaker, timeouts, retry+backoff+jitter, bulkhead, rate
limiting, shedding e idempotencia (ver §7 y `matriz-resiliencia.md`). Los microservicios
internos **no** están expuestos al host y confían en las cabeceras de identidad (`X-User-*`)
que el Gateway inyecta.

## 2. Roles e identidad

El `auth-service` emite un JWT (HS256, expiración 2 h) con la forma:

```json
{ "sub": "caja01", "rol": "CAJA", "sede": "PIURA", "exp": 1784140898 }
```

| Usuario     | Contraseña   | Rol       | Sede   | Acceso                                  |
|-------------|--------------|-----------|--------|-----------------------------------------|
| `admin`     | `admin123`   | `ADMIN`   | LIMA   | Inventario, Auditoría                   |
| `caja01`    | `caja123`    | `CAJA`    | PIURA  | Registro de Tickets, Facturación        |
| `tecnico01` | `tecnico123` | `TECNICO` | PIURA  | Diagnóstico Técnico                     |

## 3. Catálogo de microservicios

| Servicio | Contenedor | Puerto host | Responsabilidad | PostgreSQL | RabbitMQ |
|---|---|---|---|:---:|:---:|
| **API Gateway** | `api-gateway` | `8000→80` | Único ingreso público; valida JWT, inyecta `X-User-*` y `X-Correlation-ID`, RBAC (DELETE=ADMIN), Circuit Breaker | — | — |
| **Auth** | `auth-service` | `8003→80` | Emite JWT con `rol` + `sede` | — | — |
| **Tickets** | `ticket-service` | interno (vía Toxiproxy) | Alta de tickets, bandeja de pendientes, cambio de estado | ✔ | Publica `ticket.creado` |
| **Almacén** | `almacen-service` | interno | Inventario: listar, ingresar (código autogenerado), reservar stock | ✔ | — |
| **Diagnóstico** | `diagnostico-service` | interno | Diagnóstico técnico con precio + repuestos; reserva stock en Almacén | ✔ | Publica `ticket.diagnosticado` |
| **Facturación** | `facturacion-service` | interno | Emisión de comprobantes; idempotente por `id_ticket` (Fase 3) | ✔ | Publica `ticket.facturado` |
| **Auditoría** | `auditoria-service` | interno | Consume `ticket.*` y **persiste la traza en PostgreSQL**; idempotente por `(trace_id, evento)` (Fase 3) | ✔ | Consume `ticket.*` |
| **Notificaciones** | `notificacion-service` | interno | Alertas internas dirigidas por rol (ADMIN/TECNICO/CAJA); idempotente por `(trace_id, evento, rol_destino)` (Fase 3) | ✔ | Consume `ticket.creado`, `ticket.listo`, `producto.registrado` |

### Infraestructura de soporte

| Componente | Contenedor | Puerto host | Función |
|---|---|---|---|
| PostgreSQL | `postgres-db` | interno | Persistencia (una BD compartida `shservices_db`) |
| RabbitMQ | `rabbitmq` | `15672` (panel), `15692` (métricas Prometheus, `/metrics/per-object`) | Bus de eventos (exchange `tickets.eventos`, tipo topic) |
| Toxiproxy | `toxiproxy` | `8474` (control) | Inyección de fallos hacia `ticket-service` (Chaos Engineering) |
| Prometheus | `prometheus` | `9090` | Scrape de métricas: Gateway, ticket/auditoria/notificacion-service, RabbitMQ |
| Grafana | `grafana` | `3000` | Dashboard de resiliencia provisionado por archivo (Fase 4): circuit state, retry/fallback, bulkhead, rate limit, queue depth, consumer lag |
| Loki + Promtail | `loki`, `promtail` | interno | Agregación de logs estructurados, consultable desde Grafana |
| Frontend (Next.js) | (local) | `3001` | Cliente web (BFF + cookies HttpOnly) |

## 4. Endpoints públicos (vía Gateway `:8000`)

> Convención del Gateway: `/api/v1/{service}/{path}`. Como cada router interno está montado en
> `/api/v1/{service}/...`, la ruta pública lleva el segmento **duplicado**.

| Método | Ruta pública | Rol mínimo | Servicio destino |
|---|---|---|---|
| POST | `/api/v1/auth/login` **(directo a `:8003`)** | — | Auth (el Gateway bloquea `/auth`) |
| POST | `/api/v1/tickets/tickets/` | CAJA | Crear ticket (sede desde el token) |
| GET | `/api/v1/tickets/tickets/pendientes` | TECNICO | Bandeja EN_COLA |
| PATCH | `/api/v1/tickets/tickets/{id}` | TECNICO | Cambiar estado |
| GET/POST | `/api/v1/almacen/almacen/productos` | ADMIN | Listar / ingresar producto |
| POST | `/api/v1/almacen/almacen/reservar` | (interno) | Reservar stock |
| POST | `/api/v1/diagnosticos/diagnosticos/` | TECNICO | Registrar diagnóstico |
| POST | `/api/v1/facturas/facturas/` | CAJA | Emitir comprobante |
| GET | `/api/v1/auditoria/auditoria/eventos` | ADMIN | Traza de auditoría |
| GET | `/api/v1/notificaciones/notificaciones/mis-alertas` | cualquier rol autenticado | Bandeja de alertas no leídas (filtra por el rol del token) |
| POST | `/api/v1/notificaciones/notificaciones/marcar-leidas` | cualquier rol autenticado | Marca como leídas las alertas del rol |

## 5. Contrato de Health Check (FF-DEP-02)

Todos los servicios con base de datos exponen `GET /health` con validación real de PostgreSQL:

```json
{ "status": "UP", "service": "ticket-service", "version": "1.0.0", "dependencies": { "database": "UP" } }
```

Si la BD no responde: `status: "DEGRADED"`, `dependencies.database: "DOWN"` (el endpoint sigue devolviendo 200 para no tumbar el contenedor).

## 6. Flujo de negocio

1. **CAJA** registra el ticket (`SOPORTE` → `EN_COLA`, `VENTA` → `VENTA_REGISTRADA`) → **TECNICO** recibe una alerta.
2. **TECNICO** toma un ticket `EN_COLA`, registra diagnóstico (precio + repuestos), descuenta stock; el ticket pasa a `DIAGNOSTICADO` → **CAJA** recibe una alerta de que ya puede cobrar.
3. **CAJA** emite la factura del ticket.
4. **ADMIN** gestiona inventario y audita toda la traza de eventos.

## 7. Resiliencia (S34, Fases 1-5)

Todos los mecanismos de tolerancia a fallos viven en el **API Gateway**
(único punto de entrada, único lugar donde tiene sentido protegerlos a
todos de una vez). Detalle completo, verificación en vivo y métricas en
`matriz-resiliencia.md`; resumen:

| Mecanismo | Qué hace |
|---|---|
| Circuit breaker (CLOSED/OPEN/HALF_OPEN) | Fail-fast ante un servicio caído o lento, por servicio destino |
| Timeout + retry + backoff/jitter | Corta esperas; reintenta solo lo seguro (lecturas, o cualquier método si el request nunca llegó) |
| Bulkhead + shedding | Aísla la capacidad de cada servicio; descarta tráfico de baja prioridad antes de saturar del todo |
| Rate limiting global | Protege al Gateway mismo de una ráfaga, sin importar el destino |
| Idempotencia | `Idempotency-Key` (tickets) / clave natural (facturas) / índice único (consumidores RabbitMQ) |
| Logs estructurados S34 | `service, correlationId, operation, event, result, durationMs` en los 9 servicios |
| Dashboard de resiliencia | Grafana, provisionado por archivo — circuit state, retry/fallback, bulkhead, rate limit, queue depth, consumer lag |
| Pruebas de carga y caos | `pruebas/` (Python puro) — 6 pruebas, ver README raíz §"Cómo ejecutar las pruebas" |

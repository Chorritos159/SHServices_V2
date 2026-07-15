# Catálogo de Servicios — SHServices V2

> Gate **G8 · FF-DEP-08** · Arquitectura de microservicios (FastAPI + PostgreSQL + RabbitMQ)
> Última actualización: 2026-07-15

## 1. Visión general

Sistema de gestión de servicio técnico (recepción → diagnóstico → facturación) construido
sobre 7 microservicios FastAPI, orquestados con Docker Compose. El **API Gateway** es el único
punto de entrada público y el único validador de identidad (JWT). Los microservicios internos
**no** están expuestos al host y confían en las cabeceras de identidad (`X-User-*`) que el
Gateway inyecta.

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
| **Facturación** | `facturacion-service` | interno | Emisión de comprobantes | ✔ | Publica `ticket.facturado` |
| **Auditoría** | `auditoria-service` | interno | Consume `ticket.*` y **persiste la traza en PostgreSQL** | ✔ | Consume `ticket.*` |

### Infraestructura de soporte

| Componente | Contenedor | Puerto host | Función |
|---|---|---|---|
| PostgreSQL | `postgres-db` | interno | Persistencia (una BD compartida `shservices_db`) |
| RabbitMQ | `rabbitmq` | `15672` (panel) | Bus de eventos (exchange `tickets.eventos`, tipo topic) |
| Toxiproxy | `toxiproxy` | `8474` (control) | Inyección de fallos hacia `ticket-service` (Chaos Engineering) |
| Prometheus | `prometheus` | `9090` | Scrape de métricas |
| Grafana | `grafana` | `3000` | Dashboards de observabilidad |
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

## 5. Contrato de Health Check (FF-DEP-02)

Todos los servicios con base de datos exponen `GET /health` con validación real de PostgreSQL:

```json
{ "status": "UP", "service": "ticket-service", "version": "1.0.0", "dependencies": { "database": "UP" } }
```

Si la BD no responde: `status: "DEGRADED"`, `dependencies.database: "DOWN"` (el endpoint sigue devolviendo 200 para no tumbar el contenedor).

## 6. Flujo de negocio

1. **CAJA** registra el ticket (`SOPORTE` → `EN_COLA`, `VENTA` → `VENTA_REGISTRADA`).
2. **TECNICO** toma un ticket `EN_COLA`, registra diagnóstico (precio + repuestos), descuenta stock; el ticket pasa a `DIAGNOSTICADO`.
3. **CAJA** emite la factura del ticket.
4. **ADMIN** gestiona inventario y audita toda la traza de eventos.

# Catálogo de Servicios — SHServices V2

> Paquete documental S34 · Formato de **ficha de catálogo** (S33) con ownership explícito (S31).
> Última actualización: 2026-07-18.

## 1. Visión general

Sistema de gestión de servicio técnico multi-sede (PIURA / TALARA): recepción  diagnóstico 
almacén  facturación, con notificación y auditoría transversales. 7 microservicios de negocio
(FastAPI + PostgreSQL + RabbitMQ) detrás de un **API Gateway** que es el único punto de entrada
público, el único validador de identidad (JWT) y donde vive la resiliencia del sistema
(circuit breaker, timeouts, retry+backoff+jitter, bulkhead, rate limiting, shedding, outbox).
Los microservicios internos confían en las cabeceras `X-User-*` que el Gateway inyecta.

## 2. Ownership

El negocio tiene cinco áreas. Un "equipo backend" genérico **no** es owner suficiente: cada
servicio tiene un **owner funcional** (decide qué hace), un **owner técnico** (lo mantiene y
opera) y **consumidores** identificados.

| Área del negocio | Rol en el sistema | Qué decide / opera |
| :-- | :-- | :-- |
| **Recepción** (recepcionista) | `CAJA` | Alta de tickets y órdenes, cobro y entrega al cliente |
| **Técnico** | `TECNICO` | Diagnóstico, uso de repuestos, resultado técnico |
| **Administrador** | `ADMIN` | Inventario, usuarios, auditoría, supervisión de asignaciones |
| **Área de facturación** | `CAJA` / `ADMIN` | Comprobantes, montos, garantías |
| **Soporte de TI** | — (opera) | Despliegue, salud, incidentes y recuperación de TODOS los servicios |

**Matriz de responsabilidad** (formato S31 — decide / mantiene / consume / opera):

| Servicio | Owner funcional (decide) | Owner técnico (mantiene y opera) | Consumidores | Responsable operativo |
| :-- | :-- | :-- | :-- | :-- |
| api-gateway | Soporte de TI | Soporte de TI | Todas las áreas | Soporte de TI |
| auth-service | Administrador | Soporte de TI | Todas las áreas | Soporte de TI |
| ticket-service | Recepción | Soporte de TI | Recepción, Técnico, Administrador | Soporte de TI |
| diagnostico-service | Técnico | Soporte de TI | Técnico, Administrador | Soporte de TI |
| almacen-service | Administrador | Soporte de TI | Técnico, Recepción | Soporte de TI |
| facturacion-service | Área de facturación | Soporte de TI | Recepción, Administrador | Soporte de TI |
| auditoria-service | Administrador | Soporte de TI | Administrador | Soporte de TI |
| notificacion-service | Recepción | Soporte de TI | Todas las áreas | Soporte de TI |

> **Regla (S31):** ante un cambio de contrato o un incidente, el owner técnico (Soporte de TI)
> ejecuta y el owner funcional del área decide si el cambio procede.

### Usuarios de prueba

| Usuario | Contraseña | Rol | Sede |
| :-- | :-- | :-- | :-- |
| `admin` | `admin123` | `ADMIN` | PIURA |
| `caja01` | `caja123` | `CAJA` | PIURA |
| `tecnico01` | `tecnico123` | `TECNICO` | PIURA |
| `caja02` | `caja123` | `CAJA` | TALARA |
| `tecnico02` | `tecnico123` | `TECNICO` | TALARA |

## 3. Fichas de catálogo

### api-gateway
```yaml
serviceName: api-gateway
domain: plataforma
businessCapability: enrutar-y-proteger-trafico
ownerTeam: soporte-ti
technicalOwner: soporte-ti
businessOwner: soporte-ti
status: active
criticality: high          # punto único de entrada: si cae, cae el negocio
apiVersion: v1
puerto: 8000 -> 80
contracts:
  - ANY /api/v1/{servicio}/{path}   # proxy resiliente con RBAC
  - GET  /health
  - GET  /metrics                   # Prometheus
eventsPublished: []
dependencies:
  - todos los microservicios
  - postgres (tabla gateway_outbox)
  - toxiproxy (ruta hacia tickets)
```

### auth-service
```yaml
serviceName: auth-service
domain: seguridad
businessCapability: autenticar-y-autorizar
ownerTeam: soporte-ti
technicalOwner: soporte-ti
businessOwner: administrador
status: active
criticality: high          # sin token no hay operación
apiVersion: v1
puerto: 8003 -> 80
contracts:
  - POST /api/v1/auth/login         # emite JWT (sub, rol, sede, exp 2h)
  - GET  /api/v1/auth/usuarios      # ADMIN
  - POST /api/v1/auth/usuarios      # ADMIN
eventsPublished: []
dependencies:
  - postgres
```

### ticket-service
```yaml
serviceName: ticket-service
domain: atencion
businessCapability: gestionar-ticket-u-orden
ownerTeam: soporte-ti
technicalOwner: soporte-ti
businessOwner: recepcion
status: active
criticality: high
apiVersion: v1
puerto: 8001 -> 80        # vía Toxiproxy para inyección de fallos
contracts:
  - POST  /api/v1/tickets/tickets/                 # crear (idempotente: Idempotency-Key)
  - GET   /api/v1/tickets/tickets/pendientes       # cola EN_COLA
  - GET   /api/v1/tickets/tickets/por-estado/{e}
  - POST  /api/v1/tickets/tickets/{id}/tomar       # EN_COLA -> EN_DIAGNOSTICO
  - POST  /api/v1/tickets/tickets/{id}/diagnosticar
  - POST  /api/v1/tickets/tickets/{id}/rechazar    # libera stock
  - POST  /api/v1/tickets/tickets/{id}/entregar    # confirma stock, cierra
eventsPublished:
  - TicketCreado.v1
  - TicketListo.v1
dependencies:
  - postgres
  - rabbitmq
  - almacen-service          # confirmar/liberar stock
```

### diagnostico-service
```yaml
serviceName: diagnostico-service
domain: taller
businessCapability: diagnosticar-y-asignar
ownerTeam: soporte-ti
technicalOwner: soporte-ti
businessOwner: tecnico
status: active
criticality: high
apiVersion: v1
puerto: 8004 -> 80
contracts:
  - POST /api/v1/diagnosticos/diagnosticos/          # idempotente; 409 si ya tiene
  - GET  /api/v1/diagnosticos/diagnosticos/por-ticket/{id}
  - POST /api/v1/diagnosticos/asignaciones/tomar     # exclusivo: 409 si otro lo tomó
  - GET  /api/v1/diagnosticos/asignaciones/mias      # "Mis Tickets" del técnico
  - GET  /api/v1/diagnosticos/asignaciones/          # ADMIN: quién atiende qué
eventsPublished:
  - DiagnosticoRegistrado.v1
  - TicketTomado.v1
dependencies:
  - postgres
  - rabbitmq
  - almacen-service          # reservar repuestos
  - ticket-service           # sync de estado, BEST-EFFORT (no bloquea)
```
> **Dueño de las asignaciones.** "Mis Tickets" y la vista de admin las sirve este servicio, no
> el de tickets: así el técnico sigue trabajando aunque `ticket-service` esté caído (ADR-0012).

### almacen-service
```yaml
serviceName: almacen-service
domain: inventario
businessCapability: controlar-stock
ownerTeam: soporte-ti
technicalOwner: soporte-ti
businessOwner: administrador
status: active
criticality: medium
apiVersion: v1
puerto: 8002 -> 80
contracts:
  - GET  /api/v1/almacen/almacen/productos
  - POST /api/v1/almacen/almacen/productos     # código REP-/PRD- autogenerado
  - POST /api/v1/almacen/almacen/reservar
  - POST /api/v1/almacen/almacen/confirmar
  - POST /api/v1/almacen/almacen/liberar
  - POST /api/v1/almacen/almacen/descontar
eventsPublished:
  - ProductoRegistrado.v1
dependencies:
  - postgres
  - rabbitmq
```

### facturacion-service
```yaml
serviceName: facturacion-service
domain: cobranza
businessCapability: emitir-comprobante-y-garantia
ownerTeam: soporte-ti
technicalOwner: soporte-ti
businessOwner: area-de-facturacion
status: active
criticality: high
apiVersion: v1
puerto: 8005 -> 80
contracts:
  - POST /api/v1/facturas/facturas/                       # idempotente por id_ticket
  - GET  /api/v1/facturas/garantias/                      # listado con vigencia
  - GET  /api/v1/facturas/garantias/por-documento/{doc}
  - GET  /api/v1/facturas/garantias/factura-de/{idTicket} # comprobante de la garantía
eventsPublished:
  - FacturaGenerada.v1
dependencies:
  - postgres
  - rabbitmq
```
> **Dueño de las garantías.** La garantía de 90 días nace del COBRO, no de la entrega, y se
> consulta desde aquí: sobrevive a una caída de `ticket-service` (ADR-0013).

### auditoria-service
```yaml
serviceName: auditoria-service
domain: gobierno
businessCapability: registrar-trazabilidad
ownerTeam: soporte-ti
technicalOwner: soporte-ti
businessOwner: administrador
status: active
criticality: medium        # su caída no frena la operación, sí la evidencia
apiVersion: v1
puerto: 8006 -> 80
contracts:
  - GET /api/v1/auditoria/auditoria/eventos
eventsPublished: []
eventsConsumed:
  - ticket.*                # idempotente por (trace_id, evento)
dependencies:
  - postgres
  - rabbitmq
```

### notificacion-service
```yaml
serviceName: notificacion-service
domain: comunicacion
businessCapability: avisar-a-las-areas
ownerTeam: soporte-ti
technicalOwner: soporte-ti
businessOwner: recepcion
status: active
criticality: low           # degrada sin frenar el flujo principal
apiVersion: v1
puerto: 8007 -> 80
contracts:
  - GET    /api/v1/notificaciones/notificaciones/mis-alertas
  - POST   /api/v1/notificaciones/notificaciones/marcar-leidas
  - POST   /api/v1/notificaciones/notificaciones/webhooks/suscripciones
  - GET    /api/v1/notificaciones/notificaciones/webhooks/entregas
eventsPublished: []
eventsConsumed:
  - ticket.creado, ticket.listo, producto.registrado   # idempotente por (trace_id, evento, rol)
webhooksSalientes:
  - TicketCreado.v1, TicketListo.v1, ProductoRegistrado.v1   # HMAC-SHA256 + reintentos
dependencies:
  - postgres
  - rabbitmq
```

## 4. Infraestructura de soporte

| Componente | Contenedor | Puerto host | Función |
|---|---|---|---|
| PostgreSQL | `postgres-db` | interno | Persistencia (BD compartida `shservices_db`) |
| RabbitMQ | `rabbitmq` | `15672` (panel), `15692` (métricas) | Bus de eventos (exchange `tickets.eventos`, topic) |
| Toxiproxy | `toxiproxy` | `8474` (control) | Inyección de fallos hacia `ticket-service` |
| Prometheus | `prometheus` | `9090` | Scrape de métricas |
| Grafana | `grafana` | `3000` | Dashboard de resiliencia (provisionado) |
| Loki + Promtail | `loki`, `promtail` | interno | Agregación de logs, consultable en Grafana |
| Dozzle | `dozzle` | `9999` | Logs de contenedores en vivo |
| SonarQube | `sonarqube` | `9001` (perfil `analisis`) | Análisis estático |
| Frontend (Next.js) | (local) | `3001` | Cliente web (BFF + cookies HttpOnly) |

## 5. Contrato de Health Check

Todos los servicios exponen `GET /health` con validación real de PostgreSQL:

```json
{ "status": "UP", "service": "ticket-service", "version": "1.0.0", "dependencies": { "database": "UP" } }
```

Si la BD no responde: `status: "DEGRADED"`, `dependencies.database: "DOWN"` (sigue devolviendo
200 para no tumbar el contenedor). Además, cada microservicio expone
`POST /_chaos/crash` (falla controlada: mata su proceso para demostrar el auto-restart).

## 6. Flujo de negocio

1. **Recepción** registra el ticket (`SOPORTE`  `EN_COLA`; `VENTA`  `VENTA_REGISTRADA`)
    el **Técnico** recibe una alerta.
2. **Técnico** ve la cola de **su sede** y **toma** un ticket: queda asignado solo a él
   (otro técnico de la sede recibe 409) y aparece en **"Mis Tickets"**. Registra el
   diagnóstico (precio + repuestos), que **reserva stock** en Almacén; el ticket pasa a
   `DIAGNOSTICADO`  **Recepción** recibe la alerta de que ya puede cobrar.
3. **Recepción / Facturación** cobra: se emite el comprobante **y la garantía de 90 días**;
   al entregar se **confirma (consume)** el stock reservado y el ticket queda `ENTREGADO`.
4. **Administrador** gestiona inventario y usuarios, ve **quién atiende cada ticket** y
   audita la traza completa de eventos.

Todo el trayecto comparte un `X-Correlation-ID` único, auditado en `auditoria-service`.

## 7. Resiliencia

Detalle completo, verificación en vivo y métricas en [`matriz-resiliencia.md`](matriz-resiliencia.md).
Resumen: circuit breaker formal con **sonda activa** de recuperación, timeouts, retry+backoff+jitter,
bulkhead + shedding, rate limiting, **outbox transaccional** (ninguna escritura se pierde ni se
duplica), idempotencia en las tres capas, y auto-restart de contenedores ante crash real.

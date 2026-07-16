# Catálogo de Servicios

Una ficha de catálogo debe ser clara, versionable y revisable. Hace visible quién gobierna, conecta
servicio con capacidad, expone contratos y eventos e identifica dependencias críticas.

> **Nota sobre `contracts`**: las rutas se listan tal como las expone el propio microservicio.
> Al pasar por el API Gateway, la convención `/api/v1/{service}/{path}` hace que el path quede
> **doblado** (ej. `POST /api/v1/tickets/` del ticket_service se invoca públicamente como
> `POST /api/v1/tickets/tickets/`). El `auth_service` es la única excepción: el Gateway bloquea
> `/api/v1/auth/*` explícitamente, así que se consume directo en `:8003`.

## almacen_service
```yaml
serviceName: almacen_service
domain: inventario
businessCapability: gestionar-stock-y-precios-por-sede
ownerTeam: inventory-team
technicalOwner: tech-lead-almacen
businessOwner: logistica
status: active
criticality: high
apiVersion: v1
contracts:
  - GET /api/v1/almacen/productos
  - POST /api/v1/almacen/productos
  - POST /api/v1/almacen/reservar
  - POST /api/v1/almacen/confirmar
  - POST /api/v1/almacen/liberar
  - POST /api/v1/almacen/descontar
eventsPublished:
  - ProductoRegistrado.v1
dependencies:
  - postgres-db
  - rabbitmq
```

## api_gateway
```yaml
serviceName: api_gateway
domain: infraestructura
businessCapability: enrutamiento-seguridad-y-resiliencia
ownerTeam: platform-team
technicalOwner: devops-lead
businessOwner: ti
status: active
criticality: high
apiVersion: v1
contracts:
  - "* /api/v1/{service}/{path}"
eventsPublished: []
dependencies:
  - auth-service (validación JWT)
  - toxiproxy (proxy hacia ticket-service)
  - todos-los-microservicios (enrutamiento)
```

## auditoria_service
```yaml
serviceName: auditoria_service
domain: trazabilidad
businessCapability: auditar-y-persistir-eventos-del-sistema
ownerTeam: compliance-team
technicalOwner: tech-lead-auditoria
businessOwner: seguridad
status: active
criticality: medium
apiVersion: v1
contracts:
  - GET /api/v1/auditoria/eventos
eventsPublished: []
eventsConsumed:
  - ticket.* (todos los eventos de tickets.eventos)
dependencies:
  - rabbitmq
  - postgres-db
```

## auth_service
```yaml
serviceName: auth_service
domain: identidad
businessCapability: autenticacion-emision-jwt-y-gestion-usuarios
ownerTeam: security-team
technicalOwner: devsecops
businessOwner: ti
status: active
criticality: high
apiVersion: v1
contracts:
  - POST /api/v1/auth/login
  - GET /api/v1/auth/usuarios
  - POST /api/v1/auth/usuarios
eventsPublished: []
dependencies:
  - postgres-db
```

## base_service
```yaml
serviceName: base_service
domain: plataforma
businessCapability: plantilla-para-nuevos-microservicios
ownerTeam: platform-team
technicalOwner: devops-lead
businessOwner: ti
status: template
criticality: low
apiVersion: v1
contracts:
  - GET /api/v1/health
eventsPublished: []
dependencies: []
```

## diagnostico_service
```yaml
serviceName: diagnostico_service
domain: servicio-tecnico
businessCapability: diagnosticar-equipo-y-reservar-repuestos
ownerTeam: repair-team
technicalOwner: tech-lead-reparacion
businessOwner: centro-servicios
status: active
criticality: high
apiVersion: v1
contracts:
  - POST /api/v1/diagnosticos/
  - GET /api/v1/diagnosticos/por-ticket/{idTicket}
eventsPublished:
  - DiagnosticoRegistrado.v1
dependencies:
  - almacen_service (HTTP síncrono, reserva de stock)
  - rabbitmq
  - postgres-db
```

## facturacion_service
```yaml
serviceName: facturacion_service
domain: pagos
businessCapability: emitir-comprobantes-pos
ownerTeam: finance-team
technicalOwner: tech-lead-finanzas
businessOwner: finanzas
status: active
criticality: high
apiVersion: v1
contracts:
  - POST /api/v1/facturas/
eventsPublished:
  - FacturaGenerada.v1
dependencies:
  - postgres-db
  - rabbitmq
```

## notificacion_service
```yaml
serviceName: notificacion_service
domain: comunicacion-interna
businessCapability: alertar-a-roles-en-tiempo-real
ownerTeam: platform-team
technicalOwner: tech-lead-notificaciones
businessOwner: operaciones
status: active
criticality: medium
apiVersion: v1
contracts:
  - GET /api/v1/notificaciones/mis-alertas
  - POST /api/v1/notificaciones/marcar-leidas
eventsPublished: []
eventsConsumed:
  - ticket.creado    (alerta a TECNICO si estado=EN_COLA)
  - ticket.listo     (alerta a CAJA)
  - producto.registrado  (alerta a ADMIN)
dependencies:
  - rabbitmq
  - postgres-db
```

## ticket_service
```yaml
serviceName: ticket_service
domain: atencion-cliente-y-taller
businessCapability: gestionar-ciclo-de-vida-de-tickets-y-garantias
ownerTeam: customer-service-team
technicalOwner: tech-lead-tickets
businessOwner: atencion-cliente
status: active
criticality: high
apiVersion: v1
contracts:
  - POST /api/v1/tickets/
  - GET /api/v1/tickets/
  - GET /api/v1/tickets/pendientes
  - GET /api/v1/tickets/por-estado/{estado}
  - PATCH /api/v1/tickets/{id}
  - POST /api/v1/tickets/{id}/tomar
  - POST /api/v1/tickets/{id}/diagnosticar
  - POST /api/v1/tickets/{id}/rechazar
  - POST /api/v1/tickets/{id}/entregar
  - GET /api/v1/tickets/garantias
  - GET /api/v1/tickets/garantias/por-documento/{documento}
eventsPublished:
  - TicketCreado.v1
  - TicketListo.v1
dependencies:
  - postgres-db
  - rabbitmq
  - almacen_service (HTTP síncrono: confirmar/liberar stock reservado)
```

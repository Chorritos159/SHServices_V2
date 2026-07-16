# Changelog Técnico - ticket_service
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa: es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v0.1` | Prototipo: CRUD simple de tickets en memoria | Release | Uso interno, no consumible |
| `v0.4` | Persistencia en PostgreSQL vía SQLAlchemy | Compatible | Ninguna |
| `v1.0` | feat(ticket-service): Integración asíncrona con RabbitMQ y publicación de eventos | Release | Suscribirse a eventos de tickets |
| `v1.1` | feat(ticket-service): Endpoint PATCH para reparar equipos y actualizar costos | Compatible | Opcional |
| `v1.2` | Mejora del servicio de ticket | Compatible | Opcional |
| `v1.3` | Flujo de tickets + notas de venta ok | Compatible | Opcional |
| `v2.0` | Adaptación a V2 (delegando facturación y diagnóstico a nuevos microservicios) | Breaking | Cambiar flujos a nuevos microservicios |
| `v2.1` | feat(tickets): `sede`/`usuario` desde el token JWT (ya no en el body); bandeja de pendientes | Breaking | Quitar `sede`/`usuarioRegistro` del payload de `POST /tickets/` |
| `v2.2` | feat(tickets): enriquecer registro (documento, teléfono, equipo, precio estimado) + `GET` listado y por-estado | Compatible | Nuevos campos opcionales en el `POST`; usar `GET /por-estado/{estado}` para filtrar |
| `v2.3` | feat(tickets): máquina de estados centralizada (`/tomar`, `/diagnosticar`, `/rechazar`, `/entregar`) + garantías de 90 días | Breaking | Ya no usar `PATCH /{id}` con estado libre; usar los endpoints de transición |
| `v2.4` | feat(tickets): `monto_total` en garantías y evento `TicketListo.v1` al pasar a DIAGNOSTICADO | Compatible | `GET /garantias` ahora incluye `monto_total` |

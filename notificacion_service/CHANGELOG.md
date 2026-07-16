# Changelog Técnico - notificacion_service
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa: es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v0.1` | Prototipo: consumidor que solo loguea eventos, sin persistencia ni API | Release | Uso interno, no consumible |
| `v1.0` | feat(notificaciones): microservicio nuevo (FastAPI + PostgreSQL + consumidor RabbitMQ resiliente) | Release | Ninguna (servicio nuevo) |
| `v1.1` | feat(notificaciones): reglas de enrutamiento por rol — `ProductoRegistrado`→ADMIN, `TicketCreado` EN_COLA→TECNICO | Release | Consultar `GET /mis-alertas` con el JWT del rol correspondiente |
| `v1.2` | feat(notificaciones): regla `ticket.listo`→CAJA ("Equipo listo para cobro y entrega") | Compatible | Ninguna |
| `v1.3` | feat(observability): instrumentación Prometheus (`/metrics`) | Compatible | Ninguna |

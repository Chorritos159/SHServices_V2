# Changelog Técnico - almacen_service
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa: es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v0.3` | Prototipo: tabla `inventario` con un único campo de stock | Release | Uso interno, no consumible |
| `v0.7` | Se separan `stock_disponible` y `stock_reservado` | Compatible | Ninguna |
| `v1.0` | feat(almacen-service): Consumidor de eventos RabbitMQ y gestión de stock por sedes | Release | N/A |
| `v2.0` | Refactorización V2 y actualización de arquitectura | Breaking | Actualizar URLs y contratos |
| `v2.1` | feat(almacen): `GET /productos`, autogeneración de código `REP-NNN` (ya no se envía `codigo`) | Breaking | Quitar `codigo` del `POST /productos`; usar el código devuelto por la API |
| `v2.2` | feat(almacen): `precio_unitario` + stock en 2 fases: `POST /confirmar`, `/liberar`, `/descontar` | Breaking | `POST /reservar` ya no es la única operación de stock; usar `/confirmar` al entregar y `/liberar` al rechazar |
| `v2.3` | feat(almacen): publica evento `ProductoRegistrado.v1` al crear un producto | Compatible | Suscribirse si se necesita alertar sobre altas de inventario |

# Changelog Técnico - api_gateway
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa: es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v0.1` | Prototipo interno: reverse-proxy fijo sin autenticación | Release | Uso interno, no consumible |
| `v0.3` | Se agrega enrutamiento dinámico por segmento `{service}` | Compatible | Ninguna |
| `v0.6` | Primer Circuit Breaker (try/except sobre `httpx.ConnectError`) | Compatible | Ninguna |
| `v1.0` | feat(api-gateway): Implementar escudo de seguridad JWT y proxy reverso | Release | Enviar header Authorization |
| `v1.1` | feat(infra): Dockerización completa de la arquitectura | Compatible | Ninguna |
| `v2.0` | Actualización de rutas para nuevos microservicios de la V2 | Compatible | Ninguna |
| `v2.1` | refactor(gateway): inyectar headers de identidad `X-User-Sub/Rol/Sede` desde el JWT | Breaking | Los servicios internos ya no reciben `sede`/`usuario` en el body; deben leer las cabeceras |
| `v2.2` | feat(gateway): registrar `notificacion-service` y `auditoria-service` en el mapa de rutas | Compatible | Ninguna |
| `v2.3` | feat(observability): métrica dedicada `gateway_circuit_breaker_total{service,motivo}` en modo multiproceso | Compatible | Ninguna (solo expone `/metrics`) |

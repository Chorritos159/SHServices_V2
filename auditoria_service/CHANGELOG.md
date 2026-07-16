# Changelog Técnico - auditoria_service
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa: es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v0.5` | Prototipo: consumidor que solo imprime los eventos por consola | Release | Uso interno, no consumible |
| `v2.0` | Creación inicial del servicio en la arquitectura V2 | Release | Ninguna (consumidor pasivo) |
| `v2.1` | feat(auditoria): consumidor resiliente con reintento (`connect_robust` + backoff) | Compatible | Ninguna |
| `v2.2` | feat(auditoria): persistencia en PostgreSQL con `correlationId` (antes en memoria, se perdía al reiniciar) | Breaking | `GET /eventos` ahora refleja historial persistente, no solo el último proceso |

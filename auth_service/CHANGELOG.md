# Changelog Técnico - auth_service
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa: es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v0.2` | Prototipo: login contra usuarios hardcodeados en memoria | Release | Uso interno, no consumible |
| `v0.5` | Firma de JWT con HS256 y expiración de 2h | Compatible | Ninguna |
| `v1.0` | feat: implementar autenticación JWT, IAM y configuración | Release | Integrar API de login |
| `v2.0` | Integración y compatibilidad con V2 | Compatible | Ninguna |
| `v2.1` | feat(auth): agregar roles CAJA/TECNICO y claim `sede` en el JWT (elimina rol OPERADOR) | Breaking | Los tokens `OPERADOR` quedan inválidos; re-loguear. Leer `rol`+`sede` del payload |
| `v2.2` | feat(auth): endpoint `POST/GET /api/v1/auth/usuarios` protegido para ADMIN | Compatible | Opcional: usar para alta de empleados |
| `v2.3` | feat(auth): migrar gestión de usuarios de memoria a PostgreSQL con seed automático | Breaking | Ninguna para el cliente HTTP; los usuarios ahora persisten entre reinicios |

# Revisión OWASP Top 10 (2021) — SHServices V2

> Revisión del código completo (8 microservicios + API Gateway + frontend
> Next.js), 2026-07-17. Cada fila dice qué se revisó **concretamente** en
> este código, no la definición genérica de la categoría. Los hallazgos
> corregidos están verificados en vivo; los que quedan abiertos están en
> `documentacion/brechas_finales.md`.

## Resumen

| # | Categoría | Estado | Detalle |
| :-- | :-- | :-- | :-- |
| A01 | Broken Access Control | ⚠️ Parcial | RBAC en el Gateway; los microservicios confían en las cabeceras inyectadas (ver hallazgo 2) |
| A02 | Cryptographic Failures | ✅ **Corregido** | Contraseñas estaban en **texto plano** → migradas a bcrypt (ver hallazgo 1) |
| A03 | Injection | ✅ OK | Todo el acceso a datos va por SQLAlchemy ORM (consultas parametrizadas); cero SQL crudo interpolado. React escapa el HTML por defecto; sin `dangerouslySetInnerHTML` |
| A04 | Insecure Design | ✅ OK | Resiliencia por diseño (circuit breaker, bulkhead, rate limit, idempotencia — Fases 1-3); identidad centralizada en un solo punto |
| A05 | Security Misconfiguration | ⚠️ Parcial | Sin `debug=True`; contenedores sin privilegios; pero Swagger y el auth-service quedan expuestos para la demo (ver hallazgo 3) |
| A06 | Vulnerable & Outdated Components | ⚠️ Pendiente | `npm audit` reporta 2 vulnerabilidades moderadas en el frontend; sin escaneo automatizado de dependencias Python |
| A07 | Identification & Auth Failures | ✅ **Mejorado** | Hash bcrypt + comparación en tiempo constante + mensaje de error único (no permite enumerar usuarios). Sin bloqueo por intentos fallidos (ver hallazgo 4) |
| A08 | Software & Data Integrity | ✅ OK | Imágenes con tag fijo; contenedores corren como usuario sin privilegios (`USER appuser`); sin `curl \| bash` en los Dockerfiles |
| A09 | Logging & Monitoring Failures | ✅ OK | Logs estructurados S34 con `correlationId` en los 9 servicios; **no se loguea ninguna contraseña ni token**; Prometheus + Grafana + Loki |
| A10 | Server-Side Request Forgery | ✅ OK | El Gateway solo enruta a un **mapa fijo** de servicios (`MICROSERVICIOS`); un `service` desconocido devuelve 404. La URL destino nunca se construye con input del usuario |

---

## Hallazgo 1 — A02: contraseñas en texto plano ✅ CORREGIDO

**Riesgo:** crítico. La tabla `usuarios` guardaba las contraseñas **en
claro** (`password="admin123"`), y el login las comparaba con `!=`.
Cualquiera con acceso de lectura a la BD (un dump, un backup, o una
inyección en otro servicio — todos comparten la misma base
`shservices_db`) se llevaba todas las credenciales utilizables; como la
gente reutiliza contraseñas, el daño excede este sistema. El `!=`
además filtraba información por *timing*.

**Corrección** (`auth_service/app/core/password.py`, nuevo):
- **bcrypt** con salt por contraseña y coste 12 (~250 ms por verificación:
  frena la fuerza bruta sin que el login se sienta lento).
- Comparación en **tiempo constante** (`bcrypt.checkpw` / `hmac.compare_digest`).
- El seed inicial ya **no escribe texto plano** ni siquiera para las
  credenciales de demo.
- **Migración transparente:** las filas legadas en texto plano se re-hashean
  solas en el primer login exitoso — nadie queda fuera del sistema y no
  hace falta un script de migración manual.

**Verificado en vivo:** `admin` estaba como `admin123` → tras un login
correcto quedó `$2b$12$md/ls3TH...`; login con la clave correcta sigue
dando 200, con clave incorrecta da 401. Las 3 cuentas de demo migradas.

## Hallazgo 2 — A01: los microservicios confían en las cabeceras del Gateway ⚠️ ABIERTO

**Riesgo:** medio (mitigado, no eliminado). El Gateway valida el JWT e
inyecta `X-User-Sub` / `X-User-Rol` / `X-User-Sede`; los microservicios
internos **confían** en esas cabeceras sin re-validar el token. Quien
pudiera emitir peticiones **dentro de la red Docker** podría falsificar
las cabeceras y saltarse el control de acceso.

**Mitigación actual:** ningún microservicio de negocio publica puerto al
host (solo el Gateway en `8000` y el auth-service en `8003`), así que el
ataque exige ya tener acceso a la red interna.

**Acción recomendada:** propagar el JWT y validarlo también en cada
servicio (defensa en profundidad), o una malla de servicios con mTLS.
Registrado en `documentacion/brechas_finales.md`.

## Hallazgo 3 — A05: superficie expuesta para la demo ⚠️ ACEPTADO

- `auth-service` publica el puerto `8003` (necesario porque el Gateway
  bloquea `/api/v1/auth/*` y el frontend hace login directo).
- Swagger (`/docs`) abierto en Gateway y auth-service.
- Paneles de Grafana/RabbitMQ/Prometheus/Dozzle sin autenticación fuerte
  (credenciales `admin/admin`, `guest/guest`).

**Aceptado** para sustentación/demo local. Antes de cualquier despliegue
real: cerrar `8003` (que el login pase por el Gateway), desactivar Swagger
en producción, y poner credenciales fuertes en los paneles.

## Hallazgo 4 — A07: sin bloqueo por intentos fallidos ⚠️ ABIERTO

No hay límite de intentos de login por usuario/IP: un atacante puede
probar contraseñas sin freno (el rate limit global del Gateway **no**
aplica al login, porque va directo al auth-service en el `8003`).

**Mitigación parcial:** el coste 12 de bcrypt hace cada intento ~250 ms,
lo que ya limita mucho el ritmo de un ataque.

**Acción recomendada:** bloqueo temporal tras N fallos por usuario, y rate
limit específico en el endpoint de login.

## Hallazgo 5 — A06: dependencias con vulnerabilidades conocidas ⚠️ ABIERTO

`npm install` en el frontend reporta **2 vulnerabilidades moderadas**. No
hay escaneo automatizado de las dependencias Python.

**Acción recomendada:** `npm audit fix`, y agregar `pip-audit`/`safety` +
`npm audit` al pipeline. El análisis de SonarQube (ver README) cubre la
calidad y seguridad del **código propio**, no las dependencias de terceros.

---

## Lo que ya estaba bien (verificado, no asumido)

- **A03 Injection:** cero SQL crudo — todo el acceso a datos pasa por el
  ORM de SQLAlchemy con consultas parametrizadas. Pydantic valida y tipa
  todos los payloads de entrada. React escapa el HTML por defecto y no se
  usa `dangerouslySetInnerHTML` en ningún sitio.
- **A07 Sesión en el frontend:** el JWT vive en una cookie `httpOnly`
  (inaccesible desde JS del cliente → inmune a robo por XSS), con
  `secure` en producción y `sameSite: lax` (mitiga CSRF).
- **A08 Contenedores:** todos corren como `appuser`, un usuario sin
  privilegios creado en el Dockerfile — no como root.
- **A09 Logging:** ni una sola línea loguea contraseñas, tokens ni
  cabeceras `Authorization` (verificado con búsqueda en los 9 servicios).
- **A10 SSRF:** el Gateway enruta contra un diccionario fijo
  (`MICROSERVICIOS`); un servicio no registrado devuelve 404 y la URL de
  destino jamás se arma con texto que venga del usuario.
- **Secretos:** fuera del código desde la Fase 1 (`.env` gitignored, con
  `${VAR:?mensaje}` en el compose para fallar ruidosamente si falta).

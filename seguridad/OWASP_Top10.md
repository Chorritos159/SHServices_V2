# Revisión OWASP Top 10 (2021) — SHServices V2

> Revisión del código completo (8 microservicios + API Gateway + frontend
> Next.js), revisada el **2026-07-18** tras incorporar el outbox, las
> asignaciones, las garantías y los endpoints de caos. Cada fila dice qué se
> revisó **concretamente** en
> este código, no la definición genérica de la categoría. Los hallazgos
> corregidos están verificados en vivo; los que quedan abiertos están en
> `documentacion/brechas_finales.md`.

## Resumen

| # | Categoría | Estado | Detalle |
| :-- | :-- | :-- | :-- |
| A01 | Broken Access Control | ⚠️ **Hallazgo abierto** | RBAC en el Gateway; los microservicios confían en las cabeceras inyectadas (hallazgo 2) y el RBAC de lectura vive solo en el BFF (hallazgo 7). Los `/_chaos/crash` **ya están cerrados** tras `CHAOS_ENABLED` (hallazgo 6) |
| A02 | Cryptographic Failures | ✅ **Corregido** | Contraseñas estaban en **texto plano** → migradas a bcrypt (ver hallazgo 1) |
| A03 | Injection | ✅ OK | Todo el acceso a datos va por SQLAlchemy ORM (consultas parametrizadas); cero SQL crudo interpolado. React escapa el HTML por defecto; sin `dangerouslySetInnerHTML` |
| A04 | Insecure Design | ✅ OK | Resiliencia por diseño (circuit breaker, bulkhead, rate limit, idempotencia — Fases 1-3); identidad centralizada en un solo punto |
| A05 | Security Misconfiguration | ⚠️ **Aceptado** | Sin `debug=True`; contenedores sin privilegios. Swagger/auth expuestos para la demo (hallazgo 3, aceptado). Los endpoints de caos ya nacen **apagados** y devuelven 404 salvo que se encienda `CHAOS_ENABLED` (hallazgo 6, **corregido**) |
| A06 | Vulnerable & Outdated Components | ⚠️ Pendiente | `npm audit` (2026-07-18): **2 moderadas** en el frontend, sin exposición directa (dependencias de build). Sin escaneo automatizado de dependencias Python |
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

## Hallazgo 6 — A01/A05: los endpoints de caos no exigen autenticación 🟢 CERRADO

**Qué se encontró.** Los 7 microservicios exponen `POST /_chaos/crash`, que mata
su propio proceso (`os._exit(1)`) para demostrar el auto-restart. Verificado
sobre el OpenAPI real de `ticket-service`:

```
/_chaos/crash  ->  expuesto en el puerto 8001: SI
                   seguridad declarada: NINGUNA (endpoint abierto)
```

**Por qué importa.** Cualquiera con acceso de red a los puertos publicados
(8001-8007) puede **apagar cualquier servicio del sistema**, sin token y sin
dejar rastro de quién fue. Es una denegación de servicio trivial y, a la vez,
una función administrativa sin control de acceso.

**Riesgo aceptado hoy:** el entorno es local y de demostración (los puertos solo
escuchan en `localhost`). En cualquier despliegue compartido sería crítico.

**Cómo se corrigió.** El endpoint quedó detrás de `CHAOS_ENABLED`, **apagada por
defecto en el código** (`app/api/health.py` de los 7 servicios):

- Si la variable no está encendida, el endpoint responde **404** —no 403— para no
  revelar siquiera que existe, y se oculta del OpenAPI (`include_in_schema`).
- `docker-compose.yml` la enciende explícitamente en los 7 servicios, con un
  comentario que dice por qué: se necesita para demostrar el auto-healing de la
  S34. En un despliegue real esa línea no existiría.

**Verificado en los dos estados** (18/07/2026):

```
CHAOS_ENABLED=true   POST /_chaos/crash -> 200, el proceso muere y
                     restart:always lo revive  -> /health 200
CHAOS_ENABLED=false  POST /_chaos/crash -> 404 {"error":"No encontrado"}
                     /health -> 200 (el servicio NO se cayó)
                     openapi.json -> rutas con _chaos: NINGUNA
```

El riesgo real —que cualquiera apague un servicio sin token— desaparece en
cuanto la variable no se enciende, que es el estado por defecto.

---

## Hallazgo 7 — A01: el RBAC de lectura vive solo en el BFF ⚠️ ABIERTO

**Qué se encontró.** La consulta de garantías está restringida a `CAJA`/`ADMIN`
en el BFF de Next.js, pero llamando **directo al Gateway** con un token de
`TECNICO` responde igualmente:

```
TECNICO -> GET /api/v1/facturas/garantias/  ->  HTTP 200
```

**Por qué pasa.** El Gateway solo aplica RBAC a los métodos destructivos
(`DELETE` = ADMIN); para el resto valida *autenticación* pero no *autorización*
por rol. Es la misma raíz del hallazgo 2: la autorización fina vive en los
extremos (BFF o servicio), no en el Gateway.

**Matiz importante:** no todos los endpoints están igual. Las vistas que sí
implementaron la comprobación en el servicio se comportan bien —
`GET /diagnosticos/asignaciones/` devuelve **403** a un técnico. La diferencia
es que ahí el chequeo se hizo en el servicio y en garantías no.

**Impacto real:** bajo. Un técnico autenticado ve datos de garantía de su propia
empresa; no hay exposición a terceros ni escritura. Pero es una inconsistencia
de diseño que conviene cerrar.

**Acción recomendada:** declarar el rol mínimo por ruta en el Gateway (tabla
`ruta -> roles`), en vez de repetir la comprobación en cada servicio y BFF.

---

## Hallazgo 8 — A02/A09: el outbox guarda identidad, NO el token ✅ CORRECTO POR DISEÑO

Se revisó qué persiste la tabla `gateway_outbox`, porque almacena peticiones
completas para reintentarlas más tarde. Contenido real de una fila:

```json
{"content-type": "application/json", "idempotency-key": "...",
 "x-correlation-id": "...", "x-user-sub": "caja01",
 "x-user-rol": "CAJA", "x-user-sede": "PIURA"}
```

**No se guarda la cabecera `Authorization`.** Es deliberado (ADR-0011): el JWT
puede expirar antes de que el worker consiga entregar, y guardar tokens en base
de datos sería una fuga esperando a ocurrir. Se persiste solo la **identidad ya
validada**, que es lo que los servicios internos consumen.

El cuerpo de la petición sí se guarda (es el dato de negocio a reenviar: ticket,
cobro, producto). No contiene credenciales.

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

---

## Hallazgo 9 — A02: SonarQube marca 16 usos de `http://` ⚠️ ACEPTADO CON JUSTIFICACIÓN

**Qué se encontró.** El análisis estático reporta 16 issues de seguridad, todas
de la misma regla `python:S5332` ("Using HTTP protocol is insecure. Use HTTPS
instead"), repartidas por el Gateway, los consumidores de RabbitMQ y las
llamadas entre servicios.

**Por qué NO se "corrigen".** Se revisaron las 16 una por una: **todas** son
URLs de la red interna de Docker, resueltas por el DNS del bridge y que nunca
salen del host:

```
http://ticket-service:80      http://almacen-service:80
http://diagnostico-service:80 amqp://rabbitmq:5672
...
```

Cambiarlas a `https://` no las haría más seguras: no hay ningún certificado
que presentar para el nombre `ticket-service`, y el resultado sería que el
sistema deja de arrancar. Es un falso positivo *de contexto*: la regla no
distingue una URL pública de un nombre de servicio interno.

**Lo que sí sería la solución real** (fuera del alcance de este proyecto):
terminar TLS en el borde —ya se hace, el único punto de entrada es el
Gateway— y cifrar el tráfico este-oeste con **mTLS** vía un service mesh
(Istio/Linkerd) o certificados internos. Eso se decide a nivel de plataforma,
no cambiando un literal en el código.

**Estado:** riesgo aceptado y documentado. El borde (lo que un atacante puede
alcanzar) no viaja en claro; el tráfico interno sí, dentro de la red del host.

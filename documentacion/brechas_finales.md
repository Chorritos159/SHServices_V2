# Brechas finales — SHServices V2 (S34, Fase 6)

Tabla consolidada para el dictamen técnico. Cada fila es una brecha real,
identificada durante la integración (Fases 1-5), no una lista genérica de
"posibles mejoras" — todas tienen evidencia o razonamiento concreto detrás
(ver el documento referenciado en cada una).

| # | Brecha | Riesgo | Acción recomendada | Responsable |
|---|---|---|---|---|
| 1 | ~~Gateway con 1 solo worker Gunicorn (ADR-0008)~~ · **CERRADA (2026-07-18)** | — | **Hecho:** Se implementó un estado compartido en Redis para los circuit breakers (ADR-0015) y se escaló el Gateway a 8 Gunicorn workers. Se eliminó el cuello de botella de un solo núcleo de CPU. | Owner técnico del Gateway |
| 2 | Gateway como punto único de fallo | Si el proceso completo cae, cae todo el tráfico de negocio (no hay redundancia/réplicas en esta entrega) | Desplegar ≥2 réplicas detrás de un balanceador, con el estado de resiliencia ya compartido (depende de la acción #1) | DevOps / Owner de infraestructura |
| 3 | ~~`producto.registrado` no queda auditado~~ · **CERRADA (2026-07-18)** | — | Se añadió un segundo binding `producto.*` a la cola de auditoría (`auditoria_service/app/core/consumer.py`). Verificado: al registrar un producto queda el evento `ProductoRegistrado.v1` con su `trace_id` y sede | Owner técnico de Auditoría/Almacén |
| 4 | Fallas de la S34 no cubiertas por fichas de caos: consumidor lento, base de datos lenta, error de contrato, fallo parcial explícito | Sin verificación en vivo de estos escenarios (ver `documentacion/fichas_falla_controlada.md`, tabla final) | Diseñar fichas dedicadas: mock/proxy delante de PostgreSQL para latencia simulada; contrato inválido explícito en un endpoint; fallo parcial multi-repuesto en diagnóstico | Owner técnico de Resiliencia |
| 5 | ~~Corridas de carga 100k/500k/1M no ejecutadas~~ · **CERRADA (2026-07-20)** | — | **Hecho:** ejecutadas con k6 (`pruebas_k6/correr.py`). Resultados en `documentacion/tabla_registro_carga_k6.md` y `registro_de_carga.md`. Medido: ~200 rps sostenidos, p95 2,2 s, cero errores 500 | Equipo |
| 6 | `.env` con valores de demo, sin rotar | Los secretos usados durante todo el desarrollo (contraseñas, `JWT_SECRET_KEY`) no son aptos para un despliegue real | Rotar todos los secretos antes de cualquier despliegue fuera de la demo/sustentación | Owner de Seguridad |
| 10 | Los microservicios confían en las cabeceras `X-User-*` del Gateway sin re-validar el JWT (OWASP A01) | Quien alcance un microservicio directo puede falsificar identidad/rol en las cabeceras y saltarse JWT + RBAC del Gateway | Propagar el JWT y validarlo también en cada servicio (defensa en profundidad), o malla con mTLS | Owner técnico de Seguridad |
| 14 | Los 6 microservicios internos publican puerto al host (8001-8007) para exponer su Swagger (`/docs`) | Se puede golpear un servicio directo, saltándose el Gateway (JWT, RBAC, resiliencia). Agrava la brecha #10 (antes ninguno era alcanzable desde el host). Aceptado solo para demo/sustentación | Antes de un despliegue real: quitar esos `ports` del compose (Swagger accesible solo por túnel/red interna) y dejar el Gateway como único punto de entrada | Owner de Seguridad / DevOps |
| 11 | Sin bloqueo por intentos fallidos de login (OWASP A07) | Fuerza bruta contra `/auth/login` sin freno; el rate limit del Gateway no aplica (el login va directo al `8003`). Mitigado en parte: bcrypt coste 12 hace cada intento ~250 ms | Bloqueo temporal tras N fallos por usuario + rate limit en el endpoint de login | Owner técnico de Auth |
| 12 | Dependencias con vulnerabilidades conocidas (OWASP A06) | `npm audit` reporta 2 vulnerabilidades moderadas en el frontend; sin escaneo automatizado de dependencias Python | `npm audit fix`; agregar `pip-audit`/`safety` + `npm audit` al pipeline | DevOps |
| 13 | Tráfico interno sin TLS (HTTP/AMQP entre contenedores) | 15 hallazgos MINOR de SonarQube. No explotable desde fuera (red Docker privada, sin puertos publicados) | TLS entre servicios internos (requiere CA y gestión de certificados) o una malla de servicios con mTLS | DevOps / Owner de infraestructura |
| 14 | Trazas sin spans jerárquicos (no hay tracer distribuido) | La relación entre servicios se reconstruye con el `correlationId` (cumple la S34), pero no hay jerarquía padre/hijo ni tiempo por tramo como daría OpenTelemetry/Jaeger | Migrar a OpenTelemetry si se necesita analizar cuellos de botella *dentro* de una operación multi-servicio | Owner técnico de Observabilidad |
| 7 | Sin gestor de secretos externo (Vault, AWS Secrets Manager, etc.) | `.env` es un archivo plano en disco (gitignored, pero no cifrado ni auditado) | Aceptable para un proyecto académico de sustentación; evaluar un gestor real antes de producción | Owner de Seguridad |
| 8 | PostgreSQL y RabbitMQ sin réplica ni backup automatizado | Pérdida de datos o indisponibilidad si el contenedor de datos falla (más allá de lo que cubre `restart: always`) | Definir política de backup (`pg_dump` programado) y evaluar réplica de RabbitMQ para un entorno no-demo | DevOps / Owner de infraestructura |
| 9 | ~~Frontend (Next.js) no está dockerizado~~ —  **CERRADA 18/07/2026** | El sistema no se levantaba con un solo comando y la web corría en modo desarrollo durante la sustentación | **Hecho:** `frontend/Dockerfile` con build multi-stage (deps  builder  runner) y `output: standalone`, servicio `frontend` en el compose (contenedor `shservices-frontend`), usuario sin privilegios y healthcheck contra `/login`. Imagen de 217 MB. Ahora `docker compose up -d --build` levanta TODO, web incluida | Owner técnico de Frontend |

## Cómo se usa esta tabla

Cada brecha es honesta y verificable — no oculta nada que se haya
encontrado durante el trabajo de las Fases 1-5. Ninguna bloquea la
demostración de los mecanismos de resiliencia exigidos por la S34 (todos
están implementados y verificados en vivo, ver `matriz-resiliencia.md` y
`documentacion/matriz_revision_resiliencia.md`); son limitaciones de
alcance y decisiones explícitas de priorización, documentadas para que el
dictamen las evalúe con la información completa.
| 6 | Cobertura de tests **parcial** (antes: 0 %) · **MITIGADA (2026-07-18)** | Hay 26 tests unitarios sobre los mecanismos de resiliencia (100 % en circuit breaker y bulkhead, 96 % en rate limit), pero la lógica de negocio (máquina de estados del ticket, idempotencia de facturas) sigue cubierta solo por las pruebas de integración | Extender pytest a la lógica de negocio de cada servicio; la cobertura global seguirá baja hasta entonces | Owner técnico de cada servicio (Soporte de TI) |
| 7 | **Duplicación 26 %** entre microservicios (`app/core/` y `/_chaos/crash` replicados por servicio) | SonarQube la reporta como deuda; un cambio transversal (p. ej. el formato de log) hay que aplicarlo N veces | Aceptada por diseño: los servicios no comparten librería para poder desplegarse y fallar de forma independiente. Si la mantenibilidad lo exige, publicar `app/core` como paquete interno versionado | Soporte de TI |
| 8 | La garantía nace del **cobro**, no de la entrega (ADR-0013) | Si algún día cobro y entrega se separan en el tiempo, la vigencia de 90 días empezaría antes de que el cliente reciba el equipo | Revisar la regla con el Área de facturación y, si se separan, mover el disparo al hito de entrega | Área de facturación (owner funcional) |
| 9 | ~~**Endpoints `/_chaos/crash` sin autenticación**~~ (OWASP hallazgo 6) —  **CERRADA 18/07/2026** | Cualquiera con acceso a los puertos 8001-8007 podía apagar cualquier servicio, sin token y sin trazabilidad | **Hecho:** quedaron tras `CHAOS_ENABLED`, apagada por defecto en el código. Apagada  **404** (no 403: no revela que exista) y fuera del OpenAPI. `docker-compose.yml` la enciende explícitamente solo para la demo de auto-healing. Verificado en ambos estados | Soporte de TI |
| 10 | RBAC de lectura solo en el BFF (OWASP hallazgo 7) | Un `TECNICO` llamando directo al Gateway lee `/facturas/garantias/` (HTTP 200) aunque la UI lo restrinja a CAJA/ADMIN. Impacto bajo (solo lectura, mismo negocio), pero es inconsistente: en asignaciones sí devuelve 403 | Declarar el rol mínimo por ruta en el Gateway (tabla `ruta -> roles`) en vez de repetirlo en cada BFF/servicio | Soporte de TI |

| 15 | ~~El Gateway descartaba el **query string**~~ —  **CERRADA 18/07/2026** | Ningún parámetro de consulta llegaba a los servicios a través del Gateway (paginación, filtros, búsquedas). Invisible porque la respuesta seguía siendo un 200 con datos plausibles: `?limite=10` devolvía el valor por defecto y `?limite=9999` no daba el 422 del tope | **Hecho:** `api_gateway/app/main.py` reenvía `request.url.query` al construir la URL destino. Verificado por el Gateway: `?limite=10`  10 elementos, `?limite=500`  500, `?limite=9999`  422 | Owner técnico del Gateway |
| 16 | Los listados devuelven como máximo **500 filas** (por defecto 200) | Con 932 productos y 1.739 tickets en base, la vista de admin no muestra el total. Es el precio de acotar la consulta: antes devolvían la tabla entera y el endpoint llegó a tardar **más de 90 s** | Paginación explícita en la UI (botón "cargar más" o páginas numeradas) usando el parámetro `limite`, que ya funciona a través del Gateway | Owner técnico de Frontend |

| 17 | `notificacion-service` y `auditoria-service` atienden la API **y consumen RabbitMQ en el mismo proceso**, con un solo pool de conexiones | Bajo carga, el consumidor (que abre una sesión por evento) agota el pool y deja sin conexiones a la API que consulta el usuario. Medido con k6: `PoolTimeout` en `GET /mis-alertas` y circuito de 'notificaciones' abriéndose. Mitigado subiendo el pool a 25+25 y añadiendo el índice compuesto, pero la causa sigue ahí | Separar el consumidor en su propio proceso/contenedor, con su propio pool: una avalancha de eventos no debería poder tumbar la API de lectura | Owner técnico de Notificaciones/Auditoría |
| 18 | La tabla `notificaciones` **crece con el tráfico** y no tiene política de retención | El ADMIN recibe copia de todos los eventos (decisión correcta: supervisa las dos sedes), así que cada evento escribe al menos una fila. Una corrida de carga dejó **46.627** filas. En operación real el volumen es mucho menor, pero crece sin límite | Archivar o borrar las notificaciones leídas con cierta antigüedad (job programado) | Owner técnico de Notificaciones |

| 19 | ~~Los **contadores de Prometheus del Gateway subestiman** con 8 workers~~ —  **CERRADA 18/07/2026** | Cada worker de Gunicorn lleva su propio registro en memoria y `/metrics` devuelve el del que conteste el scrape. Medido: 30 peticiones enviadas, contador reportando 21. Afecta a `gateway_proxy_requests_total`, `retries`, `circuit_opens`, `rate_limit_rejects` y `bulkhead_rejects`, o sea a los paneles de Grafana. Las tendencias siguen siendo válidas; los valores absolutos no. **El ESTADO del breaker sí es correcto** (viene de Redis, ADR-0015) | **Hecho:** modo *multiprocess* de `prometheus_client` activado (`PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus` sobre `tmpfs`), con `multiprocess_mode` en los dos gauges (`max` para el estado del circuito, `livesum` para las llamadas en vuelo). Verificado: 30 enviadas  30 contadas, estable, con los 8 procesos escribiendo | Owner técnico del Gateway / Observabilidad |

---

## Brecha 20 — Tráfico este-oeste sin TLS (aceptada)

**Qué es.** Las llamadas entre el Gateway y los microservicios van en `http://`,
y la conexión a RabbitMQ en `amqp://`. SonarQube las marca como vulnerabilidad
(6 issues, severidad MINOR), y en general tiene razón.

**Por qué se acepta aquí.** Es tráfico **este-oeste** dentro de la red Docker
`shservices-net`, que no publica esos puertos al exterior: ningún byte de esas
conexiones sale del host. El borde público es el Gateway (`:8000`), y es ahí
donde termina TLS un proxy inverso en un despliegue real.

**Qué costaría cerrarla.** Una CA interna, emitir y rotar un certificado por
servicio, y montarlos en cada imagen — mTLS completa. Es exactamente el
problema que resuelve un service mesh (Istio, Linkerd), y queda fuera del
alcance de este proyecto.

**Cómo está marcada.** Con `# NOSONAR` y una nota explicando el motivo en
`api_gateway/app/main.py` (mapa `MICROSERVICIOS`) y en
`ticket_service/app/core/consumer.py` (`RABBITMQ_URL`). Se marcan, no se
ocultan: la decisión queda escrita al lado del código.

**Si esto fuera producción**, el orden sería: (1) TLS en el borde con
certificados reales, (2) políticas de red que impidan alcanzar los servicios
salvo desde el Gateway, y (3) mTLS entre servicios vía mesh.

---

## Brecha 21 — El caos tumba servicios de uno en uno, no en combinación

**Qué es.** `pruebas_k6/caos.py` derriba los servicios **secuencialmente**: cae
uno, se observa, se restaura, y solo entonces cae el siguiente. Nunca se prueban
**dos caídas simultáneas** ni un **orden aleatorio**.

**Por qué importa.** Una caída aislada solo demuestra que el mecanismo de
aislamiento funciona en el caso fácil. Los fallos que de verdad tumban sistemas
suelen ser **combinados**: almacén y facturación a la vez dejan al Gateway con
dos circuitos abiertos y el resto del tráfico compitiendo por los mismos
recursos. Con el guion actual ese escenario nunca se ejercita.

**Qué faltaría.** Un modo `--simultaneos N` que derribe varios a la vez, y un
`--aleatorio` que elija víctima y momento al azar (estilo Chaos Monkey), para
que la prueba no sea siempre el mismo guion conocido.

**Estado.** Identificada y no implementada, por decisión de alcance: el guion
secuencial ya demuestra contención, ausencia de cascada y recuperación
automática, que es lo que exige la S34. La versión combinada queda en el backlog.

---

## Brecha 22 — Cobertura de funcionalidad por servicio

**Qué es.** Cada microservicio cubre su **flujo principal**, pero se queda corto
en operaciones de gestión que un sistema en uso real necesitaría:

| Servicio | Qué falta |
| :-- | :-- |
| almacen | Ajustes de inventario, mermas, transferencias entre sedes, historial de movimientos |
| tickets | Reasignar técnico, reabrir un ticket cerrado, anular con motivo |
| diagnostico | Editar un diagnóstico ya registrado, adjuntar fotos del equipo |
| facturacion | Notas de crédito, anulación de comprobante, cierre de caja diario |
| notificaciones | Marcar todas como leídas, preferencias por usuario |
| auditoria | Exportar la traza a CSV/PDF para una auditoría externa |

**Por qué se aceptó.** El alcance se fijó en el **flujo de negocio de punta a
punta** (recepción → diagnóstico → cobro → entrega) y en la **resiliencia**, que
es lo que evalúa el curso. Añadir CRUD de gestión habría engordado la superficie
sin aportar nada a la nota.

**Estado.** Backlog priorizado por valor de negocio.

---

## Brecha 23 — Alcance del frontend

**Qué es.** La web cubre las pantallas del flujo principal por rol, pero le
faltan piezas que se esperarían de un panel operativo:

- **Sin paginación en la interfaz**: el backend ya la soporta (`?limite=`), pero
  las vistas piden un bloque y lo pintan entero. Con miles de filas se nota.
- **Sin filtros ni búsqueda avanzada** en los listados (por fecha, por estado,
  por técnico).
- **Sin edición**: todo es alta y consulta; no se puede corregir un dato mal
  escrito sin ir a la base de datos.
- **Sin gráficos ni indicadores**: la operación se ve en Grafana, no en la web.
- **Accesibilidad no auditada**: no se ha pasado un validador de contraste ni
  navegación por teclado.
- **Sin pruebas de interfaz**: no hay E2E de navegador (Playwright/Cypress); la
  verificación es de API.

**Por qué se aceptó.** El curso evalúa arquitectura de servicios, no interfaz.
El frontend existe para **demostrar que los flujos funcionan de punta a punta**,
y para eso cumple.

**Estado.** Backlog.

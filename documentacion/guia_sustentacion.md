# Guía de sustentación — respuestas preparadas (S34)

Cada respuesta apunta a evidencia real: un panel de Grafana, un archivo con su
línea, o un resultado medido. No hay nada que memorizar de adorno; todo se puede
demostrar en vivo.

---

## 0. El concepto que lo atraviesa todo: degradación con contrato

**Qué es.** Cuando el sistema no puede atender una petición del todo, tiene tres
formas de reaccionar:

| Reacción | Qué devuelve | ¿Buena? |
| :-- | :-- | :-- |
| **Romperse** | `500` "me caí y no sé por qué", o pierde datos | La peor |
| **Colgarse** | Nada: el cliente espera 30 s en silencio | Igual de mala |
| **Degradarse con contrato** | Un código semántico y documentado que dice qué pasó y qué hacer | La que se busca |

**"Contrato" significa que la respuesta es una promesa documentada.** El cliente
sabe de antemano qué códigos puede recibir y qué significa cada uno (están en
`fichas_contractuales.md`), así que puede programar contra ellos. Lo contrario es
la degradación *silenciosa*: un timeout genérico o un 500 opaco que no dice nada.

**Los contratos de degradación de este sistema:**

| Código | Significado | Cuándo | El cliente debe |
| :-- | :-- | :-- | :-- |
| `503` | Dependencia no disponible | Circuito abierto, servicio caído, pool lleno | Reintentar en unos segundos |
| `504` | Se agotó el tiempo | La dependencia tardó más que el timeout | Reintentar |
| `429` | Demasiadas peticiones | Se superó el rate limit | Esperar (lleva `Retry-After`) |
| `202` | Aceptado, en cola | Escritura que no se pudo entregar → outbox | Nada: se procesa solo, no reintentar |
| `409` | Conflicto de negocio | Ya existe, ya facturado, transición ilegal | Corregir la petición |

**Cómo lo apliqué (con archivo).** La regla es una sola: **el Gateway nunca deja
salir un 500 opaco**. Todo fallo se traduce a un código semántico:

- `api_gateway/app/main.py`, función `_proxy_resiliente`: convierte cualquier
  caída de dependencia en `503`, y un timeout en `504`.
- `_encolar_o_error` (misma archivo): si es una escritura, en vez de fallar la
  guarda en el outbox y responde `202`.
- El rate limit responde `429` con `Retry-After`.
- Los conflictos de negocio (idempotencia, restricciones únicas) responden `409`.

**La prueba medida.** En la corrida de 1M: **36.034 respuestas 503/504/429 (3,8 %)
y CERO errores 500**. Esas 36.034 no son fallos — son 36.034 veces que el sistema
dijo "ahora no puedo, reintenta" en vez de romperse. Y 58.951 escrituras se
salvaron en el outbox: ninguna perdida.

**La frase de una línea:**
> Degradarse con contrato no es fallar — es la alternativa a fallar. El sistema
> no promete "nunca me caigo"; promete "cuando algo va mal, te aviso con un
> código que entiendes y no pierdo tus datos".

---

## 1. Preguntas durante la prueba funcional

*(Responder con la operación que estés ejecutando en ese momento. Ejemplo:
registrar un diagnóstico.)*

| # | Pregunta | Respuesta modelo |
| :-- | :-- | :-- |
| 1 | ¿Qué operación acaba de ejecutarse? | "Registrar un diagnóstico: el técnico anota la falla y reserva un repuesto." |
| 2 | ¿Cuál fue el estado inicial? | "El ticket estaba en `EN_DIAGNOSTICO` (tomado por el técnico)." |
| 3 | ¿Cuál fue el estado final? | "Pasó a `DIAGNOSTICADO`, y el evento lo movió por la cola." |
| 4 | ¿Qué validaciones se aplicaron? | "La sede sale del token, no del cuerpo; el ticket tiene que existir; el stock tiene que alcanzar; y Pydantic valida el formato del payload." |
| 5 | ¿Qué error con datos inválidos? | "Un `422` con el detalle del campo que falta o está mal, no un 500." |
| 6 | ¿Qué no debe duplicarse si el usuario insiste? | "La reserva de stock. Se manda una `Idempotency-Key` derivada (`diag-{idTicket}-{codigo}`); un segundo clic devuelve el mismo resultado sin mover stock otra vez." |
| 7 | ¿Dónde se observa el resultado internamente? | "En PostgreSQL (la fila del ticket y la reserva), en la traza de auditoría, y en Grafana." |
| 8 | ¿Qué evidencia auditable quedó? | "Un evento `DiagnosticoRegistrado.v1` en `auditoria_eventos` con su `trace_id`, persistido, no solo en un log." |

---

## 2. Preguntas de observabilidad — "navega tu evidencia en vivo"

Todas se responden en **Grafana (`:3000`)**, salvo el correlationId que va en
**Dozzle (`:9999`)** o Loki.

| # | Pregunta | Dónde lo enseñas |
| :-- | :-- | :-- |
| 1 | Muéstrame el correlationId | En la respuesta HTTP viene el `trace_id`; en Dozzle/Loki filtras por él y ves toda la operación cruzando servicios. |
| 2 | ¿Qué servicios participaron? | La traza de auditoría lista los eventos con el mismo `trace_id`; también los logs del Gateway. |
| 3 | ¿Cuál fue el servicio más lento? | Panel de latencia por servicio. **Honesto:** lo veo por servicio, no por tramo dentro de una operación — eso requeriría tracing jerárquico (OpenTelemetry), y está en la **brecha 14**. |
| 4 | ¿Dónde se ve el retry? | Panel "Reintentos (retries/s) por servicio". |
| 5 | ¿Dónde se ve el timeout? | Panel "Timeouts (/s) por servicio". |
| 6 | ¿Dónde se ve el evento emitido? | En la traza de auditoría, y en Loki filtrando por `event=`. |
| 7 | ¿Dónde se ve si una cola crece? | Panel "Queue depth — mensajes listos por cola". |
| 8 | ¿Dónde se ve el consumer lag? | Panel "Consumer lag — mensajes sin confirmar". |
| 9 | ¿Dónde se ve el fallback? | Panel "Fallbacks entregados (/s) por servicio". |
| 10 | ¿Dónde se ve el circuito abierto? | Panel "Estado del circuito por servicio" (rojo = OPEN). En Prometheus: `gateway_circuit_state`. |

---

## 3. Matriz de revisión de resiliencia — un mecanismo por pregunta

Todas tienen su archivo y línea en `resiliencia.md`. Aquí la respuesta corta:

| Mecanismo | ¿Cumple? | Respuesta de una línea |
| :-- | :-- | :-- |
| Timeout | Sí | "Corta la espera. Cada servicio tiene su presupuesto (3-5 s); sin él, un servicio lento cuelga una conexión del pool." |
| Retry | Sí | "Reintenta solo lo idempotente o lo que no llegó a ejecutarse; nunca un cobro ya procesado." |
| Backoff | Sí | "3/5/8 s: crece pero no se dispara. Da tiempo a que un contenedor vuelva (~4 s) sin castigar al usuario." |
| Jitter | Sí | "Aleatoriza la espera para que 200 reintentos no vuelvan todos en el mismo instante (manada atronadora)." |
| Idempotencia | Sí | "Clave que se reserva antes de trabajar; el índice único arbitra. Verificado: 3 clics → 1 sola fila." |
| Circuit breaker | Sí | "Deja de llamar a una dependencia enferma tras 3 fallos. Estado en Redis (8 workers). Se cierra solo con la sonda." |
| Bulkhead | Sí | "Cupo de llamadas en vuelo por servicio; la lentitud de uno no arrastra a los sanos. Sin cascada." |
| Backpressure | Sí | "Rechaza en la puerta (429) cuando no puede procesar, en vez de aceptar y morir. Ver nota sobre el límite efectivo (brecha 24)." |
| Buffering | Sí | "Colas durables + outbox absorben el pico. Medido: 175.140 mensajes en cola bajo 1M, ninguno perdido." |
| Dropping/sampling | Sí | "Shedding: con el cupo casi lleno se sacrifica lo de baja prioridad. Y los logs de rutina se muestrean bajo carga." |
| Fallback | Sí | "Respuesta degradada útil: la venta se completa aunque tickets caiga; el 503/202 con contrato en vez de un 500." |

---

## 4. Preguntas puntuales de código — "ubica implementación o configuración"

| # | Pregunta | Dónde está |
| :-- | :-- | :-- |
| 1 | ¿Dónde está la política de timeout? | `api_gateway/app/main.py`, diccionario `TIMEOUTS`. |
| 2 | ¿Dónde está configurado el retry? | `main.py`, `BACKOFF_SEQ = (3, 5, 8)` y `MAX_INTENTOS`. |
| 3 | ¿Dónde está la idempotencia? | `almacen_service/app/api/almacen.py`, helpers `_reservar_clave` / `_cerrar_idempotencia`; tabla `idempotencia_almacen`. |
| 4 | ¿Dónde se registra el correlationId? | `main.py`, `correlation_id_middleware`: lo inyecta a cada petición y lo propaga en cada log. |
| 5 | ¿Dónde se valida el request? | En los `schemas.py` de cada servicio (Pydantic); FastAPI responde `422` si no casa. |
| 6 | ¿Dónde se evita exponer secretos? | `.env` está en `.gitignore`; el outbox NO guarda el JWT (solo cabeceras `X-User-*`); las contraseñas van con bcrypt coste 12. |
| 7 | ¿Dónde se separa negocio de llamadas externas? | El BFF del frontend y el Gateway: la lógica de negocio vive en los servicios, y `_proxy_resiliente` aísla la llamada externa con toda la cadena de resiliencia. |
| 8 | ¿Dónde se traduce el error externo? | `main.py`, `_encolar_o_error` y `app/core/exceptions.py`: cualquier fallo se convierte en 503/504/202, nunca un 500 opaco. |
| 9 | ¿Dónde se emite el evento auditable? | `publicar_evento` en cada servicio → exchange `tickets.eventos`; lo consume `auditoria_service`. |
| 10 | ¿Dónde se define el fallback? | `_encolar_o_error` (outbox → 202) y la respuesta 503 del breaker; métrica `FALLBACKS`. |

---



### Tabla rápida — archivo:línea (verificado hoy)

| # | Pregunta | Archivo:línea |
| :-- | :-- | :-- |
| 1 | Timeout | `api_gateway/app/main.py:120` (`TIMEOUTS`) |
| 2 | Retry | `api_gateway/app/main.py:232` (`BACKOFF_SEQ`), jitter en `:236` |
| 3 | Idempotencia | `almacen_service/app/api/almacen.py:126` (`_reservar_clave`) |
| 4 | CorrelationId | `api_gateway/app/main.py:645` (`correlation_id_middleware`) |
| 5 | Validar request | `*/models/schemas.py` (Pydantic) + `exceptions.py:109` (422) |
| 6 | No exponer secretos | `.gitignore:7` + `api_gateway/app/core/outbox.py:80` |
| 7 | Separar negocio/externo | `api_gateway/app/main.py:371` (`_proxy_resiliente`) |
| 8 | Traducir error externo | `main.py:410` (503) + `exceptions.py:31` (handler global) |
| 9 | Evento auditable | `diagnostico_service/app/core/rabbitmq.py:28` (`publicar_evento`) |
| 10 | Fallback | `api_gateway/app/main.py:619` (`_encolar_o_error`) |

Seis de diez están en `api_gateway/app/main.py`: ten ese archivo abierto y usa
Ctrl+G (ir a línea).

---

## 5. La pregunta final — modelo de respuesta completo

> "Bajo 1 millón de peticiones y con una dependencia crítica fallando, ¿qué se
> degrada primero, cómo lo detectan, qué mecanismo se activa y qué evidencia
> demuestra que el sistema sigue bajo control?"

**Debe incluir: métrica, traza, log, estado de resiliencia, impacto funcional y
acción correctiva.** Respuesta completa, con los seis elementos marcados:

> "Lo probamos de verdad: corrimos 952.701 peticiones en 90 minutos.
>
> **Qué se degrada primero:** almacén. Es el servicio más golpeado porque cada
> diagnóstico y cada venta pasa por él. Bajo esa carga su **pool de conexiones a
> PostgreSQL se satura**.
>
> **Cómo lo detectamos** (métrica + estado de resiliencia): en Grafana, el panel
> de circuitos muestra el de almacén abriéndose — **1.430 aperturas acumuladas**.
> El `gateway_circuit_state` de almacén pasa a 2 (OPEN).
>
> **Qué mecanismo se activa:** el circuit breaker hace **fail-fast**. En cuanto ve
> 3 fallos seguidos, deja de llamar a almacén y responde `503` al instante. Dato
> curioso y contraintuitivo: eso *mejora* la latencia global, porque el p95 bajó
> a 2,7 s — las peticiones a almacén se resuelven en milisegundos en vez de
> esperar el timeout.
>
> **Traza y log:** cada operación lleva su `trace_id`; en Loki filtramos por él y
> vemos la cadena completa, incluida la línea `Circuito OPEN para 'almacen':
> fail-fast`. En la traza de auditoría queda el evento persistido.
>
> **Impacto funcional:** las lecturas a almacén se degradan con contrato (503),
> pero las **escrituras no se pierden**: se desvían al outbox — 58.951 en esta
> corrida — y se entregan cuando almacén se recupera. Los demás servicios (auth,
> tickets, facturas) siguieron con el circuito cerrado: **sin cascada**.
>
> **Evidencia de que sigue bajo control:** cero errores 500, cero pérdida de
> datos, y el circuito de almacén terminó en CLOSED — se recuperó solo por la
> sonda activa, sin que nadie tocara nada.
>
> **Acción correctiva:** identificamos que el timeout del pool de almacén (15 s)
> es mayor que el del Gateway (3 s), así que hay peticiones esperando por
> respuestas que ya nadie va a leer, y eso agrava la saturación. Está documentado
> como brecha 26; la corrección es bajar ese timeout por debajo del del Gateway."

Esa respuesta toca los seis elementos exigidos y **cada afirmación es un número
medido**, no una intención.

---

## 6. Preguntas parecidas a la final (para practicar)

**P: Un consumidor de RabbitMQ muere a mitad de la carga. ¿Qué pasa con los
mensajes que estaba procesando y cómo lo demuestras?**

> "No se pierde ninguno. Los mensajes que tenía sin confirmar (unacked) vuelven a
> la cola como listos y otro consumidor los reprocesa; el ACK solo se manda si el
> handler termina bien. Se ve en Grafana: en la corrida de 1M, el panel de
> consumer lag cae de golpe de 140.000 a casi cero mientras el de queue depth
> sube — son los mismos mensajes cambiando de estado, no desapareciendo. El panel
> 'Consumidores activos' muestra el reconectar entre 1 y 4."

**P: Dos usuarios hacen la misma operación exactamente a la vez. ¿Qué evita el
duplicado y dónde está?**

> "El índice único de la base de datos, no una comprobación en código. La clave
> de idempotencia se INSERTA antes de hacer el trabajo; solo una petición gana y
> las demás chocan con IntegrityError. Lo verificamos con dos técnicos tomando el
> mismo ticket: gana quien pulsó primero, y el otro recibe un 409. Está en
> `asignaciones.py` con la clave primaria en `id_ticket`."

**P: El rate limit dice 20 rps pero mides 200. ¿Miente el número?**

> "No miente, pero el límite efectivo no es 20. El token bucket vive en memoria
> de cada worker y el Gateway corre con 8, así que el límite real es ~160 rps. Lo
> detectamos midiendo, al construir la demo del rate limit, y está documentado
> como brecha 24. Es el mismo problema que tenía el circuit breaker antes de mover
> su estado a Redis; el rate limit se quedó sin migrar. Mientras tanto la
> contención real la aporta el bulkhead, que sí funciona por servicio."

**P: Si todo falla a la vez —tickets, almacén y facturación caídos— y el cajero
cobra, ¿qué pasa?**

> "El cobro se completa igual. La factura se salva en el outbox, y el cierre del
> ticket y el descuento de stock se resuelven por evento cuando los servicios
> vuelven. Lo probamos: con los tres parados, el cobro respondió 201, y al
> levantarlos el ticket pasó a ENTREGADO solo en ~6 s con el stock consumido. El
> dinero entra aunque la infraestructura esté a medias."

---

## 7. Regla de oro para toda la sustentación

Cuando no sepas un número exacto, **di dónde se ve** en vez de inventarlo:
"eso lo tengo medido, está en el panel X de Grafana" o "en el archivo Y".
Y cuando algo NO esté cubierto, **reconócelo con su brecha**: "eso no lo tengo,
es la brecha N, y la solución sería Z". Reconocer un límite con criterio suma más
que fingir que no existe.

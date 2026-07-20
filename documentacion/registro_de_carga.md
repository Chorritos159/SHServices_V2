# Registro de carga — SHServices V2 (S34, Fase 5)

> Formato exacto de la S34 (pág. 24). Generado con `pruebas/03_carga_100k.py`
> / `04_carga_500k.py` / `05_carga_1M.py` (runner `pruebas/lib/carga_nodos.py`).
> **Modo carga — atender TODAS:** durante cada corrida el Gateway se pone en
> modo carga (`ampliar_rate_limit`), que amplía el rate limit y el bulkhead,
> sube los timeouts (`TIMEOUT_FACTOR`) y desactiva el circuit breaker
> (`CIRCUIT_BREAKER_DISABLED`). Así se mide el **throughput real del backend**
> sin que los mecanismos de protección rechacen tráfico (0 rechazos por 429/503).
> Al terminar cada corrida se **restauran** los límites normales.
>
> **Carga MIXTA — todos los servicios, con escrituras** (`--mixto`): ~70%
> lecturas y ~30% **escrituras**, repartidas por todos los servicios:
>
> | Servicio | Lectura | Escritura |
> | :-- | :-- | :-- |
> | tickets | `GET /pendientes` | `POST /` (crear ticket) |
> | almacen | `GET /productos` | `POST /productos` |
> | notificaciones | `GET /mis-alertas` | `POST /marcar-leidas` |
> | diagnosticos | `GET /asignaciones/mias` | `POST /asignaciones/tomar` + `POST /diagnosticos/` *(cadena)* |
> | facturas | — | `POST /facturas/` *(cadena)* |
> | auditoria | `GET /eventos` | *(consume los eventos que generan las escrituras)* |
> | auth | login de cada nodo | — |
>
> La **cadena de negocio** (crear ticket  tomarlo  diagnosticar  cobrar) es
> la única forma de ejercitar diagnósticos y facturación con escrituras
> **válidas** (necesitan un ticket en el estado correcto); va con peso bajo.
> Las escrituras son las que hacen trabajar a **RabbitMQ** (eventos) y a los
> consumidores de auditoría y notificaciones.
>
> Los datos que crea la carga van marcados con el prefijo `CARGA-`; se limpian
> con `python pruebas/limpiar_datos_carga.py --borrar`.

## Metodología (por qué no son conteos literales)

A la tasa real del sistema (Gateway de 1 worker, decenas de rps), completar
1,000,000 de peticiones tomaría horas. En vez de eso, cada nivel corre en una
**ventana de tiempo fija**, con varios **nodos** concurrentes mandando
**bloques** sucesivos (no un solo hilo, no todo de golpe). La etiqueta
100k/500k/1M es el **nivel de carga ofrecida**, no un conteo a cumplir — se
reporta el throughput real sostenido en la ventana. La concurrencia se mantiene
moderada para que, con los límites ampliados, se atiendan **todas** las
peticiones (0% de rechazos) y el resultado mida capacidad, no el limitador.

| Nivel | Nodos | Bloque | Ventana | Prueba |
| :-- | :-- | :-- | :-- | :-- |
| 780 (baseline) | — (20 hilos) | — | ~15 s | `02_carga_780.py` |
| 100k | 96 | 5 | ~9.1 min | `carga_100k.py` |
| 500k | 128 | 5 | ~8.5 min | `carga_500k.py` |
| 1M | 160 | 5 | ~10.5 min | `carga_1M.py` |

## Tabla de registro

| Fase | Throughput | p95 | p99 | Error rate | CPU/Mem (api-gateway) | Queue depth | Resultado |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 780 (baseline, límites normales) | *(pendiente)* | | | | | | |
| 100k | 182.75 rps | 1024 ms | 1327 ms | 0.5% | 709% / 660 MiB | 23337 | Exitosa, procesamiento masivo con auto-healing y sin error de pool. |
| 500k | *(pendiente de corrida)* | | | | | | |
| 1M | *(pendiente de corrida)* | | | | | | |

> La fila **780** es la línea base con los límites NORMALES del Gateway
> (`prueba 02`): su Error rate alto son 429/503 de degradación con contrato
> (backpressure + bulkhead), NO fallos. Las 100k/500k/1M corren con el rate
> limit ampliado para medir el throughput real del backend.
>
> **Cómo se llena esta tabla.** Ninguna columna se inventa:
>
> | Columna | De dónde sale |
> | :-- | :-- |
> | Throughput, p95, p99, Error rate | `python pruebas/resumen_carga.py` (los lee del JSON de cada corrida) |
> | CPU/Mem, Queue depth | `python pruebas/monitor_recursos.py` en una segunda terminal, EN PARALELO a la carga |
> | Resultado | A mano: explica el primer cuello de botella con las métricas de arriba (regla S34) |
>
> `resumen_carga.py` deja la tabla lista para pegar en
> `pruebas/resultados/tabla_registro_carga.md`.
>
> `monitor_recursos.py` muestrea cada 5 s y al final da el **pico** y el
> promedio. Se hace así y no mirando `docker stats` a ojo porque una lectura
> manual da el valor del instante en que miraste, que casi nunca es el pico —
> y el pico es justamente el dato que dice si el Gateway se quedó sin CPU.

## Cuello de botella identificado (corridas previas, diseño anterior)

Antes de este rediseño se corrió una prueba sostenida de conteo literal
(no por ventana de tiempo) durante ~17 min, alcanzando **79,275**
peticiones a un throughput estable de **~85 rps**, con:

- **CPU del Gateway durante la carga:** **~100%** de un núcleo
  (`docker stats`) — el Gateway corre con **1 solo worker Gunicorn** (fix
  de Fase 1: el circuit breaker necesita una única fuente de verdad en
  memoria; ver `matriz-resiliencia.md` §2).
- **`ticket-service` durante la carga:** ~50% CPU — no es el cuello de botella.

**Primer cuello de botella (regla de la S34, pág. 24):** el **Gateway de 1
solo worker** es el límite de throughput, no la base de datos ni
`ticket-service`. Es una limitación **conocida y documentada** (Fase 1): la
alternativa (más workers) requeriría mover el estado del circuit breaker a
un backend compartido (Redis) para no romper su consistencia entre
procesos — evaluado y postergado explícitamente por priorizar la
corrección del mecanismo de resiliencia sobre el throughput bruto en esta
entrega. Este número (~85 rps, 1 núcleo saturado) es la referencia contra
la que se leen los resultados de las corridas por nodos/bloques.

## Referencia: corridas cortas ya verificadas (no reemplazan la tabla, la respaldan)

| Corrida | Total | Configuración | Resultado |
| :-- | :-- | :-- | :-- |
| Humo (límites normales) | 780 | 100 hilos concurrentes | 58×200, 693×429, 29×503 — p95=207ms, p99=259ms. Backpressure conteniendo, Gateway sano después |
| Humo (límites ampliados) | 3,000 | 18 hilos concurrentes | 2,722×200 (90.7%), 278×503 (bulkhead) — p50=208ms, p95=285ms, p99=376ms. Confirma que sin el rate limit, el bulkhead (cupo=12) es el siguiente límite real |

## Queue depth y consumer lag

Visibles en vivo en el dashboard de Grafana (Fase 4,
`grafana/dashboards/resiliencia_s34.json`, fila "RabbitMQ") vía
`rabbitmq_queue_messages_ready` / `rabbitmq_queue_messages_unacked` por
cola. Durante las corridas de carga sobre `GET /tickets` (una lectura
síncrona, no pasa por RabbitMQ) la cola no crece — la publicación de
eventos (`ticket.creado`, etc.) solo ocurre en las escrituras (`POST
/tickets`), que no son el foco de esta corrida de throughput.

---

## El cuello de botella real: el pool de conexiones (2026-07-18)

La corrida de **500k** destapó algo que ninguna prueba anterior había visto:

```
codigos: HTTP 200: 8818  HTTP 201: 4906  HTTP 500: 4  HTTP ERR: 34
```

Cuatro **HTTP 500**. Un 500 significa "falló algo que nadie previó", así que
se fue a buscar al log del servicio:

```
QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30.00
```

**No era carga: era configuración.** Tres problemas encadenados:

1. **Pool por defecto de SQLAlchemy**: `pool_size=5, max_overflow=10` = 15
   conexiones por servicio. Nadie lo había tocado nunca.
2. **`pool_timeout=30s`**, que es *peor* que no tener conexiones: el Gateway
   corta a los 8 s, así que el cliente ya se había ido y el worker seguía 22
   segundos más esperando un hueco, ocupando un hilo para nadie.
3. **PostgreSQL con `max_connections=100`** (el valor de fábrica), mientras 8
   servicios × 15 conexiones = **120 potenciales**. El techo del sistema no era
   la CPU ni la red: era la base de datos quedándose sin sitio.

### Qué se cambió

| Antes | Ahora | Por qué |
| :-- | :-- | :-- |
| `pool_size=5, max_overflow=10` | `10 + 10` = 20 por servicio | Cubre la concurrencia real medida |
| `pool_timeout=30s` | `5s` | Si en 5 s no hay conexión, el servicio está saturado: mejor decirlo rápido |
| `max_connections=100` | `200` | 8 × 20 = 160, más margen para administración |
| Pool agotado  **HTTP 500** | **HTTP 503** + `Retry-After` | Saturación no es avería |

El último punto es el que más importa. Un pool agotado significa **el servicio
está saturado**, que es un estado transitorio y reintentable — exactamente lo
que expresa un 503. Devolver 500 impedía al circuit breaker y al cliente
distinguir "está sobrecargado" de "está roto", y son dos cosas que se atienden
de forma distinta.

### Lección

Las pruebas de carga sirvieron para lo que tienen que servir: **encontraron un
límite que nadie había puesto a propósito**. El sistema no aguantaba menos de
lo esperado por diseño, sino por un valor por defecto que nadie había mirado.

## Segundo hallazgo: un 500 en la carrera de idempotencia (2026-07-18)

Tras arreglar el pool, la corrida de auto-recuperación bajo carga dejó **un
último HTTP 500**:

```
Error no controlado en POST /api/v1/facturas/: 'NoneType' object has no attribute 'id'
```

En `facturacion_service`, el manejador de la carrera de idempotencia daba por
hecho que tras un `IntegrityError` **siempre** existe una factura previa:

```python
except IntegrityError:
    db.rollback()
    existente = db.query(FacturaDB).filter(...).first()
    op.campos["idFactura"] = existente.id      # <- si existente es None, revienta
```

Pero `IntegrityError` no solo lo lanza el choque contra la unicidad de
`id_ticket`: también cualquier otra restricción (un `NOT NULL`, una FK). En
esos casos no hay factura previa que devolver, `existente` es `None` y el
`.id` explotaba en un 500 opaco — justo en el endpoint del **dinero**.

Corregido: si `existente` es `None` se responde **409 legible** y el motivo
real (`exc.orig`) queda en el log para quien opera.

**Verificado:** 8 cobros simultáneos del mismo ticket  `[201 × 8]`, cero 500.

Los dos hallazgos comparten patrón: **código que asumía el camino feliz y solo
falla bajo concurrencia**. Ninguna prueba funcional los habría encontrado; hizo
falta carga real.

---

## Corte por CONTEO, no por ventana (2026-07-18)

Las corridas pasan de "lo que quepa en N segundos" a **completar un número
exacto de peticiones**. El runner acepta `--total` y termina al alcanzarlo;
la ventana de tiempo queda solo como tope de seguridad.

El motivo es de fiabilidad del dato: con ventana fija, el total depende de
cómo esté de ocupada la máquina ese día, así que dos corridas del "mismo"
nivel no son comparables. Con conteo, la cifra es la misma siempre y lo que
varía es el tiempo — que es justo la variable que se quiere medir.

| Nivel | Peticiones | Concurrencia | Duración aprox. |
| :-- | --: | :-- | --: |
| 780 (base) | ~580 | 2 nodos × 8 | ~40 s |
| 100k | **8.000** | 4 nodos × 16 | ~3.5 min |
| 500k | **20.000** | 5 nodos × 18 | ~8.5 min |
| 1M | **25.000** | 6 nodos × 20 | ~10.5 min |

Medido en la 100k tras el cambio: **8.004 exitosas de 8.069 (99.2%)**,
37.2 rps, p95 1.495 ms, **cero errores 500**.

## La corrida de 100.000 REALES (`13_carga_100k_real.py`)

Las etiquetas 100k/500k/1M nombran el **escalón de carga**, no el conteo — y
esa distinción, por bien explicada que esté, siempre deja la duda de "¿y
cuántas mandaste de verdad?".

`pruebas/13_carga_100k_real.py` la responde sin discusión: **completa 100.000
peticiones reales**, contadas una a una, y no para hasta llegar. A ~40 rps son
unos **40-45 minutos**, así que está pensada para dejarla corriendo y volver.
Cada 5 s imprime el avance con porcentaje y minutos restantes:

```
… 34120/100000 (34.1%) ~41 rps  [832s, faltan 65880 -> ~26.8 min]
```

**Qué aporta más allá del conteo.** Es la única corrida lo bastante larga para
enseñar cosas que una ventana de 3 minutos no puede ver:

- si el throughput **se degrada con el tiempo** — una fuga de memoria o de
  conexiones se nota a los 20 minutos, no a los 2 (de hecho así apareció el
  agotamiento del pool);
- si el outbox y los consumidores de RabbitMQ van al día en una sesión larga;
- si la latencia p99 aguanta o se deteriora.

> **Importante antes de lanzarla:** correr
> `python pruebas/limpiar_datos_carga.py --borrar`. En modo mixto, 100.000
> peticiones crean muchísimos tickets y productos, y los listados devuelven
> todo sin paginar. Si se arranca con la base ya llena, la corrida se degrada
> por el VOLUMEN DE DATOS y no por la carga — que es justo lo que no se quiere
> medir.

---

## El generador de carga era el cuello de botella (2026-07-18)

Tras mover el circuit breaker a Redis y escalar el Gateway a **8 workers**
(ADR-0015), se midió otra vez el techo con el endpoint trivial `/health`, que
no toca base de datos ni proxy y por tanto aísla al Gateway:

| Configuración | Throughput |
| :-- | --: |
| 1 worker | 96 rps |
| **8 workers + Redis** | **108 rps** |

**Multiplicar los workers por 8 dio un 12% más, no 12×.** Eso descartaba al
Gateway como cuello de botella y obligaba a buscar en otro sitio.

### La prueba que lo aclaró

Se lanzaron varios procesos generadores **en paralelo** contra el mismo
endpoint. Si el límite fuera del servidor, el total no subiría:

| Generadores | Throughput total |
| --: | --: |
| 1 | 105 rps |
| 2 | 171 rps |
| 4 | **257 rps** — y seguía subiendo |

El total **escala con el número de generadores**, así que el techo que se venía
midiendo era el del **cliente**, no el del sistema. Un único proceso de
`carga_nodos.py` (Python + asyncio) no pasa de ~105 rps.

### Qué significa esto para todas las mediciones anteriores

Los throughputs de este documento —29, 37, 42 rps— **describen al generador
tanto como al sistema**. No son falsos: son el rendimiento *observado con esa
herramienta*. Pero no son el techo del sistema, y presentarlos como tal sería
un error.

Lo que sí se puede afirmar con lo medido:

- El sistema sostiene **al menos 257 rps** en lecturas, sin saturarse.
- Su techo real **no se conoce**, porque no se ha medido con un generador
  capaz de superarlo.
- Las conclusiones sobre **resiliencia** (contención, cero 500, recuperación
  automática, ausencia de cascada) **no se ven afectadas**: esas no dependen
  del volumen, sino de cómo reacciona el sistema al fallo.

### Por qué Python asyncio se queda corto como generador

El generador vive en un solo proceso con GIL: cada respuesta hay que
deserializarla, medirla y contabilizarla en Python, y eso compite con el propio
envío. Herramientas como **k6** (escrita en Go) usan hilos ligeros del runtime
sin GIL y pueden mantener miles de peticiones concurrentes por proceso.

**Es la explicación más probable de que otra implementación reportara ~1.190
rps**: no necesariamente un backend más rápido, sino un generador que no era el
límite. Comparar throughputs medidos con herramientas distintas compara, en
buena parte, las herramientas.

### Cómo cerrar esto correctamente

Dos caminos, ambos honestos:

1. **Varios generadores en paralelo** (lo ya hecho): suma el throughput de N
   procesos. Funciona y no añade dependencias, pero es incómodo de coordinar.
2. **Adoptar k6** para las corridas de alto volumen y dejar los scripts de
   Python para las pruebas funcionales y de caos, donde el volumen no importa
   y sí importa poder escribir lógica de negocio.

---

## Lo que destapó k6: el consumidor ahogando a su propia API (2026-07-18)

Al medir con k6 —que empuja mucho más que el generador de Python— apareció
esto en `notificacion-service`:

```
level="ERROR" service="exception-handler"
message="Pool de conexiones agotado en GET /api/v1/notificaciones/mis-alertas"
errorType="PoolTimeout"  httpStatus=503
```

Y en el Gateway, la consecuencia:

```
level="WARNING" message="Circuito OPEN para 'notificaciones': fail-fast"
```

### Dos causas, y la segunda es de diseño

**1. Una consulta sin el índice adecuado.** `GET /mis-alertas` filtra por
`(rol_destino, leida)` y ordena por `created_at DESC`. Había índices sueltos en
las dos primeras columnas pero **ninguno en `created_at`**, así que PostgreSQL
filtraba y luego **ordenaba en memoria** todo lo que pasara el filtro. Con
**46.627 notificaciones** acumuladas:

```
ANTES:  Bitmap Heap Scan -> 11.139 filas -> top-N heapsort     9.8 ms
DESPUÉS: Index Scan Backward, para en el LIMIT               0.248 ms
```

**40× más rápido** con un índice compuesto `(rol_destino, leida, created_at)`.

**2. El servicio hace doble trabajo con un solo pool.** `notificacion-service`
atiende la API HTTP **y** consume eventos de RabbitMQ en el mismo proceso, y el
consumidor abre una sesión por notificación. Bajo carga, consumidor y API
compiten por las mismas 20 conexiones hasta agotarlas.

Se subió su pool (y el de `auditoria-service`, que también consume) a 25+25.
**La solución de fondo sería separar el consumidor en su propio proceso**, con
su propio pool: así una avalancha de eventos no puede dejar sin conexiones a la
API que consulta el usuario. Queda registrado como brecha.

### Por qué había 46.627 notificaciones

Es efecto directo de la decisión de que **el ADMIN reciba copia de todos los
eventos**. Es correcto funcionalmente —el admin supervisa las dos sedes— pero
significa que cada evento del sistema escribe al menos una fila. Bajo carga
sintética eso se multiplica rápido.

No se cambia la decisión: en operación real el volumen de eventos es órdenes de
magnitud menor. Pero conviene saber que **esa tabla crece con el tráfico** y
necesitará una política de retención (archivar o borrar leídas con antigüedad).

### Resultado tras los dos arreglos

| | Antes | Después |
| :-- | --: | --: |
| Queue depth pico | 101 | **13** |
| Errores 503 | sí (circuito abierto) | **0** |
| Errores 500 | 0 | **0** |

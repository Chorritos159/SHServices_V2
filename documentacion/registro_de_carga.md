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
> La **cadena de negocio** (crear ticket → tomarlo → diagnosticar → cobrar) es
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
| 100k | 3 | 12 | 2 min | `03_carga_100k.py` |
| 500k | 4 | 16 | 5 min | `04_carga_500k.py` |
| 1M | 5 | 16 | 10 min | `05_carga_1M.py` |

## Tabla de registro

| Fase | Throughput | p95 | p99 | Error rate | CPU/Mem (api-gateway) | Queue depth | Resultado |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 780 (baseline, límites normales) | *(pendiente)* | | | | | | |
| 100k | *(pendiente de corrida)* | | | | | | |
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
| Pool agotado → **HTTP 500** | → **HTTP 503** + `Retry-After` | Saturación no es avería |

El último punto es el que más importa. Un pool agotado significa **el servicio
está saturado**, que es un estado transitorio y reintentable — exactamente lo
que expresa un 503. Devolver 500 impedía al circuit breaker y al cliente
distinguir "está sobrecargado" de "está roto", y son dos cosas que se atienden
de forma distinta.

### Lección

Las pruebas de carga sirvieron para lo que tienen que servir: **encontraron un
límite que nadie había puesto a propósito**. El sistema no aguantaba menos de
lo esperado por diseño, sino por un valor por defecto que nadie había mirado.

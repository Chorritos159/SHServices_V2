# ADR-0015 — Circuit Breaker Distribuido con Redis y Escalabilidad Multi-Worker

**Estado:** Aceptada · **Fecha:** 2026-07-18 · **Fase:** S34, Fase 5 (Escalabilidad de Alto Rendimiento)

## Contexto

El Gateway originalmente se limitó a **1 solo worker Gunicorn** (ADR-0008) debido a que el estado de resiliencia (`CircuitBreaker`) se guardaba en memoria. Múltiples workers causaban "parpadeo" de los breakers y discrepancias en Grafana.

Sin embargo, limitar el Gateway a 1 solo worker restringe el throughput del sistema a ~96 rps (CPU de un solo núcleo saturada bajo tráfico rutinario) e impide alcanzar las metas de alta concurrencia demandadas por las pruebas reales mixtas de **100k, 500k y 1M de peticiones** (que requieren un rendimiento sostenido de más de 1190 rps).

Además, las consultas de listados pesados (como `GET /tickets/`) sin límite de paginación saturaban la CPU del backend al serializar miles de registros generados durante las pruebas de carga, degradando el throughput del sistema a ~28 rps y elevando latencias a 4.1s.

## Decisión

1.  **Estado Compartido en Redis:** Refactorizar la clase `CircuitBreaker` en `api_gateway/app/core/resilience.py` para almacenar sus propiedades en Redis. Esto garantiza consistencia distribuida del estado de los breakers entre múltiples procesos.
2.  **Escalamiento a 8 Workers:** Configurar el API Gateway con `--workers 8` (aprovechando la CPU multi-core de los servidores locales i9).
3.  **Límites por Defecto (Paginación Implícita):** Añadir un límite por defecto (`limite = 50`) en las consultas y endpoints de listado (`GET`) de todos los microservicios con estado para prevenir la sobrecarga de serialización en Python y bloqueos de PostgreSQL.
4.  **Resiliencia Autogestionada (Graceful Degradation):** El Circuit Breaker implementa un fallback en memoria automática en caso de que Redis se caiga, garantizando que el sistema nunca deje de funcionar por problemas en la base de datos de caché.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Mantener 1 worker y documentar limitación | No permitiría simular ni validar la respuesta del sistema ante pruebas de nivel de producción de 100k/500k/1M de peticiones en tiempos prácticos (< 15 minutos). |
| Escalar a 8 workers sin Redis | El circuit breaker "parpadearía", permitiendo que peticiones golpeen microservicios caídos, rompiendo la garantía de resiliencia exigida por la S34. |

## Consecuencias

*   **Positivas:**
    *   El **estado** del Circuit Breaker es **consistente entre los 8 workers**:
        ya no "parpadea" ni depende de a qué proceso cayó la petición. Esto es lo
        que desbloquea escalar el Gateway sin perder la garantía de resiliencia,
        y era la condición que ADR-0008 puso para poder hacerlo.
    *   Latencias de listados estables (**67 ms** medidos en `GET /tickets/`
        con 1.739 filas en tabla) gracias al límite por defecto. Antes de
        paginar, ese mismo endpoint llegó a **superar los 90 s** con la base
        cargada de datos de pruebas.
    *   Las pruebas unitarias locales siguen pasando gracias al fallback en
        memoria (no exigen un Redis levantado).
*   **Negativas:**
    *   Nueva dependencia de infraestructura (contenedor de Redis).
    *   Cada evaluación del breaker pasa a ser una llamada de red. Se mitiga
        con `socket_timeout=2.0` y el fallback en memoria, pero deja de ser una
        operación de nanosegundos.

## Los CONTADORES de Prometheus (detectado y CORREGIDO el 2026-07-18)

Redis comparte el **estado** del breaker (abierto/cerrado), y eso resolvió el
parpadeo. Pero los **contadores** de Prometheus siguen viviendo en la memoria
de cada worker:

`gateway_proxy_requests_total`, `gateway_retries_total`,
`gateway_circuit_opens_total`, `gateway_rate_limit_rejects_total`,
`gateway_bulkhead_rejects_total`...

Cada uno de los 8 procesos lleva su propio registro, y `/metrics` devuelve el
del worker que conteste el scrape. **Comprobado:** se mandaron 30 peticiones y
el contador reportó **21**, de forma estable entre scrapes — no es un retraso,
es que solo se ve una fracción.

**Consecuencia para Grafana:** todos los paneles basados en esos contadores
**subestiman** el volumen real. No están "rotos" —las tendencias y las formas
siguen siendo válidas— pero sus valores absolutos no se pueden citar como
cifras del sistema.

Esta ADR afirmaba *"consistencia absoluta del estado del Circuit Breaker en
Grafana"*. Es cierto para el **estado** (viene de Redis) y **falso para los
contadores**.

**Corregido** activando el modo *multiprocess* de `prometheus_client`: los 8
workers escriben sus muestras en `/tmp/prometheus` (un `tmpfs`, porque son
datos efímeros) y el scrape las **agrega**. Los dos *gauges* declaran cómo
combinarse, porque sumarlos no significaría nada:

| Gauge | Modo | Por qué |
| :-- | :-- | :-- |
| `gateway_circuit_state` | `max` | Si CUALQUIER worker lo ve OPEN, el circuito está OPEN. Basta con que un proceso haga fail-fast para que lo esté |
| `gateway_bulkhead_in_flight` | `livesum` | Las llamadas en vuelo SÍ se suman: es el total real de trabajo en curso |

**Verificado:** 30 peticiones enviadas → **30 contadas**, estable entre
scrapes, con los 8 procesos escribiendo. Antes: 21 de 30.

### Dos errores que costaron una iteración cada uno

**Limpiar el directorio desde el código de la app.** `app/main.py` lo importa
CADA worker, así que cada uno borraba los ficheros que los demás ya habían
escrito y los contadores quedaban a cero. Una variable de entorno como guarda
tampoco sirve: cada proceso tiene su propia copia. La limpieza va en el
`command` del contenedor, **antes** de arrancar gunicorn.

**Usar `command: >` con comillas anidadas.** Compose partía mal los argumentos
y gunicorn arrancaba con **todos sus valores por defecto** (`127.0.0.1:8000`,
worker `sync`, 1 worker), ignorando las banderas: el Gateway quedaba
inalcanzable y `unhealthy`. Se pasó a la forma de lista, que entrega cada
argumento tal cual.

## Corrección de una afirmación anterior (2026-07-18)

La primera versión de esta ADR afirmaba que el throughput quedaba *"escalado a
más de 1190 rps de forma legítima"*. **Ese número no estaba medido y no se
sostiene.** Medición posterior sobre esta misma configuración (8 workers +
Redis), con el endpoint trivial `/health` para aislar el Gateway:

| Configuración | Throughput medido |
| :-- | --: |
| 1 worker (ADR-0008) | 96 rps |
| **8 workers + Redis** | **108 rps** |

Multiplicar los workers por 8 dio un **12%** más, no 12×. La causa se
identificó midiendo con varios generadores en paralelo:

| Generadores de carga | Throughput total |
| --: | --: |
| 1 | 105 rps |
| 2 | 171 rps |
| 4 | **257 rps** (sin saturar todavía) |

**El techo que se estaba midiendo era el del generador de carga (Python
asyncio), no el del sistema.** Un único proceso generador no pasa de ~105 rps,
así que cualquier medición hecha con él estaba describiendo al cliente y no al
servidor.

Esto **no invalida la decisión** —el estado compartido en Redis sigue siendo lo
que permite escalar sin romper el breaker, y la paginación sigue siendo
correcta— pero sí obliga a corregir el dato: el throughput real del sistema
está **por encima de 257 rps** y no se conoce su techo, porque haría falta un
generador que no sea el cuello de botella (ver `pruebas_k6/README.md`).

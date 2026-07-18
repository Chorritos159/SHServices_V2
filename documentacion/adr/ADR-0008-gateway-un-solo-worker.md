# ADR-0008 — API Gateway con 1 solo worker Gunicorn

**Estado:** Aceptada · **Fecha:** 2026-07-16 · **Fase:** S34, Fase 1

## Contexto

El Gateway originalmente corría con Gunicorn a 4 workers Uvicorn
(`--workers 4`), pensado para aprovechar varios núcleos bajo carga. Al
implementar el circuit breaker formal (Fase 1), su estado (`CLOSED` /
`HALF_OPEN` / `OPEN`) y las métricas Prometheus asociadas se guardan en
memoria del proceso Python.

En la verificación en vivo con Toxiproxy (cortar el tráfico hacia
`ticket-service` y observar el circuito) se detectó que el estado
"parpadeaba" entre `CLOSED` y `OPEN` de forma inconsistente: cada uno de
los 4 workers Gunicorn es un **proceso de sistema operativo independiente**,
con su propio diccionario de breakers y su propio registro Prometheus.
Una petición podía caer en un worker cuyo breaker nunca vio los fallos que
otro worker sí registró, y cada scrape de `/metrics` reflejaba el estado
de un worker al azar — no un circuit breaker real, sino 4 breakers
independientes por servicio.

## Decisión

Bajar el Gateway a **1 solo worker Gunicorn** (`--workers 1`), garantizando
una única fuente de verdad para el estado del circuit breaker y las
métricas de resiliencia.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Mantener 4 workers, aceptar el parpadeo | El circuit breaker dejaría de ser una garantía real: una fracción del tráfico seguiría golpeando una dependencia enferma mientras otra hace fail-fast |
| Backend de estado compartido (Redis) entre workers | Es la solución correcta a largo plazo, pero agrega una dependencia nueva (Redis), rediseño de `resilience.py` para operaciones atómicas distribuidas, y no era necesaria para demostrar correctamente el mecanismo en el alcance de esta entrega |

## Consecuencias

- **Positivas:** el circuit breaker es una garantía real y consistente;
  las métricas de Grafana (Fase 4) reflejan el estado verdadero del
  sistema, no un promedio ruidoso entre procesos.
- **Negativas:** el throughput máximo del Gateway queda acotado a lo que
  un solo núcleo de CPU puede sostener (~85-90 rps medidos, ver
  `documentacion/registro_de_carga.md`). El Gateway es I/O-bound (reenvía
  llamadas async), así que el costo real es limitado, pero es el primer
  cuello de botella bajo carga sostenida — documentado explícitamente, no
  oculto.
- **Revisión futura:** si el throughput de un despliegue real lo exige, la
  siguiente iteración es mover el estado del breaker a Redis (operaciones
  atómicas `INCR`/`EXPIRE` para consecutivos y ventana de error rate) y
  volver a escalar a varios workers/réplicas — **no** volver a múltiples
  workers en memoria sin ese cambio.

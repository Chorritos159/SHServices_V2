# ADR-0010 — Pruebas de carga por nodos/bloques, ventana de tiempo fija

**Estado:** Aceptada · **Fecha:** 2026-07-16 · **Fase:** S34, Fase 5

## Contexto

La S34 pide un "Registro de carga" con tres niveles (100k / 500k / 1M
peticiones). La primera implementación generaba carga con un pool de
hilos disparando sin parar hasta completar el conteo literal — a la tasa
real medida del sistema (~85-90 rps, ver ADR-0001), completar 500,000
peticiones tomaba 1.5-2 horas, y 1,000,000 tomaba 3-4 horas. Poco práctico
para una corrida de verificación, y desalineado con cómo se generan
cargas realistas (varios orígenes/clientes, no un solo hilo disparando sin
pausa).

## Decisión

Reemplazar el generador por uno que simula varios **nodos** concurrentes
independientes, cada uno mandando **bloques** sucesivos de peticiones (no
un hilo, no todo de golpe), con **backoff escalonado 3s → 5s → 8s +
jitter** entre bloques que topan con 429/503 (sube de nivel; un bloque
limpio lo resetea a 0). La corrida se acota a una **ventana de tiempo
fija** de 10-15 minutos por nivel, no a un conteo. La etiqueta 100k/500k/1M
pasa a representar el **nivel de carga ofrecida** (más nodos, bloques más
grandes en cada nivel), no un número de peticiones a completar:

| Nivel | Nodos | Bloque | Ventana |
|---|---|---|---|
| 100k | 6 | 40 | 10 min |
| 500k | 10 | 80 | 15 min |
| 1M | 15 | 120 | 15 min |

Si un nivel no alcanza su etiqueta dentro de la ventana, el "Registro de
carga" documenta el throughput real sostenido y explica el primer cuello
de botella con métricas — exactamente la regla explícita de la S34 ("si
el sistema llega a su límite, el equipo debe explicar el primer cuello de
botella con métricas"), en vez de forzar una corrida de horas para
alcanzar un número.

## Alternativas consideradas

| Alternativa | Por qué no |
|---|---|
| Mantener el conteo literal, correr en background varias horas | Válido en principio, pero poco práctico para verificar/iterar sobre el diseño de las pruebas; el usuario pidió explícitamente que no tomara "muchooo tiempo" |
| Escalar el throughput real del sistema (más workers del Gateway) para que 500k/1M sean alcanzables en minutos | Contradice ADR-0001: requeriría mover el estado del circuit breaker a Redis, fuera del alcance de esta fase |
| Reducir el conteo objetivo directamente (p. ej. "500k" = 5,000 peticiones reales) | Pierde la trazabilidad con el vocabulario de la S34; la ventana de tiempo + nodos/bloques preserva la semántica de "nivel de carga" sin mentir sobre cuántas peticiones se completaron de verdad |

## Consecuencias

- **Positivas:** cada nivel corre en 10-15 minutos, verificable en una
  sesión de trabajo normal; el patrón de nodos/bloques + backoff
  escalonado es más representativo de tráfico real que un firehose de
  hilos; el "cuello de botella" queda documentado con evidencia en vez de
  asumido.
- **Negativas:** el "Registro de carga" no muestra literalmente 500,000 o
  1,000,000 de peticiones completadas — requiere una nota metodológica
  explícita (ver `documentacion/registro_de_carga.md`) para que la lectura
  de la tabla no se malinterprete como "no se alcanzó el objetivo por una
  falla", cuando en realidad es una decisión de diseño de la prueba.

# Decisiones Arquitectónicas (ADR)

Registro de las decisiones de ingeniería del proyecto. Cada una dice **qué se
decidió, por qué, qué se descartó y qué consecuencias tiene** — incluidas las
malas. Una ADR no se borra ni se reescribe cuando cambia de opinión: se
supersede con una nueva, para que el historial siga siendo legible.

## Decisiones de arquitectura (0001-0007)

Las siete decisiones estructurales del sistema, cada una con su riesgo técnico
identificado y la mitigación aplicada.

| # | Decisión | Riesgo identificado | Estado |
| :-- | :-- | :-- | :-- |
| [0001](ADR-0001-arquitectura-soa-por-capas.md) | Arquitectura SOA por capas | Servicios que mezclan responsabilidades | Mitigado (fichas + 2 responsabilidades reubicadas) |
| [0002](ADR-0002-api-gateway-punto-de-entrada.md) | API Gateway como punto de entrada | Que concentre negocio y sea cuello de botella | Mitigado (sin lógica de negocio; cuello medido) |
| [0003](ADR-0003-contratos-rest-json.md) | Contratos REST/JSON | Contratos ambiguos o mal definidos | Mitigado (OpenAPI generado del código) |
| [0004](ADR-0004-sincrono-solo-en-critico.md) | Síncrono solo en operaciones críticas | Acumulación de latencia en cadenas | Mitigado (timeouts por salto, cadenas ≤3) |
| [0005](ADR-0005-eventos-para-tareas-secundarias.md) | Eventos para tareas secundarias | Eventos duplicados, perdidos o sin traza | Mitigado (idempotencia, durabilidad, `trace_id`) |
| [0006](ADR-0006-hibrido-orquestacion-coreografia.md) | Híbrido orquestación / coreografía | Orquestar de más o no poder rastrear | Mitigado (regla explícita + `correlationId`) |
| [0007](ADR-0007-base-central-por-esquemas-funcionales.md) | Base central por capacidades | Mezcla de datos entre servicios | **Parcial — deuda declarada** |

> La 0007 es la única con la mitigación **no aplicada**: las tablas siguen en el
> esquema `public`. Está escrito así a propósito; el detalle y lo que sí
> contiene el riesgo están en la propia ADR.

## Decisiones de implementación (0008-0014)

Decisiones tomadas durante la construcción, casi siempre a raíz de algo que se
rompió y se investigó.

| # | Decisión | De dónde salió |
| :-- | :-- | :-- |
| [0008](ADR-0008-gateway-un-solo-worker.md) | Gateway con 1 solo worker Gunicorn | El estado del circuit breaker "parpadeaba": 4 workers = 4 breakers independientes |
| [0009](ADR-0009-estrategia-idempotencia.md) | Idempotencia: clave natural vs. `Idempotency-Key` | Reintentos del outbox no debían duplicar cobros ni reservas |
| [0010](ADR-0010-carga-por-nodos-bloques.md) | Carga por nodos/bloques en ventana fija | Completar 1M de peticiones literales tomaría horas |
| [0011](ADR-0011-outbox-transaccional-gateway.md) | Outbox transaccional en el Gateway | Una escritura no se puede perder porque el destino esté caído |
| [0012](ADR-0012-asignaciones-en-diagnostico.md) | Asignaciones en diagnostico-service | Son trabajo del técnico, no del ciclo del ticket |
| [0013](ADR-0013-garantias-en-facturacion.md) | Garantías en facturacion-service | La garantía nace del cobro, no de la entrega |
| [0014](ADR-0014-sonda-activa-circuit-breaker.md) | Sonda activa del circuit breaker | Sin tráfico, un circuito abierto no se cerraba nunca |

## Formato

Todas siguen la misma estructura: **Contexto** (qué problema había),
**Decisión** (qué se hizo), **Alternativas consideradas** (qué se descartó y por
qué) y **Consecuencias** (positivas y negativas). Las 0001-0007 añaden **Riesgo
identificado y mitigación**, que es lo que pide la matriz de decisiones
arquitectónicas del curso.

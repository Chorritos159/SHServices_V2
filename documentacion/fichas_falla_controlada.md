# Fichas de falla controlada — SHServices V2 (S34, Fase 5)

> Formato exacto de la S34 (pág. 30): cada falla se diseña con hipótesis y
> evidencia esperada, y se ejecuta con el sistema **operando** (no en frío).
> Las 6 fichas corresponden a `pruebas/06_caos.py`, corrida el 2026-07-16
> (versión Bash original; migrado a Python puro después, mismo comportamiento).
> Reporte completo: `pruebas/resultados/05_caos_20260716_225158.txt`.

## Ficha A — Servicio caído

| Elemento | Respuesta |
| :-- | :-- |
| Falla inducida | `docker stop almacen-service` con el sistema operando |
| Servicio afectado | `almacen-service` (vía API Gateway) |
| Hipótesis esperada | El circuito abre tras fallos consecutivos y el Gateway deja de intentar contactar al servicio (fail-fast), sin colgarse ni propagar el fallo a otros servicios |
| Métrica observada | `gateway_circuit_state{service="almacen"}`: 0 (CLOSED) → 2 (OPEN) tras 3 fallos consecutivos. 4 llamadas de sondeo devolvieron 503 |
| Estado esperado del negocio | 503 honesto con `circuito` y `trace_id` en el cuerpo — nunca un 500 opaco ni un timeout colgado |
| Tiempo de recuperación esperado | Cooldown de 15 s + arranque del contenedor; sonda HALF_OPEN cierra el circuito sola |
| Evidencia de auditoría | Fail-fast medido en **58 ms** con el circuito abierto (sin tocar la red). Sonda tras `docker start` → HTTP 200, `circuit_state` vuelto a 0 (CLOSED), **sin intervención manual** |

## Ficha B — Latencia artificial

| Elemento | Respuesta |
| :-- | :-- |
| Falla inducida | Toxiproxy: toxina `latency` de 8000 ms en `ticket_proxy` (timeout configurado del Gateway para `tickets`: 3 s) |
| Servicio afectado | `ticket-service` (único servicio detrás de Toxiproxy) |
| Hipótesis esperada | El Gateway corta la espera al presupuesto configurado (504), reintenta una vez en operaciones de lectura, y tras fallos repetidos abre el circuito |
| Métrica observada | Intento 1: HTTP 504 en 6422 ms (timeout + 1 reintento con backoff). Intento 2: HTTP 504 en 3084 ms. Intento 3: HTTP 503 en 63 ms (circuito ya OPEN). `gateway_circuit_state{service="tickets"}`: 0 → 2 |
| Estado esperado del negocio | 504 con `trace_id` en los primeros intentos; 503 con `circuito` una vez abierto — nunca una espera indefinida |
| Tiempo de recuperación esperado | Cooldown de 15 s tras quitar la toxina; sonda HALF_OPEN cierra el circuito |
| Evidencia de auditoría | Sonda tras `DELETE .../toxics/latencia_caos` → HTTP 200, `circuit_state` vuelto a 0 (CLOSED) |

## Ficha C — Cola saturada (bulkhead + shedding)

| Elemento | Respuesta |
| :-- | :-- |
| Falla inducida | Ráfaga de 40 peticiones **realmente concurrentes** (asyncio, no procesos separados) contra `auditoria` (bulkhead: cupo=5, prioridad de lectura = "baja") |
| Servicio afectado | `auditoria-service` (vía Gateway) — el resto de servicios no se ven afectados (bulkhead aislado por servicio) |
| Hipótesis esperada | Al superar el 70% de ocupación del bulkhead, el tráfico de baja prioridad se descarta preventivamente (503) antes de llegar a la saturación dura, protegiendo cupo para escrituras críticas |
| Métrica observada | 4×200, 36×503 — **los 36 rechazos fueron `shed_baja_prioridad`** (ninguno llegó a `saturado`: el shedding actuó antes de la saturación real). `gateway_bulkhead_in_flight{service="auditoria"}` volvió a 0 al terminar (sin fugas de cupo) |
| Estado esperado del negocio | 503 con detalle explícito ("está bajo presión... se descarta para proteger el tráfico crítico") y `Retry-After` |
| Tiempo de recuperación esperado | Inmediato: en cuanto baja la ocupación, el siguiente request pasa sin esperar cooldown (no es un circuit breaker, es contención en tiempo real) |
| Evidencia de auditoría | `gateway_bulkhead_rejects_total{razon="shed_baja_prioridad",service="auditoria"}` = 36 tras la ráfaga |

## Ficha D — Rate limit 429 (backpressure)

| Elemento | Respuesta |
| :-- | :-- |
| Falla inducida | Ráfaga de 100 peticiones realmente concurrentes contra `tickets`, con los límites normales del Gateway (token bucket: 40 de ráfaga, 20/s en régimen) |
| Servicio afectado | Ninguno "afectado" — la protección es del **Gateway mismo**, no de una dependencia |
| Hipótesis esperada | El Gateway rechaza con 429 + `Retry-After` en cuanto se agotan los tokens, antes de gastar tiempo en JWT/RBAC/proxy, protegiendo su propia capacidad de proceso |
| Métrica observada | 17×200, 61×429, 22×503 (el resto cayó en el bulkhead de tickets, cupo=12, también saturado por la misma ráfaga) |
| Estado esperado del negocio | 429 con `Retry-After` calculado a partir de la tasa de repuesto del bucket |
| Tiempo de recuperación esperado | Continuo: el bucket se rellena a 20 tokens/s: no hay "cooldown" fijo |
| Evidencia de auditoría | `gateway_rate_limit_rejects_total` = 61 tras la ráfaga (contador acumulado, Prometheus) |

## Ficha E — Webhook/evento duplicado (idempotencia)

| Elemento | Respuesta |
| :-- | :-- |
| Falla inducida | Mismo `POST /tickets` reenviado dos veces con la **misma `Idempotency-Key`** (simula un reintento del cliente o un redelivery) |
| Servicio afectado | `ticket-service` |
| Hipótesis esperada | El segundo envío devuelve la respuesta original sin crear un segundo ticket |
| Métrica observada | Ambas respuestas devolvieron el mismo `idTicket` (`TICK-LIM-7DF5`) |
| Estado esperado del negocio | 1 sola fila en la tabla `tickets` (verificado también en la Fase 3 con consulta directa a PostgreSQL) |
| Tiempo de recuperación esperado | N/A — no hay degradación que recuperar, es prevención |
| Evidencia de auditoría | Log estructurado `operation=crear_ticket result=duplicado` en `ticket-service` para el segundo envío |

## Fallas de la S34 no cubiertas en esta fase

| Falla (pág. 27 S34) | Por qué no aplica / queda pendiente |
| :-- | :-- |
| Consumidor lento | No hay un mecanismo para regular la velocidad de un consumidor RabbitMQ en este sistema (los consumidores procesan a la velocidad que llegan los mensajes) |
| Base o almacenamiento lento | Requeriría un proxy/mock delante de PostgreSQL (no está en el alcance de esta fase) |
| Error de contrato | Cubierto parcialmente por la validación Pydantic de cada servicio (422 ante payload inválido), pero no se diseñó como ficha de caos explícita |
| Fallo parcial (ejecutar una parte y fallar la siguiente) | El flujo diagnóstico→almacén (`_mover_stock`) ya maneja este caso en el código (try/except por repuesto), pero no se verificó como ficha de caos dedicada en esta fase |

---

## Ficha F — Degradación funcional: la VENTA sobrevive sin ticket-service

**Añadida el 2026-07-18**, junto con la venta de mostrador.

| Campo | Valor |
| :-- | :-- |
| **Falla inyectada** | `docker pause ticket-service` (caída dura: acepta la conexión TCP y no responde nunca) |
| **Operación bajo prueba** | Venta directa de mostrador: 2 unidades de un producto de la sede |
| **Comportamiento esperado** | La venta se completa igual. El ticket es *best-effort* |
| **Mecanismo** | Degradación funcional + outbox del Gateway |

### Por qué esta ficha existe

Las fichas A-E prueban que una falla **no se propaga**. Esta prueba algo
distinto y más exigente: que una falla **no detiene el negocio** cuando la
operación no depende de verdad del servicio caído.

Una venta de mostrador necesita dos cosas: que salga el stock y que el cliente
se lleve su comprobante. El ticket es un registro de conveniencia. Tratarlo
como obligatorio significaría que una caída de `ticket-service` cierra la caja
—y eso no es resiliencia, es acoplamiento disfrazado.

### Resultado medido (2026-07-18)

```
Producto elegido: PRD-003 (23 en stock, S/.80.0)
ticket-service PAUSADO

1. Alta del ticket   -> HTTP 202 (encolado en el outbox); la venta NO se detiene aquí
2. Descuento de stock -> HTTP 200
3. Cobro              -> HTTP 201, comprobante FAC-PIU-6F6B por S/.160.00

OK: VENTA COMPLETADA con ticket-service caído (referencia VENTA-PIU-CAOS...,
    sin ticket). El cliente se llevó su producto y su comprobante.
```

El **202 del paso 1** es la parte interesante y no estaba planeada: el Gateway
no solo dejó pasar la venta, además **encoló el alta del ticket en su outbox**,
así que cuando `ticket-service` vuelve el registro se crea solo. La venta no se
degradó a "se perdió el ticket", sino a "el ticket llega más tarde".

### Qué se restaura al terminar

La prueba hace `docker unpause` en un `finally`, así que el servicio vuelve
aunque la ficha falle a mitad.

---

## Ficha G — Caos BAJO CARGA sostenida (`pruebas/11_caos_bajo_carga.py`)

**Añadida el 2026-07-18.** Es la ficha que faltaba y la más parecida a un
incidente real.

### Por qué existe

Las fichas A-F rompen cosas con el sistema **en reposo**, y las pruebas de
carga 03/04/05 lo miden **sano**. Ninguna respondía la pregunta que de verdad
importa: *¿qué le pasa a la gente que ya está operando cuando un servicio se
cae en mitad de la jornada?*

Esta prueba lanza la carga real (100k / 500k / 1M) y, **sin parar el tráfico**,
va tumbando servicios uno a uno y devolviéndolos, muestreando el estado de los
circuitos cada 5 s para construir una línea de tiempo.

### Los tres criterios

| Criterio | Qué se exige | Por qué |
| :-- | :-- | :-- |
| **Contención** | **Cero respuestas 500** | Un 500 es el sistema perdiendo el control. Toda falla debe salir como 503/504, que son contrato |
| **Continuidad** | ≥50% del tráfico atendido | Con 3 de 7 servicios cayendo por turnos, exigir 100% sería absurdo; lo que no puede pasar es que se caiga todo |
| **Recuperación** | Los 7 circuitos en CLOSED al final | Sin tocar nada a mano: lo cierra la sonda activa (ADR-0014) |

### Resultado medido (2026-07-18, nivel 100k)

```
peticiones enviadas .............. 2775
throughput ....................... 15.3 rps
atendidas con exito .............. 2702  (97.4%)
encoladas en el outbox (202) ..... 130
degradadas con contrato (503) .... 72
ERRORES OPACOS (500) ............. 0
latencia p95 / p99 ............... 1344 / 1656 ms

t+  0s  caidos: ninguno    circuitos: todos CLOSED
t+ 22s  caidos: almacen    circuitos: almacen=OPEN
t+ 60s  caidos: ninguno    circuitos: todos CLOSED     <- recuperado solo
t+ 82s  caidos: tickets    circuitos: tickets=OPEN
t+125s  caidos: ninguno    circuitos: todos CLOSED     <- recuperado solo
t+136s  caidos: facturas   circuitos: facturas=OPEN
t+189s  caidos: ninguno    circuitos: todos CLOSED     <- recuperado solo
```

**Lo que dice ese resultado.** Con tres servicios cayendo por turnos durante la
ventana, el sistema atendió el **97.4%** del tráfico y no produjo **ni un solo
500**. Las 130 escrituras que llegaron durante las caídas no se perdieron:
quedaron en el outbox y se entregaron solas. Y en la línea de tiempo se ve que
**solo se abre el circuito del servicio caído** — los otros seis siguen
cerrados, que es la definición de "no hay cascada".

### Un fallo de la propia prueba, corregido

La primera versión leía el estado final de los circuitos **después** de
`restaurar_rate_limit()`, que reinicia el Gateway y pone los contadores a cero.
El resultado era un diccionario vacío y el criterio de recuperación pasaba
siempre: un falso OK. Ahora la lectura se toma antes del reinicio, y si no se
puede leer se marca como **fallo** en vez de darlo por bueno — un criterio que
no se puede verificar no es un criterio aprobado.

---

## Ficha H — Auto-recuperación: ¿cuánto tarda en curarse solo?

**Añadida el 2026-07-18.** `pruebas/12_autorecuperacion.py`

### Por qué existe

Las fichas anteriores mantienen el servicio caído un tiempo fijo para observar
la degradación. Esta hace lo contrario: **mata el proceso y no vuelve a tocar
nada**. Solo mide tiempos.

Es la pregunta de quien opera el sistema: *si se cae a las 3 de la mañana y
nadie lo mira, ¿en cuánto vuelve?* Decir "se recupera automáticamente" no es
una respuesta; un número sí.

Se usa `POST /_chaos/crash` y no `docker stop` **a propósito**: `docker stop`
es una parada ordenada y Docker NO dispara `restart: always` (entiende que se
lo pediste tú). El endpoint mata el proceso con `os._exit(1)`, que es una caída
de verdad.

### Resultado medido (2026-07-18)

| Servicio | Docker lo revive | `/health` responde | Circuito a CLOSED | **Total** |
| :-- | --: | --: | --: | --: |
| almacen | 0.1 s | 1.1 s | 0.3 s | **6.1 s** |
| tickets | 0.1 s | 1.1 s | 0.3 s | **6.0 s** |
| diagnosticos | 0.1 s | 1.2 s | 0.3 s | **6.2 s** |
| facturas | 0.1 s | 1.1 s | 0.3 s | **6.0 s** |
| auditoria | 0.1 s | 1.1 s | 0.3 s | **6.0 s** |

**Peor caso 6.2 s. Promedio 6.1 s.** Los cinco, sin que nadie ejecutara un
solo comando.

### Cómo leer esos 6 segundos

El desglose importa más que el total:

- **0.1 s** — Docker detecta la muerte y relanza el contenedor. Es
  `restart: always` haciendo su trabajo.
- **1.1 s** — el proceso arranca, conecta a PostgreSQL y responde `/health`.
- **0.3 s** — el circuito vuelve a CLOSED en cuanto la sonda activa confirma
  que el servicio responde (ADR-0014).
- El resto hasta los 6 s es el margen de la propia prueba entre comprobaciones.

**Este es el número que sostiene el objetivo de disponibilidad de
`documentacion/sla.md`.** Sin él, ese 99% sería una cifra inventada: con
~6 s por caída, harían falta unas 87 caídas al mes para agotar el presupuesto
de error del nivel alto.

### Ficha H bis — el mismo número, pero bajo carga

`python pruebas/12_autorecuperacion.py --nivel 500k`

Medir la recuperación con el sistema **en reposo** da el mejor caso y lo
presenta como si fuera el habitual: un proceso arranca mucho más rápido en una
máquina que no está haciendo nada. Con `--nivel` el sistema se cura **mientras
atiende tráfico real**, que es lo que pasaría de verdad.

**La diferencia no es pequeña** (medido 2026-07-18, nivel 100k):

| | En reposo | Bajo carga | |
| :-- | --: | --: | :-- |
| Docker revive el contenedor | 0.1 s | 0.1 s | igual (no depende de la carga) |
| `/health` responde | 1.1 s | 2.0 s | el arranque compite por CPU |
| Circuito vuelve a CLOSED | 0.3 s | **11.5 s** | la sonda espera el cooldown de 15 s |
| **Total** | **6.1 s** | **19.0 s** | **3× más** |

El tramo que se dispara es el del circuito, y tiene explicación: en reposo casi
no había tráfico, así que el circuito apenas llegó a abrirse y cerró en cuanto
la sonda lo tocó. Bajo carga el circuito **sí abre de verdad** (hay peticiones
reales fallando) y entonces hay que esperar el cooldown completo antes de que
la sonda pruebe.

**Los 19 s son el número defendible**, no los 6. Si alguien pregunta cuánto
tarda el sistema en recuperarse solo, la respuesta honesta es "unos 19 segundos
con tráfico encima", no el mejor caso de laboratorio.

Con ese dato, agotar el presupuesto de error mensual del nivel alto (99%)
requeriría unas 23 caídas al mes.

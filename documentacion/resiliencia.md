# Resiliencia — los 12 mecanismos, dónde están y por qué esos valores

Cada mecanismo indica **servicio / carpeta**, el **archivo y la línea** donde
vive, y **por qué se eligió ese número**. Los valores no son adornos: casi todos
salieron de una medición o de un fallo real que se documentó en su momento.

> Las líneas son las del commit en que se escribió este documento. Si el código
> se mueve, búscalo por el nombre de la constante, que sí es estable.

---

## 1. Timeout

| | |
|---|---|
| **Servicio / carpeta** | `api_gateway/app/main.py` |
| **Dónde** | `TIMEOUTS` (línea 97), aplicado en línea 357 y usado en la llamada de línea 396 |

```python
TIMEOUTS = {
    "auth": 3.0, "tickets": 3.0, "almacen": 3.0, "diagnosticos": 5.0,
    "facturas": 4.0, "auditoria": 3.0, "notificaciones": 3.0,
}
TIMEOUT_DEFAULT = 5.0
```

**Por qué esos tiempos.** No son iguales a propósito: cada uno se fijó por lo que
hace la operación más lenta de ese servicio.

- **3 s** para lecturas y operaciones simples (auth, tickets, almacén,
  auditoría, notificaciones). Un login o un listado que tarde más de 3 s ya es
  una anomalía, no lentitud normal.
- **5 s para diagnósticos** porque registrar un diagnóstico llama *a su vez* a
  almacén para reservar cada repuesto (`diagnostico.py` línea 88, con su propio
  `timeout=5.0`). Necesita más presupuesto que sus dependencias, o cortaría
  antes de que la cadena termine.
- **4 s para facturas** porque emitir el comprobante escribe factura y garantía
  en la misma transacción.

Sin timeout, un servicio lento no falla: **se queda colgado ocupando una conexión
del pool**, y ese es el modo de fallo que de verdad tumba el sistema (lo vimos
pasar con almacén cuando su conexión a RabbitMQ se quedó muerta).

---

## 2. Retry + backoff

| | |
|---|---|
| **Servicio / carpeta** | `api_gateway/app/main.py` y `api_gateway/app/core/outbox.py` |
| **Dónde** | `BACKOFF_SEQ` (línea 209), `MAX_INTENTOS` (línea 210); outbox: `_backoff()` (línea 124) |

```python
BACKOFF_SEQ = (3.0, 5.0, 8.0)
MAX_INTENTOS = len(BACKOFF_SEQ) + 1   # 4 intentos = 3 esperas
```

**Por qué 3/5/8 y no 1/2/4.** La secuencia crece pero no se dispara: cuatro
intentos suman ~16 s de ventana, que es tiempo de sobra para que un servicio se
reinicie (medimos ~4 s para que un contenedor vuelva a responder), sin que el
usuario se quede esperando medio minuto. Un backoff exponencial clásico
(1/2/4/8/16) alargaría demasiado el peor caso para una operación interactiva.

**Solo se reintenta lo idempotente o lo que no llegó a ejecutarse.** Reintentar
un cobro que sí se procesó sería peor que el fallo original; por eso los
reintentos van de la mano de las claves de idempotencia del punto 4.

---

## 3. Jitter

| | |
|---|---|
| **Servicio / carpeta** | `api_gateway/app/main.py` |
| **Dónde** | `_backoff_jitter()` (línea 213) |

**Por qué.** Si 200 peticiones fallan a la vez porque un servicio se cayó, todas
esperarían exactamente 3 s y **volverían todas juntas en el mismo instante**: el
servicio que acaba de levantarse recibe de golpe la misma avalancha que lo tumbó.
Es el efecto "manada atronadora". El jitter añade una fracción aleatoria a cada
espera para que los reintentos se repartan en el tiempo en vez de sincronizarse.

---

## 4. Idempotencia

| | |
|---|---|
| **Servicios / carpetas** | `almacen_service`, `diagnostico_service`, `facturacion_service`, `api_gateway` |
| **Dónde** | `almacen_service/app/api/almacen.py`: helpers `_respuesta_idempotente()` (línea 123) y `_guardar_idempotencia()` (línea 139), aplicados en `crear_producto`, `reservar_stock`, `descontar_stock` y `descontar_venta`. Modelo: `almacen_service/app/models/idempotencia.py` (tabla `idempotencia_almacen`). Equivalente en `diagnostico_service/app/models/idempotencia.py` |

**Qué problema resuelve, con los dos casos reales que lo motivaron:**

- **Alta de producto duplicada.** Si almacén se caía entre el `commit` y la
  respuesta, el cliente reintentaba y el producto quedaba dado de alta **dos
  veces**. Verificado tras el arreglo: dos peticiones con la misma clave 
  `201` y `201`, mismo código `REP-018`, **una sola fila**.
- **Stock descontado varias veces.** El técnico pulsaba varias veces "agregar
  repuesto" y cada pulsación movía stock. Verificado: tres clics con la misma
  clave  stock 20  **18**, no 14.

**Detalle de diseño que importa.** La clave que manda el diagnóstico al reservar
es **derivada, no aleatoria**: `diag-{idTicket}-{codigo}`
(`diagnostico_service/app/api/diagnostico.py`, línea ~95). Si fuera un UUID
nuevo en cada reintento, la idempotencia no serviría de nada — cada intento
parecería una operación distinta.

El registro de la clave se guarda **después** del commit del efecto: si fallara
al guardarla, es preferible perder la protección que perder una venta ya
confirmada.

---

## 5. Circuit Breaker

| | |
|---|---|
| **Servicio / carpeta** | `api_gateway/app/core/resilience.py` |
| **Dónde** | `CircuitBreaker.__init__` (líneas 31-32); estado compartido en Redis (ADR-0015) |

```python
umbral_consecutivos=3, ventana_seg=30.0,
min_muestras=4, umbral_error_rate=0.5, cooldown_seg=15.0
```

**Por qué esos umbrales.**

- **3 fallos seguidos**: uno o dos pueden ser un error puntual; tres seguidos ya
  es una dependencia enferma. Menos de 3 daría falsos positivos constantes.
- **50 % de error con mínimo 4 muestras**: el mínimo evita que dos peticiones
  desafortunadas abran el circuito por un "100 % de error" sobre una muestra
  ridícula.
- **15 s de cooldown**: da margen a que un contenedor se reinicie (~4 s medidos)
  sin dejar el circuito abierto de más.

**Por qué en Redis y no en memoria.** El Gateway corre con 8 workers. Con estado
local, cada worker tenía su propia idea del circuito y el estado "parpadeaba".

**Sonda activa** (`main.py` línea 516, `SONDA_BREAKER_INTERVALO_S = 5`): un
breaker clásico solo cierra si llega tráfico real. Si el servicio se cae de
madrugada, el circuito se quedaría abierto indefinidamente pese a estar sano. La
sonda prueba cada 5 s **por la misma ruta que el tráfico real**, para que lo que
comprueba sea exactamente lo que vive el usuario. Medido: el circuito se cierra
solo en ~16 s.

---

## 6. Bulkhead

| | |
|---|---|
| **Servicio / carpeta** | `api_gateway/app/main.py` |
| **Dónde** | `BULKHEAD_LIMITES` (línea 267), `BULKHEADS` (línea 286) |

```python
BULKHEAD_LIMITES = {
    "auth": 8, "tickets": 12, "almacen": 8, "diagnosticos": 8,
    "facturas": 8, "auditoria": 5, "notificaciones": 5,
}
```

**Por qué esos cupos.** Es un reparto por uso real, no un número global:
`tickets` recibe **12** por ser el más transitado (recepción + técnico +
garantías); `auditoria` y `notificaciones` **5** por ser de lectura y soporte.

**Qué evita.** Sin mamparo, un servicio lento acapara todas las conexiones
salientes del Gateway y **arrastra a los servicios sanos**. Con cupo por
servicio, la lentitud de uno se queda contenida en su compartimento: los demás
siguen atendiendo. Es exactamente la ausencia de cascada que verifica la prueba
de caos.

---

## 7. Backpressure (rate limit)

| | |
|---|---|
| **Servicio / carpeta** | `api_gateway/app/core/ratelimit.py`, configurado en `main.py` |
| **Dónde** | `RATE_LIMITER = TokenBucket(...)` (líneas 298-300) |

```python
capacidad = RATE_LIMIT_BURST (40)
tasa_por_seg = RATE_LIMIT_RPS (20)
```

**Por qué 20 rps con ráfaga de 40.** Cinco usuarios reales (2 recepciones, 2
técnicos, 1 admin) no generan ni 5 rps sostenidas, así que **20 rps es ~3× la
demanda real** y deja holgura. La ráfaga de 40 absorbe picos legítimos (varios
usuarios pulsando a la vez) sin castigar el uso normal.

Devuelve **429**, que es una respuesta con contrato: le dice al cliente "vuelve a
intentarlo", no "me rompí".

---

## 8. Buffering

| | |
|---|---|
| **Servicios / carpetas** | RabbitMQ (`docker-compose.yml`) + `api_gateway/app/core/outbox.py` |
| **Dónde** | Colas durables: `ticket_service/app/core/consumer.py` (`tickets_estado_queue`), `notificacion_service/app/core/consumer.py` línea 119 (`notificaciones_queue`). Outbox: `INTERVALO_DRENAJE_S = 3` (línea 16) |

**Dos capas de amortiguación:**

- **Colas durables de RabbitMQ** (`durable=True` en exchange y cola): absorben
  los picos. Medido en la corrida de 100k: la cola llegó a **20.620 mensajes** y
  drenó sola hasta cero. El sistema no rechazó ni perdió eventos — los encoló.
- **Outbox del Gateway**: si una escritura no se puede entregar, se guarda y se
  reintenta cada 3 s. El usuario recibe un **202 "en cola"**, no un error.

Esto es lo que hace que el SLA de *integridad* sea más fuerte que el de
*disponibilidad*: se puede incumplir la disponibilidad sin perder un solo dato.

---

## 9. Dropping / Sampling

| | |
|---|---|
| **Servicio / carpeta** | `api_gateway/app/main.py` |
| **Dónde** | Shedding: `_RAZONES_BULKHEAD = ("saturado", "shed_baja_prioridad")` (línea 131) y umbral de ocupación (línea ~289). Muestreo de logs: líneas 318-322 |

**Dos cosas distintas que suelen confundirse:**

- **Shedding de peticiones**: por encima del umbral de ocupación, el bulkhead
  todavía tiene cupo técnico pero **lo reserva para tráfico de prioridad alta**
  y rechaza preventivamente el de baja. Se prefiere sacrificar lo prescindible
  antes que degradar lo crítico.
- **Muestreo de logs**: bajo carga se registra 1 de cada N logs de rutina. Los
  **warnings y errores nunca se muestrean** (circuito abierto, timeout,
  fallback): se loguean siempre. Sería absurdo perder justo la evidencia del
  fallo por ahorrar disco.

---

## 10. Fallback

| | |
|---|---|
| **Servicios / carpetas** | `api_gateway/app/main.py`; BFF en `frontend/src/app/api/ventas/route.ts` |
| **Dónde** | Métrica `FALLBACKS` (línea 136); respuesta degradada del breaker; venta degradada en `ventas/route.ts` líneas 83-94 |

**El caso de negocio que lo justifica.** Si `ticket-service` está caído, la venta
de mostrador **se completa igual**: se descuenta el stock, se emite el
comprobante y se avisa al cajero de que el ticket se creará solo cuando el
servicio vuelva. Verificado tumbando el proxy de tickets con Toxiproxy: la venta
respondió `201` con `FAC-PIU-FDF72F02D04C` sobre `VENTA-PIU-807A10AD`.

Un fallback no es "fingir que todo va bien": es **decidir qué parte del negocio
puede seguir** y decirlo con claridad.

---

## 11. Queue depth

| | |
|---|---|
| **Dónde se ve** | Grafana, panel *Queue depth — mensajes listos por cola*; API de RabbitMQ en `http://localhost:15672/api/queues` |
| **Instrumentación** | Muestreador de `pruebas_k6/correr.py`, que lo imprime en vivo durante la carga |

**Para qué sirve.** Es el indicador que **delata el cuello de botella real** del
sistema. En la corrida de 100k, con la CPU en 518 % de 1600 % disponibles, la
cola creció hasta 20.620: la máquina sobraba, lo que no daba abasto eran los
consumidores. Sin esta métrica, la conclusión habría sido "falta CPU", que es
falsa.

Una cola que **crece y luego drena** es sano (absorción). Una cola que crece y
**no baja** es un consumidor muerto.

---

## 12. Consumer lag

| | |
|---|---|
| **Dónde se ve** | Grafana, paneles *Consumer lag (mensajes sin confirmar)* y *Consumidores activos por cola* |

**Diferencia con queue depth, que es la que importa.** *Queue depth* son los
mensajes esperando; *consumer lag* son los **entregados pero aún sin confirmar
(unacked)**. Un lag alto con la cola vacía significa que los consumidores
recibieron el trabajo pero no lo terminan — están atascados, no ociosos.

El panel *Consumidores activos* marcó **1 por cola** durante la carga: ahí está
la explicación de por qué el sistema se estabiliza en ~200 rps. Escalar
consumidores es la siguiente palanca, y está identificada gracias a esta métrica.

---

## Resumen

| # | Mecanismo | Servicio / carpeta | Archivo:línea |
|---|---|---|---|
| 1 | Timeout | api_gateway | `app/main.py:97,357` |
| 2 | Retry + backoff | api_gateway | `app/main.py:209` · `core/outbox.py:124` |
| 3 | Jitter | api_gateway | `app/main.py:213` |
| 4 | Idempotencia | almacen, diagnostico, facturacion | `almacen/app/api/almacen.py:123,139` |
| 5 | Circuit Breaker | api_gateway | `core/resilience.py:31` · sonda `main.py:516` |
| 6 | Bulkhead | api_gateway | `app/main.py:267,286` |
| 7 | Backpressure | api_gateway | `app/main.py:298` · `core/ratelimit.py` |
| 8 | Buffering | RabbitMQ + gateway | `core/outbox.py:16` · consumidores `durable=True` |
| 9 | Dropping / Sampling | api_gateway | `app/main.py:131,318` |
| 10 | Fallback | api_gateway + BFF | `app/main.py:136` · `ventas/route.ts:83` |
| 11 | Queue depth | RabbitMQ + Grafana | panel *Queue depth* |
| 12 | Consumer lag | RabbitMQ + Grafana | panel *Consumer lag* |

**Cómo demostrarlos en vivo:** `python pruebas/13_resiliencia_en_vivo.py`
(4 demos cortas: sonda activa, timeout+retry, bulkhead y respawn de worker).
Para verlos bajo carga real con servicios cayéndose:
`python pruebas_k6/caos.py --fase 100k --vus 200`.

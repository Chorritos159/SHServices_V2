# SLA / SLO — SHServices V2

> Acuerdo de nivel de servicio del sistema de soporte técnico multi-sede.
> Los números **no son aspiracionales**: salen de lo medido en las pruebas de
> carga (`registro_de_carga.md`) y de los límites realmente configurados en el
> código. Última revisión: 2026-07-20.

## 1. Alcance y contexto (por qué estos números y no "99.99%")

Un SLA honesto describe lo que la arquitectura **puede sostener**, no lo que
suena bien. Esta instalación tiene tres condicionantes que acotan el máximo
alcanzable:

| Condicionante | Efecto sobre el SLA |
| :-- | :-- |
| **Un solo host** (Docker Compose, sin réplicas) | No hay tolerancia a fallo de infraestructura: si el host cae, cae todo |
| **Consumidores únicos por cola** | 1 consumidor en cada cola de RabbitMQ; es el primer cuello de botella. El techo medido con k6 es de ~200 rps sostenidos, y lo que lo limita no es la CPU (pico del 518 % sobre 1600 % disponibles) sino que los consumidores no drenan al ritmo que el Gateway encola |
| **Sin alta disponibilidad de datos** | PostgreSQL de instancia única, sin réplica ni failover |

Por eso el objetivo es **99,0 % mensual** ("dos nueves") para lo crítico y no
99,9 %. Prometer 99,9 % (43 min de caída al mes) con un único gateway sin
réplicas sería un SLA que la arquitectura no puede cumplir.

## 2. Disponibilidad comprometida

El objetivo se fija por **criticidad** del servicio (misma clasificación que las
fichas de `catalogo-servicios.md`):

| Servicio | Criticidad | Disponibilidad objetivo | Caída máx./mes | Justificación |
| :-- | :-- | :-- | :-- | :-- |
| api-gateway | Alta | **99,0 %** | 7 h 18 min | Punto único de entrada; su caída es total |
| auth-service | Alta | **99,0 %** | 7 h 18 min | Sin token no hay operación |
| ticket-service | Alta | **99,0 %** | 7 h 18 min | Entrada del negocio (recepción) |
| facturacion-service | Alta | **99,0 %** | 7 h 18 min | Cobro y garantías: impacto económico directo |
| diagnostico-service | Media | **98,5 %** | 11 h | El técnico puede seguir con "Mis Tickets" ya tomados |
| almacen-service | Media | **98,5 %** | 11 h | Bloquea reservas, no la recepción de equipos |
| auditoria-service | Media | **98,5 %** | 11 h | No frena la operación; sí la evidencia (los eventos quedan en cola) |
| notificacion-service | Baja | **97,0 %** | 22 h | Degrada la comodidad, no el flujo principal |

**Medición:** ventana mensual, sobre el `GET /health` de cada servicio scrapeado
por Prometheus. Se considera "no disponible" un servicio con `status != UP`
durante más de 1 minuto consecutivo.

**Exclusiones (no consumen presupuesto de error):** ventanas de mantenimiento
anunciadas, fallas inducidas a propósito en pruebas de caos (`pruebas/06`, `10`,
`/_chaos/crash`) y caídas del host/Docker ajenas al sistema.

## 3. Latencia (SLO)

Objetivos por percentil, con la carga real esperada del negocio (≤ 20 rps,
5 usuarios concurrentes entre las dos sedes):

| Operación | p95 objetivo | p99 objetivo | Medido |
| :-- | :-- | :-- | :-- |
| Lecturas (listados, consultas) | **< 800 ms** | < 1,2 s | p95 490–672 ms |
| Escrituras (ticket, diagnóstico, cobro) | **< 1,5 s** | < 2,5 s | p95 ~930 ms en carga mixta |
| Consulta puntual sin carga | < 100 ms | < 200 ms | ~35 ms |

**Degradación aceptada bajo carga alta** (por encima de ~40 rps, fuera del
régimen normal): p95 hasta **3 s** con error rate < 1 %.

**Medición real con k6** (100 000 peticiones, 200 usuarios virtuales, 8,4 min):

| Métrica | Valor medido | Objetivo | Veredicto |
| :-- | :-- | :-- | :-- |
| Throughput sostenido | 203 rps | ≥ 20 rps (régimen de negocio) | Cumple — 10× la demanda de diseño |
| p95 | 2 199 ms | < 3 s en carga alta | Cumple |
| p99 | 3 053 ms | < 5 s en carga alta | Cumple |
| Error rate (5xx) | **0,00 %** | < 1 % | Cumple |
| Degradadas con contrato (503/504/429) | 1 131 (1,4 %) | < 5 % | Cumple — son respuestas con contrato, no caídas |
| Escrituras salvadas por el outbox | 1 008 | 0 pérdidas | Cumple — ninguna perdida |
| Pérdida de datos | 0 | 0 | Cumple |

El p95 de 2,2 s se obtiene a **10 veces el régimen normal** (20 rps): la
degradación es proporcional y predecible, no un colapso.

**Comportamiento observado a nivel 1M.** Por encima de ~200 rps el pool de
conexiones de `almacen-service` se agota, su circuito abre y el Gateway hace
fail-fast. En ese punto el SLA de **disponibilidad** se incumple para ese
servicio, pero el de **integridad no**: las escrituras se desvían al outbox
(21 781 en esa corrida) y ninguna se pierde. Es el límite real de esta
instalación con un solo host, y está documentado como tal en vez de presentarse
como capacidad alcanzable.

## 4. Rate limiting: qué es y por qué existe

**Configuración:** token bucket global en el Gateway — **20 req/s sostenidas,
ráfaga de 40**. Al superarlo: `429 Too Many Requests` + cabecera `Retry-After`.

**Por qué está y por qué con esos números:**

1. **Protege al Gateway de sí mismo.** El Gateway corre con **8 workers** y su
   capacidad real medida es de ~200 rps. Sin límite, una ráfaga lo satura, la
   latencia se dispara para *todos* los servicios y el sistema colapsa sin señal
   previa — el peor resultado posible según la S34 ("colapso sin señal previa =
   observabilidad insuficiente").
2. **20 rps es ~3× la demanda real del negocio.** Cinco usuarios (2 recepciones,
   2 técnicos, 1 admin) no generan ni 5 rps sostenidas. El límite deja holgura
   amplia sin permitir que un cliente descontrolado tumbe el servicio.
3. **La ráfaga de 40 absorbe picos legítimos** (varias pestañas abriendo
   listados a la vez) sin castigar al usuario real.
4. **Rechazar explícito es mejor que degradar en silencio.** Un `429` con
   `Retry-After` es *backpressure*: el cliente sabe qué pasó y cuándo reintentar.
   Un timeout genérico no dice nada.

**De dónde sale exactamente el 20.** No es un número redondo elegido al azar:

| Dato | Valor | Fuente |
| :-- | :-- | :-- |
| Usuarios concurrentes reales | 5 (2 recepciones, 2 técnicos, 1 admin) | Alcance del negocio |
| Peticiones por usuario en uso activo | ~1 cada segundo | Un listado y una acción por pantalla |
| Demanda real estimada | **~5 rps** | 5 × 1 |
| Margen de seguridad aplicado | ×4 | Para picos y crecimiento |
| **Límite configurado** | **20 rps** | 5 × 4 |
| Ráfaga permitida | 40 (2× el límite) | Absorbe un pico de 2 s sin castigar |

El criterio es proteger **sin estorbar**: el límite tiene que estar muy por
encima del uso legítimo y muy por debajo de lo que tumba el sistema. Con 20 rps
hay un factor 4 de holgura frente al uso real y un factor 10 de margen frente a
la capacidad medida (~200 rps).

**Consecuencia asumida:** las pruebas de carga (100k/500k/1M) **amplían
temporalmente** el rate limit y el bulkhead, porque su objetivo es medir la
capacidad real del backend y no el techo del propio limitador. Se restauran al
terminar cada corrida (ver `registro_de_carga.md`).

### Limitación conocida: el límite efectivo no es 20 rps

Hay que decirlo porque afecta a lo anterior. El token bucket vive **en memoria
de cada worker** y el Gateway corre con **8**, así que cada uno lleva su propia
cuenta: el límite efectivo es **~8 × 20 = 160 rps**, no los 20 configurados.

Se detectó midiendo, al construir la demo 9: una ráfaga sostenida de 40 rps
durante 12,6 s no produjo **ni un solo 429**, cuando con 20 rps reales deberían
haberse rechazado ~200 peticiones.

Es el mismo problema que tenía el circuit breaker antes del ADR-0015 (cada
worker con su propio estado); al migrarlo a Redis se migró el breaker pero no el
rate limit. Queda registrado como **brecha 24**, y su gemelo en el contador de
intentos de login como **brecha 25**.

Mientras tanto, la contención real la aporta el **bulkhead**, que sí funciona
por servicio y sí rechaza con 503 cuando se llena.

## 5. Otros límites que sostienen el SLA

| Mecanismo | Valor | Por qué ese valor |
| :-- | :-- | :-- |
| **Timeout por servicio** | 3 s (auth, tickets, almacén, auditoría, notificaciones) · 4 s (facturas) · 5 s (diagnóstico) | Diagnóstico y facturación orquestan llamadas a almacén, por eso más holgura. Un timeout corta la espera antes de que el usuario abandone |
| **Bulkhead (llamadas en vuelo)** | tickets 12 · auth/almacén/diagnóstico/facturas 8 · auditoría/notificaciones 5 | Tickets es el más transitado. Aísla: una dependencia lenta no consume la capacidad de las demás |
| **Circuit breaker** | Abre a los 3 fallos seguidos · cooldown 15 s | 3 fallos es señal de dependencia enferma, no de un error puntual. 15 s da margen a reiniciar sin dejar el circuito abierto de más |
| **Backoff de reintento** | **3 s  5 s  8 s** (+ jitter); el outbox sigue hasta 30 s | Escalonado para no golpear una dependencia enferma; el jitter evita que todos reintenten a la vez |
| **Shedding** | Al 70 % de ocupación del bulkhead | Reserva el cupo restante para escrituras críticas, descartando lecturas de baja prioridad |

## 6. Garantía de no pérdida de datos (más fuerte que el SLA de disponibilidad)

Aunque un servicio esté **caído**, una escritura aceptada por el Gateway **no se
pierde**: se encola en el outbox y se entrega cuando el servicio vuelve, con la
misma `Idempotency-Key` (no se duplica). Ver ADR-0011.

> **Compromiso:** 0 % de pérdida de escrituras aceptadas (`202 encolado`) y 0 %
> de duplicación, incluso durante una caída total del servicio destino.

Esto significa que el SLA de *disponibilidad* puede incumplirse sin que se
incumpla el de *integridad*: el usuario ve un aviso de "en cola", no un error.

## 7. Presupuesto de error y qué pasa al incumplir

| Nivel | Situación | Acción | Responsable |
| :-- | :-- | :-- | :-- |
| Verde | Dentro de objetivo | Operación normal | Soporte de TI |
| Ámbar | > 50 % del presupuesto de error consumido en el mes | Congelar cambios no críticos; revisar la causa dominante en Grafana | Soporte de TI |
| Rojo | SLA incumplido | Playbook de incidente (`runbook.md` §8) + registro de brecha con acción y responsable | Soporte de TI + owner funcional del área |

**Escalamiento:** el owner técnico (Soporte de TI) ejecuta la recuperación; el
owner funcional del área afectada (Recepción, Técnico, Administrador o
Facturación) decide si se comunica al cliente y si procede una compensación
manual. Detalle por servicio en `catalogo-servicios.md` §2.

## 8. Ventanas de mantenimiento

Cambios con reinicio de contenedores: **fuera del horario de atención**
(el sistema es de uso diurno en las sedes de Piura y Talara). Un
`docker compose up -d --build <servicio>` reinicia solo ese servicio; el resto
sigue operando y el Gateway devuelve `202 encolado` para las escrituras que caigan
en esa ventana.

## 9. Lo que este SLA **no** cubre

- **Alta disponibilidad real**: no hay réplicas ni failover (brechas #1 y #2).
- **Recuperación ante desastre**: no hay copia de seguridad automatizada de
  PostgreSQL ni objetivo de RPO/RTO definido.
- **Terceros**: no se integran proveedores externos; si se añadieran (p. ej. una
  pasarela de pago), su disponibilidad se acota aparte.

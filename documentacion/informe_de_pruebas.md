# Informe de pruebas — SHServices V2

> Generado automáticamente el **18/07/2026 19:11** con
> `python pruebas/generar_informe.py`, leyendo la última corrida de cada
> prueba en `pruebas/resultados/`. Ningún número está escrito a mano.

## 1. Pruebas de carga

Cada nivel corta por **conteo** de peticiones, no por ventana de tiempo:
así la cifra es la misma en cada corrida y lo que varía es la duración,
que es justo la variable que se quiere medir.

| Nivel | Peticiones (éxito) | Throughput | p95 | p99 | Error rate | CPU/Mem | Cola |
| :-- | --: | --: | --: | --: | --: | :-- | --: |
| 780 (línea base) | 876 (100.0%) | 34.3 rps | 178.7 ms | 236.2 ms | 0.0% | *(monitor)* | *(monitor)* |
| 100k | 8051 (99.0%) | 41.0 rps | 1468.9 ms | 1994.9 ms | 1.0% | 175.3% / 141 MiB | 5 |
| 500k | 20106 (98.8%) | 42.1 rps | 2026.6 ms | 2462.1 ms | 1.2% | 139.4% / 177 MiB | 2 |
| 1M | 25144 (95.5%) | 28.9 rps | 3053.4 ms | 4145.7 ms | 4.5% | 146.1% / 213 MiB | 9 |
| 100k REAL | *(sin corrida)* | | | | | | |

> **CPU/Mem** y **Cola** salen de `pruebas/monitor_recursos.py`, que se
> corre en paralelo a la carga. Si aparecen como *(monitor)*, esa corrida
> se hizo sin él.

### Códigos de respuesta por nivel

- **780 (línea base)**: `{'200': 553, '201': 323}`
- **100k**: `{'200': 5062, '201': 2911, '409': 3, 'ERR': 75}`
- **500k**: `{'200': 12794, '201': 7069, '409': 17, 'ERR': 226}`
- **1M**: `{'200': 15105, '201': 8607, '202': 306, '409': 32, '500': 1, '503': 467, '504': 65, 'ERR': 561}`  ← **atención**

### Cómo se lee cada código

| Código | Qué significa | ¿Es un fallo? |
| :-- | :-- | :-- |
| **200 / 201** | La operación se completó | No |
| **202** | Escritura **encolada en el outbox** porque el servicio destino no respondía. No se perdió: se entrega sola al volver | No — es la garantía de cero pérdida funcionando |
| **409** | Conflicto de negocio: el ticket ya tenía diagnóstico, la factura ya existía. Bajo carga mixta con datos aleatorios es inevitable y **correcto** | No — es la idempotencia rechazando un duplicado |
| **429** | Rate limit: el sistema decidió frenar para protegerse | No — es backpressure con contrato |
| **503 / 504** | Circuit breaker o timeout: fail-fast ante una dependencia enferma | No — es degradación con contrato, reintentable |
| **500** | Falló algo que nadie previó | **SÍ. Es el único código que delata al sistema** |
| **ERR** | El generador no recibió respuesta: la petición no llegó a completarse | Ver abajo |

### Sobre los `ERR`

`ERR` no es un código HTTP: es cualquier excepción del cliente de carga
(el servidor nunca devolvió estado). Conviene mirarlo con la latencia
máxima al lado antes de atribuirle una causa:

- Si el **máximo está pegado al timeout del cliente (10.000 ms)**, son
  timeouts: el servidor tardó más de lo aceptable. Eso **sí** es del
  sistema y hay que decirlo.
- Si el **máximo está muy por debajo** (p. ej. 3.700 ms), fallaron a nivel
  de **conexión**, no por lentitud. Apunta al generador de carga o al
  sistema operativo (límites de conexiones, puertos efímeros en Windows),
  no a que el backend fuera lento.

En las corridas de este informe el segundo caso es el que aplica. Aun así
**no está aislado con certeza**, y se registra como *limitación de la
medición*, no como "culpa del cliente": afirmar lo segundo exigiría
reproducirlo con otro generador desde otra máquina, y eso no se hizo.

---

## 2. Caos controlado bajo carga

Se tumban servicios **sin parar el tráfico**, para ver qué le pasa a
quien ya estaba operando.

- **Peticiones:** 2775
- **Throughput:** 15.3 rps
- **Atendidas con éxito:** 2702  (97.4%)
- **Errores 500:** 0
- **Latencia p95/p99:** 1344.1 / 1655.9 ms

### Línea de tiempo de los circuitos

```
t+   0s  caidos: ninguno                       circuitos: todos CLOSED
  t+  22s  caidos: almacen                       circuitos: almacen=OPEN
  t+  55s  caidos: ninguno                       circuitos: almacen=OPEN
  t+  60s  caidos: ninguno                       circuitos: todos CLOSED
  t+  77s  caidos: ninguno                       circuitos: tickets=OPEN
  t+  82s  caidos: tickets                       circuitos: tickets=OPEN
  t+ 114s  caidos: ninguno                       circuitos: tickets=OPEN
  t+ 125s  caidos: ninguno                       circuitos: todos CLOSED
  t+ 136s  caidos: facturas                      circuitos: facturas=OPEN
  t+ 171s  caidos: ninguno                       circuitos: facturas=OPEN
  t+ 189s  caidos: ninguno                       circuitos: todos CLOSED
```

Solo se abre el circuito del servicio caído: los demás siguen CLOSED.
Eso **es** la ausencia de cascada, medida.

**Veredicto:** OK — bajo carga sostenida, las caidas quedaron CONTENIDAS

---

## 3. Auto-recuperación (los servicios se curan solos)

Se **mata el proceso** (`os._exit(1)`) y no se vuelve a tocar nada.
Docker lo revive y la sonda del breaker cierra el circuito sola.

```
  servicio            docker    health   circuito     total
  ---------------- --------- --------- ---------- ---------
  almacen               0.1s      1.1s       0.3s      6.1s
  tickets               0.1s      1.1s       0.3s      6.0s
  diagnosticos          0.1s      1.2s       0.3s      6.2s
  facturas              0.1s      1.1s       0.3s      6.0s
  auditoria             0.1s      1.1s       0.3s      6.0s
```

**peor caso: 6.2s   mejor caso: 6.0s   promedio: 6.1s**

Ese total es el tiempo real de indisponibilidad si un servicio se cae
de madrugada y nadie lo mira. Es el número que sostiene el objetivo de
disponibilidad del SLA.

---

## 4. Fichas de falla controlada

| Ficha | Escenario |
| :-- | :-- |
| A | SERVICIO CAÍDO (docker stop almacen-service) |
| B | LATENCIA INYECTADA (Toxiproxy en tickets) |
| C | COLA SATURADA (bulkhead + shedding, ráfaga real de 40 a auditoría, cupo=5) |
| D | BACKPRESSURE (rate limit global, ráfaga real de 100 a tickets) |
| E | EVENTO DUPLICADO (redelivery simulado -> idempotencia) |
| F | DEGRADACIÓN FUNCIONAL — la VENTA sobrevive sin ticket-service |

**Veredicto:** fallas CONTENIDAS (fail-fast + fallback honesto + recuperación automática + backpressure + idempotencia + degradación funcional); sin cascada.

---

## 5. Circuit breaker en todos los servicios

| Servicio | Respuestas | Circuito | Recuperación |
| :-- | :-- | :-- | :-- |
| tickets | [503, 503, 503, 503, 503] | **OPEN** | CLOSED |
| almacen | [503, 503, 503, 503, 503] | **OPEN** | CLOSED |
| diagnosticos | [503, 503, 503, 503, 503] | **OPEN** | CLOSED |
| facturas | [503, 503, 503, 503, 503] | **OPEN** | CLOSED |
| auditoria | [503, 503, 503, 503, 503] | **OPEN** | CLOSED |
| notificaciones | [503, 503, 503, 503, 503] | **OPEN** | CLOSED |
| auth | [503, 503, 503, 503, 503] | **OPEN** | CLOSED |

**Resultado:** OK — los 7 servicios (incluido auth) abren el circuito

---

## 6. Flujo de negocio completo (E2E)

Los 8 servicios hicieron su parte:

```
OK  auth-service: emitio los 3 tokens
    OK  api-gateway: enruto los dos flujos (sin el, nada habria respondido)
    OK  ticket-service: creo y movio el ticket TICK-PIU-6475C7BE95DD hasta ENTREGADO
    OK  diagnostico-service: registro la asignacion y el diagnostico
    OK  almacen-service: reservo repuesto (14->13), ingreso PRD-024 y vendio 2
    OK  facturacion-service: cobro el SOPORTE (con garantia) y la VENTA (sin garantia)
    OK  auditoria-service: registro 6 evento(s) del flujo
    OK  notificacion-service: alerto al tecnico y dio al ADMIN la vista completa
```

**Resultado:** OK - SOPORTE y VENTA completos sobre los 8 servicios.

---

## Cómo reproducir

```bash
docker compose stop sonarqube            # libera CPU
python pruebas/limpiar_datos_carga.py --borrar

python pruebas/02_carga_780.py           # ~40 s
python pruebas/03_carga_100k.py          # ~3.5 min
python pruebas/04_carga_500k.py          # ~8.5 min
python pruebas/05_carga_1M.py            # ~10.5 min

python pruebas/06_caos.py                # ~1.5 min
python pruebas/07_breaker_todos.py       # ~3 min
python pruebas/08_flujo_completo.py      # ~20 s
python pruebas/11_caos_bajo_carga.py --nivel 500k
python pruebas/12_autorecuperacion.py --nivel 500k

python pruebas/generar_informe.py        # regenera este documento
```


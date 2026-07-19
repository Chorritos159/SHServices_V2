# Pruebas de carga con k6

Generador de carga en **Go** para las tres fases de la S34. Convive con
`pruebas/` (funcionales, caos, resiliencia) y con `pruebas_reales/`: **no
sustituye a ninguna**. Si k6 fallara, esas siguen sirviendo.

## Por qué k6

El generador de Python (`pruebas/lib/carga_nodos.py`) topa en **~105 rps por
proceso**. Se comprobó lanzando varios en paralelo:

| Generadores Python | Throughput total |
| --: | --: |
| 1 | 105 rps |
| 2 | 171 rps |
| 4 | 257 rps — y seguía subiendo |

Como el total escalaba con el número de procesos, **el techo que se estaba
midiendo era el del cliente, no el del sistema**. Un solo proceso con GIL hace
competir entre sí el envío, la deserialización y el conteo.

k6 es Go: sus usuarios virtuales son goroutines, sin GIL. Además **corre dentro
de la red Docker**, hablando con `api-gateway:80` directamente, así que se salta
la traducción de red de Windows.

### La diferencia, medida

| | Generador Python | k6 |
| :-- | --: | --: |
| Throughput (mismo sistema) | 105 rps | **166 rps** con 20 VUs |
| p95 | 1.495 ms | **284 ms** |

La latencia cae 5× porque buena parte de esos 1.495 ms era el propio generador
esperándose a sí mismo.

## Uso

```bash
# Comprobar que todo funciona antes de una corrida larga (~10 s)
python pruebas_k6/correr.py --fase humo

# Las tres fases de la S34
python pruebas_k6/correr.py --fase 100k
python pruebas_k6/correr.py --fase 500k
python pruebas_k6/correr.py --fase 1M

# Afinar la concurrencia
python pruebas_k6/correr.py --fase 100k --vus 100
```

No hay que instalar nada: se usa la imagen oficial `grafana/k6` por Docker.

## Qué deja cada corrida

**La fila de la tabla, con las ocho columnas rellenas.** Ninguna se escribe a
mano:

```
| Fase | Throughput | p95 | p99 | Error rate | CPU/Mem | Queue depth | Resultado |
| **humo** | 166 rps | 284 ms | 401 ms | 0.00% | 315% / 518 MiB | 101 | cero
errores 500. cola RabbitMQ hasta 101 mensajes: los consumidores se quedaron atrás. |
```

- **Throughput, p95, p99, error rate** — del resumen de k6
- **CPU/Mem y Queue depth** — muestreados en paralelo durante la corrida
- **Resultado** — redactado a partir de lo observado, siguiendo la regla de la
  S34: *si el sistema llega a su límite, explicar el primer cuello de botella
  con métricas*

Las filas se **acumulan** en `documentacion/tabla_registro_carga_k6.md`, así que
cada corrida suma sin borrar las anteriores. El JSON completo de k6 queda en
`pruebas_k6/resultados/`.

## Dos detalles que importan

**El error rate cuenta solo 5xx.** La métrica `http_req_failed` de k6 marca como
fallo *todo* status ≥ 400, incluidos los **409** de conflicto de negocio (ticket
ya diagnosticado, factura ya emitida) que bajo carga mixta son inevitables y
**correctos**. Contarlos como errores daría una tasa de fallo inflada por el
funcionamiento normal de la idempotencia.

**Se amplían rate limit y bulkhead durante la corrida** (y se restauran al
terminar). Sin eso se mide dónde corta el limitador, no la capacidad: la primera
corrida de humo dio 66% de 503 simplemente porque k6 empujaba más rápido que el
límite de 20 rps.

## Antes de una corrida larga

```bash
docker compose stop sonarqube dozzle          # liberan CPU
python pruebas/limpiar_datos_carga.py --borrar
```

Lo segundo importa: la carga mixta crea tickets y productos, y aunque los
listados ya están paginados, la base creciendo cambia lo que se mide.

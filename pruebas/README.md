# Suite de pruebas — SHServices V2 (Fase 5, S34)

Scripts en Bash (con generadores de carga en Python puro en `pruebas/lib/`,
requieren `httpx`: `pip install httpx`). Todos se ejecutan **desde la raíz
del proyecto** con el sistema arriba (`docker compose up -d`). Los reportes
quedan en `pruebas/resultados/` (texto + JSON, ignorados por git).

> En Windows: usar **Git Bash**. Los scripts pasan las rutas de la API sin
> la barra inicial (`api/v1/...`, no `/api/v1/...`) a propósito: MSYS
> convierte cualquier argumento que empiece con "/" a una ruta de Windows
> antes de que Python lo reciba — los runners la reponen internamente, ya a
> salvo.

| # | Script | Qué prueba | Duración |
| :-- | :-- | :-- | :-- |
| 1 | `bash pruebas/01_traza_unica.sh` | Una operación completa trazada de inicio a fin: auditoría + notificaciones + logs estructurados de 4 contenedores con UN correlationId | ~10 s |
| 2 | `bash pruebas/02_carga_780.sh` | 780 peticiones a la vez con los límites normales: se observa el rate limit (429) y el bulkhead (503) rechazando de forma controlada | ~5 s |
| 3 | `bash pruebas/03_carga_100k.sh` | Nivel **100k**: 6 nodos x bloques de 40, ventana de 10 min | 10 min |
| 4 | `bash pruebas/04_carga_500k.sh` | Nivel **500k**: 10 nodos x bloques de 80, ventana de 15 min | 15 min |
| 5 | `bash pruebas/05_carga_1M.sh` | Nivel **1M**: 15 nodos x bloques de 120, ventana de 15 min | 15 min |
| 6 | `bash pruebas/06_caos.sh` | 6 fichas de falla controlada: servicio caído, latencia, cola saturada (bulkhead+shed), rate limit, evento duplicado | ~1 min |

## Metodología de las pruebas 3-5 (nodos, bloques, ventana fija)

`pruebas/lib/carga_nodos.py` simula varios **nodos** independientes (no un
solo hilo, no "todo de golpe"): cada nodo manda **bloques** de N peticiones
concurrentes, espera un poco, y manda el siguiente bloque — así hasta que
se acaba una **ventana de tiempo fija** (10-15 min).

- **Por qué ventana de tiempo y no conteo literal:** a la tasa real medida
  del sistema (~85-90 rps, limitada por el Gateway de 1 worker), completar
  500,000 peticiones tomaría 1.5-2 horas y 1,000,000 tomaría 3-4 horas —
  poco práctico para una corrida de verificación. Las etiquetas 100k/500k/1M
  representan el **nivel de carga ofrecida** (más nodos, bloques más
  grandes en cada nivel), no un conteo a cumplir. Se reporta cuánto
  throughput real se sostuvo en la ventana y, si no se alcanza la etiqueta,
  se explica el primer cuello de botella con métricas (regla explícita de
  la S34).
- **Backoff entre bloques:** escalonado **3s → 5s → 8s + jitter** cuando un
  bloque recibe 429/503 (sube de nivel en cada bloque afectado); un bloque
  limpio baja el nivel a 0 y usa una pausa corta (~0.2-0.4s). Sin esto,
  todos los nodos reintentarían sincronizados justo cuando el sistema ya
  está bajo presión.
- Las pruebas 3-5 amplían el rate limit del Gateway temporalmente
  (`RATE_LIMIT_RPS`/`RATE_LIMIT_BURST`, configurable por entorno desde la
  Fase 5) para medir el throughput real del backend y no el techo del
  propio limitador, y lo **restauran al terminar** (`trap ... EXIT`).

## Correr las pruebas largas en segundo plano

```bash
bash pruebas/04_carga_500k.sh > pruebas/resultados/04_consola.log 2>&1 &
# progreso en vivo:
tail -f pruebas/resultados/04_consola.log
# señales del gateway en vivo (formato Prometheus):
curl -s http://localhost:8000/metrics | grep -E "gateway_(circuit_state|bulkhead|retries|fallbacks)"
# CPU/Mem del gateway durante la carga:
docker stats --no-stream api-gateway
```

No correr dos pruebas de nivel (3, 4 o 5) **simultáneamente**: compiten por
el mismo bulkhead de tickets (cupo=12) y confunden la medición de cada una.

## Corridas cortas de humo (mismo mecanismo, menos volumen/tiempo)

```bash
NODOS=3 BLOQUE=10 DURACION=60 bash pruebas/03_carga_100k.sh
```

## Cómo leer los resultados

- **HTTP 200** = atendida. **429** = rate limit global (backpressure).
  **503** = bulkhead lleno / shedding de baja prioridad / circuito abierto
  (rechazo controlado). **504** = timeout del presupuesto. Los rechazos
  controlados NO son fallas: son el sistema degradando con contrato
  (Fases 1-2 de S34).
- `latencia p50/p95/p99` viene del runner (extremo a extremo, agregando
  todos los nodos). Las métricas por servicio (circuit state, retries,
  fallbacks, bulkhead) se leen de `GET /metrics` del Gateway (formato
  Prometheus) o del dashboard de Grafana (Fase 4).
- La prueba 6 registra las fichas en
  `documentacion/fichas_falla_controlada.md` (formato exacto de la S34).
- El "Registro de carga" (formato exacto de la S34, pág. 24) se llena en
  `documentacion/registro_de_carga.md` con los reportes JSON de
  `pruebas/resultados/`.

## Notas de honestidad de la medición

- "N a la vez" se ejecuta como N trabajadores concurrentes dentro de cada
  bloque (prueba 2) o como varios nodos mandando bloques sucesivos
  (pruebas 3-5): un solo equipo no abre 1M de sockets simultáneos; lo que
  se mide es el comportamiento del sistema bajo presión sostenida, que es
  lo operativamente relevante.
- **Cuello de botella identificado:** con el rate limit ampliado, el
  Gateway (1 solo worker Gunicorn — necesario para que el circuit breaker
  tenga una única fuente de verdad, ver Fase 1) satura su núcleo de CPU
  antes que `ticket-service` o PostgreSQL. Ver
  `documentacion/registro_de_carga.md` para el detalle.
- **Importante (Git Bash / MSYS):** cualquier `--ruta` o argumento que
  pases a mano a los runners debe ir **sin** la barra inicial, o Git Bash
  lo va a convertir en una ruta de Windows.
- Corridas largas: cuidar que Docker Desktop no se suspenda (energía) y
  evitar sincronizaciones pesadas de OneDrive durante la prueba (el
  proyecto vive dentro de una carpeta de OneDrive).

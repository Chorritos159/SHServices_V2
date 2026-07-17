# Suite de pruebas — SHServices V2 (Fase 5, S34)

Scripts en Bash (con un runner Python de librería estándar en `lib/carga.py`
y un generador de concurrencia real en `lib/rafaga_async.py`, que sí
requiere `httpx`: `pip install httpx`). Todos se ejecutan **desde la raíz
del proyecto** con el sistema arriba (`docker compose up -d`). Los reportes
quedan en `pruebas/resultados/` (texto + JSON, ignorados por git).

> En Windows: usar **Git Bash**. Los scripts pasan las rutas de la API sin
> la barra inicial (`api/v1/...`, no `/api/v1/...`) a propósito: MSYS
> convierte cualquier argumento que empiece con "/" a una ruta de Windows
> antes de que Python lo reciba — `lib/carga.py` y `lib/rafaga_async.py` la
> reponen internamente, ya a salvo.

| # | Script | Qué prueba | Duración aprox. |
| :-- | :-- | :-- | :-- |
| 1 | `bash pruebas/01_traza_unica.sh` | Una operación completa trazada de inicio a fin: auditoría + notificaciones + logs estructurados de 4 contenedores con UN correlationId | ~10 s |
| 2 | `bash pruebas/02_carga_780.sh` | 780 peticiones a la vez con los límites normales: se observa el rate limit (429) y el bulkhead (503) rechazando de forma controlada | ~5 s |
| 3 | `bash pruebas/03_carga_500k.sh` | 500,000 peticiones sostenidas (18 trabajadores, alineados al bulkhead para que ~todo se sirva). Amplía el rate limit temporalmente y LO RESTAURA al salir | ~1.5–2 h (a ~80-90 rps servidos) |
| 4 | `bash pruebas/04_carga_1M.sh` | 1,000,000 de peticiones (mismo runner) | ~3–4 h |
| 5 | `bash pruebas/05_caos.sh` | 5 fichas de falla controlada: servicio caído, latencia, cola saturada (bulkhead+shed), rate limit, evento duplicado (idempotencia) | ~1 min |

## Correr las cargas largas en segundo plano

```bash
bash pruebas/03_carga_500k.sh > pruebas/resultados/03_consola.log 2>&1 &
bash pruebas/04_carga_1M.sh  > pruebas/resultados/04_consola.log 2>&1 &
# progreso en vivo:
tail -f pruebas/resultados/03_consola.log
# señales del gateway en vivo (formato Prometheus):
curl -s http://localhost:8000/metrics | grep -E "gateway_(circuit_state|bulkhead|retries|fallbacks)"
# CPU/Mem del gateway durante la carga:
docker stats --no-stream api-gateway
```

No correr 03 y 04 **simultáneamente**: compiten por el mismo bulkhead de
tickets (cupo=12) y confunden la medición de throughput de ambas.

## Corridas cortas de humo (mismo mecanismo, menos volumen)

```bash
TOTAL=5000 HILOS=18 bash pruebas/03_carga_500k.sh
```

## Cómo leer los resultados

- **HTTP 200** = atendida. **429** = rate limit global (backpressure).
  **503** = bulkhead lleno / shedding de baja prioridad / circuito abierto
  (rechazo controlado). **504** = timeout del presupuesto. Los rechazos
  controlados NO son fallas: son el sistema degradando con contrato
  (Fases 1-2 de S34).
- `latencia p50/p95/p99` viene del runner (extremo a extremo). Las métricas
  por servicio (circuit state, retries, fallbacks, bulkhead) se leen de
  `GET /metrics` del Gateway (formato Prometheus) o del dashboard de
  Grafana (Fase 4).
- La prueba 5 registra las fichas en
  `documentacion/fichas_falla_controlada.md` (formato exacto de la S34).

## Notas de honestidad de la medición

- "N a la vez" se ejecuta como N trabajadores concurrentes (prueba 2) o
  carga sostenida con H trabajadores (pruebas 3-4): un solo equipo no abre
  1M de sockets simultáneos; lo que se mide es el comportamiento del
  sistema bajo presión sostenida, que es lo operativamente relevante.
- Las pruebas 3-4 amplían el rate limit para medir el throughput REAL del
  sistema (no el tope del limitador) y lo restauran al terminar; la prueba
  2 se corre con límites normales justamente para ver el backpressure
  actuar.
- **Cuello de botella identificado:** con el rate limit ampliado, el
  Gateway (1 solo worker Gunicorn — necesario para que el circuit breaker
  tenga una única fuente de verdad, ver Fase 1) satura su núcleo de CPU
  antes que `ticket-service` o PostgreSQL. Ver
  `documentacion/registro_de_carga.md` para el detalle y la justificación
  de por qué no se subieron los workers.
- **Importante (Git Bash / MSYS):** cualquier `--ruta` o argumento que
  pases a mano a `lib/carga.py`/`lib/rafaga_async.py` debe ir **sin** la
  barra inicial, o Git Bash lo va a convertir en una ruta de Windows.
- Corridas largas: cuidar que Docker Desktop no se suspenda (energía) y
  evitar sincronizaciones pesadas de OneDrive durante la prueba (el
  proyecto vive dentro de una carpeta de OneDrive).

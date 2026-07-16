# Observabilidad y Resiliencia — SHServices V2

Guía para operar y demostrar la resiliencia del sistema (Circuit Breaker, trazas y Chaos con Toxiproxy).

## 1. Dashboard de Resiliencia (Grafana)

- Abre **http://localhost:3000** (admin / admin) → carpeta **SHServices** → **"SHServices · Resiliencia"**.
- Se provisiona solo desde `grafana/provisioning/` (datasources Prometheus/Loki + dashboard).

Paneles:

| Panel | Qué muestra | Query base |
|---|---|---|
| Cortes Circuit Breaker (total) | Nº total de cortes del breaker | `sum(gateway_circuit_breaker_total)` |
| Servicios UP | Cuántos servicios responden (de 8) | `sum(up{job=~".+-service\|api-gateway"})` |
| Latencia p95 Gateway | Latencia del enrutado (sube con Toxiproxy) | `histogram_quantile(0.95, ...)` |
| Tasa de error 5xx | Proporción de fallos en el Gateway | `rate(...status="5xx") / rate(...)` |
| Circuit Breaker por motivo | Cortes por `conexion` (503) y `timeout` (504) | `sum by (motivo) (rate(gateway_circuit_breaker_total[1m]))` |
| Peticiones por status | 2xx / 4xx / 5xx en el tiempo | `sum by (status) (rate(http_requests_total{job="api-gateway"}[1m]))` |
| Latencia p50/p95/p99 | Distribución de latencia | `histogram_quantile(...)` |
| Disponibilidad (up) | UP/DOWN por servicio | `up{job=~".+-service\|api-gateway"}` |

> El Gateway corre con **4 workers gunicorn**, por eso se activó el **modo multiproceso** de
> `prometheus_client` (`PROMETHEUS_MULTIPROC_DIR`), que agrega los contadores de todos los workers.

## 2. Cómo seguir la traza (Correlation-ID)

Cada petición recibe un **`X-Correlation-ID`** que el Gateway genera (o propaga) y viaja por todos
los servicios y por los eventos de RabbitMQ. En una respuesta de error (503/504) viene en `trace_id`.

**Seguir una traza en Grafana → Explore → datasource Loki:**

```logql
{stack="shservices"} | json | trace_id = "<PEGA_AQUI_EL_ID>"
```

O por servicio:

```logql
{container="api-gateway"} | json | trace_id != "N/A"
```

Cada log es JSON con `service_name`, `trace_id`, `message` y `timestamp`, así que puedes reconstruir
el recorrido completo de una operación entre microservicios.

## 3. Chaos Engineering con Toxiproxy

El tráfico Gateway → `ticket-service` pasa por **Toxiproxy** (proxy `ticket_proxy`, control en `:8474`).
Al degradarlo, el Circuit Breaker del Gateway responde y se ve en el dashboard.

**Inyectar latencia (dispara 504 · timeout):**
```bash
curl -X POST http://localhost:8474/proxies/ticket_proxy/toxics \
  -d '{"name":"lat","type":"latency","attributes":{"latency":8000}}'
```

**Simular caída (dispara 503 · conexión):**
```bash
curl -X POST http://localhost:8474/proxies/ticket_proxy -d '{"enabled":false}'
```

**Restaurar el servicio:**
```bash
curl -X DELETE http://localhost:8474/proxies/ticket_proxy/toxics/lat
curl -X POST   http://localhost:8474/proxies/ticket_proxy -d '{"enabled":true}'
```

Tras cada inyección, crea/consulta un ticket por el Gateway y observa el dashboard: el panel
**"Circuit Breaker por motivo"** marca `timeout` o `conexion`, y la latencia p95 se dispara.

## 4. Prueba automatizada

No hay tests unitarios; la resiliencia se valida con un script end-to-end:

```bash
python pruebas_resiliencia.py
```

Ejecuta la secuencia completa (sano → latencia/504 → recuperado → caída/503 → restaurado) y
reporta **5/5 PASS** más el nº de cortes registrados. Ideal para demostrar el Circuit Breaker en vivo.

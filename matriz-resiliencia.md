# Matriz de Resiliencia — SHServices V2

> Gate **G8 · FF-DEP-08** · Estrategias de tolerancia a fallos y Chaos Engineering
> Última actualización: 2026-07-15

## 1. Resumen de mecanismos

| Mecanismo | Dónde | Qué protege |
|---|---|---|
| **Circuit Breaker** | API Gateway | Aísla un microservicio caído o lento |
| **Toxiproxy** | Tráfico Gateway → Tickets | Simula latencia/caídas (prueba del breaker) |
| **`restart: always`** | Todos los contenedores | Auto-recuperación ante crash |
| **Health checks** | Dockerfile + `/health` | Detección de servicios no saludables |
| **`depends_on` + `condition`** | Compose | Orden de arranque controlado |
| **`connect_robust` + retry loop** | Consumidor de Auditoría | Sobrevive a RabbitMQ no disponible |
| **`pool_pre_ping` / `pool_recycle`** | Capa SQLAlchemy | Reconexión transparente a PostgreSQL |
| **Gunicorn multi-worker** | API Gateway | Throughput y aislamiento bajo carga |

## 2. Circuit Breaker (API Gateway)

El Gateway envuelve cada llamada saliente (`httpx`, `timeout=5s`) y traduce los fallos:

| Fallo del microservicio | Excepción | Respuesta del Gateway |
|---|---|---|
| Servicio apagado / inaccesible | `httpx.ConnectError` | **503** Service Unavailable + `trace_id` |
| Servicio lento (> 5 s) | `httpx.TimeoutException` | **504** Gateway Timeout + `trace_id` |

Así, la caída de un servicio **no** propaga un error 500 opaco ni cuelga al cliente: se devuelve
un código semántico y el `X-Correlation-ID` para rastrear el incidente.

## 3. Chaos Engineering con Toxiproxy

- El Gateway apunta a Tickets mediante `http://toxiproxy:8666` (no directo).
- Toxiproxy reenvía a `ticket-service:80` y permite **inyectar toxinas** (latencia, corte de
  conexión, ancho de banda) a través de su API de control en `:8474`.
- Sirve para **demostrar el Circuit Breaker en vivo**: al inyectar un corte, el Gateway responde
  503; al inyectar latencia > 5 s, responde 504.

**Ejemplo (inyectar latencia de 8 s):**
```bash
curl -X POST http://localhost:8474/proxies/ticket_proxy/toxics \
  -d '{"type":"latency","attributes":{"latency":8000}}'
# → crear un ticket ahora devuelve 504 Gateway Timeout
```

## 4. Matriz de dependencias y arranque

| Servicio | Depende de | Condición | Nota de resiliencia |
|---|---|---|---|
| api-gateway | auth-service, toxiproxy | `service_started` | Arranca aunque un servicio esté caído (para probar el breaker) |
| ticket-service | postgres-db, rabbitmq | `service_healthy` | No arranca sin sus dependencias sanas |
| almacen-service | postgres-db | `service_healthy` | — |
| diagnostico-service | postgres-db, rabbitmq | `service_healthy` | — |
| facturacion-service | postgres-db, rabbitmq | `service_healthy` | — |
| auditoria-service | rabbitmq, **postgres-db** | `service_healthy` | Persiste la traza (Fase 4) |

## 5. Resiliencia del consumidor de eventos

El `auditoria-service` consume de RabbitMQ dentro de un **bucle de reintento**:

- El healthcheck de RabbitMQ (`rabbitmq-diagnostics ping`) puede reportar "healthy" **antes** de
  aceptar conexiones AMQP. Si el primer `connect_robust` fallaba, la tarea moría sin reintentar.
- **Corrección:** `while True: try … except: sleep(5)` — reintenta el arranque y reconecta si la
  conexión cae. Los mensajes durables quedan en la cola hasta que el consumidor vuelve.

## 6. Resiliencia de datos

- **`pool_pre_ping=True`**: valida cada conexión con un `SELECT 1` antes de usarla (descarta
  conexiones muertas si PostgreSQL se reinició).
- **`pool_recycle=280`**: recicla conexiones viejas antes de que el servidor las cierre.
- **Mensajería durable**: exchange y colas `durable=True`; los eventos no se pierden si un
  consumidor está temporalmente caído.

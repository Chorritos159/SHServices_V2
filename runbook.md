# Runbook Operativo — SHServices V2

> Gate **G8 · FF-DEP-08** · Despliegue básico y operación del servicio
> Última actualización: 2026-07-16 (Fase 6 del plan de integración S34)

## 1. Prerrequisitos

- Docker Desktop / Docker Engine + Docker Compose v2
- Node.js 20+ (solo para el frontend web)
- Python 3.11+ con `httpx` (`pip install httpx`) — solo para correr `pruebas/`
- Puertos host libres: `8000`, `8003`, `15672`, `15692`, `8474`, `9090`, `3000` y `3001` (frontend)
- Un `.env` en la raíz (copiar de `.env.example` y completar) — sin él, `docker compose up` falla
  explícitamente en vez de correr con secretos vacíos

## 2. Levantar todo el sistema

Desde la raíz del proyecto:

```bash
cp .env.example .env   # completar los valores, solo la primera vez
docker compose up --build
```

> `--build` reconstruye las imágenes con el código más reciente. Para dejarlo en segundo plano:
> `docker compose up --build -d`.

El frontend web se levanta aparte:

```bash
cd frontend
npm install      # solo la primera vez
npm run dev      # queda en http://localhost:3001
```

## 3. Pasos de validación (post-arranque)

### 3.1 Contenedores sanos
```bash
docker compose ps
# Todos deben figurar como "running"; los de BD/colas como "healthy".
```

### 3.2 Health checks avanzados (FF-DEP-02)
```bash
docker exec ticket-service python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:80/health').read().decode())"
```
Salida esperada:
```json
{"status":"UP","service":"ticket-service","version":"1.0.0","dependencies":{"database":"UP"}}
```
Repetir para `almacen-service`, `diagnostico-service`, `facturacion-service`, `auditoria-service`,
`notificacion-service`.

### 3.3 Autenticación (JWT con rol + sede)
```bash
curl -s -X POST http://localhost:8003/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"usuario":"caja01","password":"caja123"}'
# → { "access_token": "...", "token_type": "bearer", "expires_in": 7200 }
```

### 3.4 Prueba de humo end-to-end
Con el `access_token` de arriba en `$TOKEN`:
```bash
# CAJA crea un ticket (la sede se toma del token, no del body)
curl -s -X POST http://localhost:8000/api/v1/tickets/tickets/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"datosCliente":"Demo","tipoOperacion":"SOPORTE","datosEquipo":"Laptop","prioridad":"ALTA"}'
# → 201 { "idTicket": "TICK-PIU-XXXX", "estadoInicial": "EN_COLA", ... }
```
Flujo completo por la UI (`http://localhost:3001`): `caja01` crea ticket → `tecnico01`
diagnostica (descuenta stock) → `caja01` factura → `admin` revisa Inventario y Auditoría.

### 3.5 Auditoría persistente (FF-DEP-07)
```bash
docker exec postgres-db psql -U admin -d shservices_db -c \
  "SELECT evento, trace_id, sede, id_ticket FROM auditoria_eventos ORDER BY id DESC LIMIT 5;"
```

## 4. Puertos y paneles

| URL | Servicio |
|---|---|
| http://localhost:3001 | Frontend web |
| http://localhost:8000/docs | Swagger del API Gateway |
| http://localhost:8003/docs | Swagger del Auth (demo) |
| http://localhost:15672 | RabbitMQ (guest/guest) |
| http://localhost:9090 | Prometheus |
| http://localhost:3000 | Grafana (admin/admin) |
| http://localhost:8474 | Toxiproxy (API de control) |

## 5. Operación diaria

```bash
docker compose logs -f auditoria-service     # seguir logs de un servicio
docker compose restart ticket-service        # reiniciar un servicio
docker compose up -d --build almacen-service # reconstruir tras cambios de código
docker compose down                          # detener todo (conserva volúmenes/datos)
docker compose down -v                       # detener y BORRAR datos (¡destructivo!)
```

## 6. Prueba de caos (Circuit Breaker, bulkhead, rate limit, idempotencia)

Chequeo manual rápido (un solo mecanismo):

```bash
# Inyectar latencia de 8 s en el tráfico hacia Tickets (timeout del Gateway: 3s)
curl -X POST http://localhost:8474/proxies/ticket_proxy/toxics \
  -d '{"name":"latencia_manual","type":"latency","attributes":{"latency":8000}}'
# Crear/leer un ticket ahora debe devolver 504; tras 3 fallos seguidos, 503 con "circuito":"OPEN".
# Quitar la toxina (usa el "name" que le pusiste arriba) para restaurar el servicio:
curl -X DELETE http://localhost:8474/proxies/ticket_proxy/toxics/latencia_manual
# Tras el cooldown (15s), la sonda HALF_OPEN cierra el circuito sola.
```

**Verificación completa (recomendada):** `python pruebas/06_caos.py` corre las 5 fichas de
falla controlada de la S34 (servicio caído, latencia, cola saturada/bulkhead+shed, rate limit,
evento duplicado) en ~1 minuto, con veredicto explícito al final. Detalle de cada ficha
(hipótesis, métrica observada, evidencia) en `documentacion/fichas_falla_controlada.md`.

## 7. Troubleshooting

| Síntoma | Causa probable | Acción |
|---|---|---|
| Login 401 tras cambiar roles | Token viejo (rol `OPERADOR`) | Cerrar sesión y volver a entrar |
| Auditoría vacía | Consumidor aún reconectando | Esperar ~5 s y refrescar; ver `logs auditoria-service` |
| `503` al crear ticket | Servicio caído / toxina activa | `docker compose ps`; quitar toxina de Toxiproxy |
| `504` al crear ticket | Latencia > 5 s (toxina) | Quitar la toxina de latencia |
| Frontend no llega al backend | Contenedores abajo | `docker compose up -d` |
| Puerto 3000 ocupado | Grafana usa el 3000 | El frontend corre en el **3001** (por diseño) |
| `429` en ráfagas de peticiones | Rate limit global del Gateway (backpressure, no una falla) | Esperar unos segundos (se repone a 20 tokens/s) o revisar `Retry-After` en la respuesta |
| `503` "está bajo presión... baja prioridad" | Shedding del bulkhead (contención, no una falla) | Esperar; el cupo se libera apenas terminan las llamadas en vuelo — ver `gateway_bulkhead_in_flight` en Grafana |
| `docker compose up` falla con `Falta VAR en .env` | No existe `.env` o falta una variable | `cp .env.example .env` y completar los valores faltantes |

## 8. Playbooks de incidente (formato S34)

Cada playbook responde: qué pasa, cómo lo detecto, qué miro, qué ejecuto, a quién escalo y a
quién informo. **Owner técnico y responsable operativo de todos los servicios: Soporte de TI.**
El owner funcional de cada área decide si un cambio procede (ver `catalogo-servicios.md` §2).

### 8.1 Un microservicio está caído

| Sección | Detalle |
| :-- | :-- |
| **Incidente** | Un servicio de negocio no responde (503/504 en el Gateway) |
| **Detección** | Grafana: `gateway_circuit_state{service=…}` = 2 (OPEN); alertas de error rate; `docker compose ps` |
| **Primeras revisiones** | `docker compose ps` (¿Exited/unhealthy?), `docker compose logs --tail=50 <servicio>`, `GET /health` del servicio |
| **Acción** | Si crasheó: `restart: always` lo revive solo (~2 s). Si está `Exited` tras un stop manual: `docker compose up -d <servicio>`. Si está `unhealthy` (proceso colgado): `docker compose up -d --force-recreate <servicio>` |
| **Verificación** | El circuito se cierra **solo** en ~15-20 s (sonda activa, ADR-0014). Las escrituras encoladas se entregan solas (outbox, ADR-0011) |
| **Escalamiento** | Soporte de TI (owner técnico). Si es pérdida de datos → Administrador |
| **Comunicación** | Área afectada (Recepción / Técnico / Facturación) según el servicio |

### 8.2 El usuario ve "tu solicitud quedó en cola"

| Sección | Detalle |
| :-- | :-- |
| **Incidente** | Una escritura se encoló porque el servicio destino no estaba disponible (respuesta `202 encolado`) |
| **Detección** | Aviso ámbar en la UI; log del Gateway `operation=outbox_encolar` |
| **Primeras revisiones** | `SELECT estado, COUNT(*) FROM gateway_outbox GROUP BY estado;` — ¿hay PENDIENTE acumulándose? |
| **Acción** | **Ninguna sobre la petición**: el worker la reintenta solo. Resolver la caída del servicio destino (§8.1) |
| **Verificación** | La fila pasa a `ENTREGADO` con `status_respuesta` 2xx. Si queda `DESCARTADO`, fue un error de negocio (4xx): revisar `ultimo_error` y rehacer la operación corregida |
| **Escalamiento** | Soporte de TI |
| **Comunicación** | Avisar al área que la operación se completó sola (no debe reenviarla) |

### 8.3 Una cola de RabbitMQ crece y no baja

| Sección | Detalle |
| :-- | :-- |
| **Incidente** | `queue depth` sube sostenidamente (consumidores insuficientes o caídos) |
| **Detección** | Grafana → RabbitMQ: *Queue depth* y *Consumer lag*; `Consumidores activos por cola` = 0 |
| **Primeras revisiones** | `docker exec rabbitmq rabbitmqctl list_queues name messages consumers`; logs de `auditoria-service` / `notificacion-service` |
| **Acción** | Reiniciar el consumidor: `docker compose up -d --force-recreate auditoria-service` (los eventos están en cola durable: no se pierden) |
| **Verificación** | `consumers` vuelve a 1 y `messages` baja a 0 |
| **Escalamiento** | Soporte de TI |
| **Comunicación** | Administrador (la auditoría se recupera con retraso, no se pierde) |

### 8.4 Datos de prueba de carga en la base

| Sección | Detalle |
| :-- | :-- |
| **Incidente** | Tras una corrida de carga quedan tickets/productos/facturas con prefijo `CARGA-` |
| **Detección** | Listados del frontend con muchos registros `CARGA-…` |
| **Acción** | `python pruebas/limpiar_datos_carga.py` (cuenta) → `--borrar` (elimina) |
| **Escalamiento** | Soporte de TI |
| **Comunicación** | Administrador antes de borrar, para confirmar que no hay datos reales mezclados |

### 8.5 Provocar una caída controlada (para demo o prueba)

```bash
# Crash REAL: el proceso muere solo y restart:always lo revive en ~2 s
curl.exe -X POST http://localhost:8001/_chaos/crash     # ticket-service (ver README: puerto por servicio)

# Caída sostenida (se queda abajo hasta que TÚ lo levantes)
docker pause <servicio>    # …luego: docker unpause <servicio>
docker stop  <servicio>    # …luego: docker start   <servicio>
```
> `docker pause` / `stop` / `kill` **no** disparan `restart: always` (Docker los trata como
> parada solicitada por el usuario). Solo un **crash real** se auto-recupera.

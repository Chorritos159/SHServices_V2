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

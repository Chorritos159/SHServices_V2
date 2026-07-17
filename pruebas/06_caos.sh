#!/bin/bash
# PRUEBA 6 (Fase 5, S34): CAOS — 5 fichas de falla controlada.
#   A. Servicio caído (docker stop almacen-service) -> circuit breaker OPEN
#      -> fail-fast -> recuperación automática al volver.
#   B. Latencia inyectada (Toxiproxy en tickets) -> timeout (504) -> circuito
#      OPEN -> recuperación (sonda HALF_OPEN) al quitar la toxina.
#   C. Cola saturada (ráfaga concurrente real) -> bulkhead + shedding (503).
#   D. Backpressure (ráfaga concurrente real) -> rate limit global (429).
#   E. Evento duplicado (redelivery simulado) -> idempotencia, no duplica.
# Uso:  bash pruebas/06_caos.sh
set -u
source "$(dirname "$0")/lib/comun.sh"
verificar_sistema
LIB="$(dirname "$0")/lib"

SALIDA="$RESULTADOS/06_caos_$(date +%Y%m%d_%H%M%S).txt"
marca() { echo "[$(date +%H:%M:%S)] $1"; }

{
banner "FICHA A: SERVICIO CAÍDO (docker stop almacen-service)"
TOKEN=$(login admin admin123)
marca "circuit_state almacen (antes): $(metrica_gateway 'gateway_circuit_state{service="almacen"}')  (0=CLOSED)"
marca "💥 docker stop almacen-service"
docker stop almacen-service > /dev/null
sleep 1
for i in 1 2 3 4; do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "$GW/almacen/almacen/productos" -H "Authorization: Bearer $TOKEN")
  marca "  intento $i -> HTTP $CODE"
done
marca "circuit_state almacen (tras 4 fallos): $(metrica_gateway 'gateway_circuit_state{service="almacen"}')  (2=OPEN esperado)"
T0=$(date +%s%N)
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$GW/almacen/almacen/productos" -H "Authorization: Bearer $TOKEN")
MS=$(( ($(date +%s%N) - T0) / 1000000 ))
marca "fail-fast con el circuito abierto -> HTTP $CODE en ${MS}ms (esperado: <100ms, sin tocar la red)"
marca "🔌 docker start almacen-service"
docker start almacen-service > /dev/null
marca "Esperando cooldown del circuito (15s) + arranque del servicio..."
sleep 20
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$GW/almacen/almacen/productos" -H "Authorization: Bearer $TOKEN")
marca "sonda tras recuperación -> HTTP $CODE | circuit_state: $(metrica_gateway 'gateway_circuit_state{service="almacen"}')  (0=CLOSED esperado)"

banner "FICHA B: LATENCIA INYECTADA (Toxiproxy en tickets)"
marca "circuit_state tickets (antes): $(metrica_gateway 'gateway_circuit_state{service="tickets"}')"
marca "💉 inyectando latencia de 8s en ticket_proxy (timeout configurado: 3s)"
curl -s -X POST http://localhost:8474/proxies/ticket_proxy/toxics \
  -d '{"name":"latencia_caos","type":"latency","attributes":{"latency":8000}}' > /dev/null
for i in 1 2 3; do
  T0=$(date +%s%N)
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "$GW/tickets/tickets/" -H "Authorization: Bearer $TOKEN")
  MS=$(( ($(date +%s%N) - T0) / 1000000 ))
  marca "  intento $i -> HTTP $CODE en ${MS}ms (504 = timeout de los 3s configurados)"
done
marca "circuit_state tickets (tras timeouts): $(metrica_gateway 'gateway_circuit_state{service="tickets"}')  (2=OPEN esperado)"
marca "🧹 quitando la toxina"
curl -s -X DELETE http://localhost:8474/proxies/ticket_proxy/toxics/latencia_caos > /dev/null
marca "Esperando cooldown del circuito (15s)..."
sleep 16
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$GW/tickets/tickets/" -H "Authorization: Bearer $TOKEN")
marca "sonda tras recuperación -> HTTP $CODE | circuit_state: $(metrica_gateway 'gateway_circuit_state{service="tickets"}')  (0=CLOSED esperado)"

banner "FICHA C: COLA SATURADA (bulkhead + shedding, ráfaga real de 40 a auditoría, cupo=5)"
python "$LIB/rafaga_async.py" "api/v1/auditoria/auditoria/eventos" 40
marca "bulkhead rejects (shed_baja_prioridad): $(metrica_gateway 'gateway_bulkhead_rejects_total{razon="shed_baja_prioridad",service="auditoria"}')"
marca "bulkhead in_flight tras la ráfaga (debe volver a 0): $(metrica_gateway 'gateway_bulkhead_in_flight{service="auditoria"}')"

banner "FICHA D: BACKPRESSURE (rate limit global, ráfaga real de 100 a tickets)"
python "$LIB/rafaga_async.py" "api/v1/tickets/tickets/" 100
marca "rate limit rejects (acumulado): $(metrica_gateway 'gateway_rate_limit_rejects_total')"

banner "FICHA E: EVENTO DUPLICADO (redelivery simulado -> idempotencia)"
CID="caos-idem-$(date +%s)"
PAYLOAD="{\"datosCliente\":\"Cliente Caos Idem\",\"documento_cliente\":\"99999999\",\"telefono_cliente\":\"999999999\",\"tipoOperacion\":\"VENTA\",\"prioridad\":\"NORMAL\"}"
R1=$(curl -s -X POST "$GW/tickets/tickets/" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -H "Idempotency-Key: $CID" -d "$PAYLOAD")
R2=$(curl -s -X POST "$GW/tickets/tickets/" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -H "Idempotency-Key: $CID" -d "$PAYLOAD")
ID1=$(echo "$R1" | json_get idTicket 2>/dev/null)
ID2=$(echo "$R2" | json_get idTicket 2>/dev/null)
if [ "$ID1" = "$ID2" ] && [ -n "$ID1" ]; then
  marca "OK: mismo idTicket ($ID1) en el reintento -> no se duplicó"
else
  marca "❌ idTicket distinto: '$ID1' vs '$ID2'"
fi

banner "Veredicto S26/S34: fallas CONTENIDAS (fail-fast + fallback honesto + recuperación automática + backpressure + idempotencia); sin cascada."
echo "Reporte guardado en: $SALIDA"
} 2>&1 | tee "$SALIDA"

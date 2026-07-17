#!/bin/bash
# PRUEBA 2 (Fase 5, S34): 780 peticiones A LA VEZ con los límites NORMALES
# del gateway (rate limit 20/40, bulkhead tickets=12): se observa el
# backpressure (429) y el bulkhead (503) rechazando de forma controlada,
# sin que el gateway se caiga.
# Uso:  bash pruebas/02_carga_780.sh
set -u
source "$(dirname "$0")/lib/comun.sh"
verificar_sistema

TOTAL="${TOTAL:-780}"
HILOS="${HILOS:-100}"

banner "PRUEBA 2: $TOTAL PETICIONES ($HILOS trabajadores, límites normales)"
TOKEN=$(login admin admin123)

python "$(dirname "$0")/lib/carga.py" \
  --total "$TOTAL" --hilos "$HILOS" \
  --ruta "api/v1/tickets/tickets/" \
  --token "$TOKEN" --nombre "02_carga780" --salida "$RESULTADOS"

echo ""
echo "--- Interpretación ---"
echo "HTTP 200 = atendida. 429 = rate limit (backpressure del Gateway)."
echo "503 = bulkhead de 'tickets' lleno (cupo=12, este endpoint es GET ->"
echo "prioridad 'media', no aplica shedding). Ninguno es una falla: es el"
echo "sistema degradando con contrato (Fases 1-2 de S34)."
echo ""
echo "--- El Gateway sigue sano tras la ráfaga ---"
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8000/health

echo ""
echo "--- Señales del Gateway (/metrics) ---"
echo "  circuit_state tickets: $(metrica_gateway 'gateway_circuit_state{service="tickets"}')  (0=CLOSED)"
echo "  bulkhead rejects tickets: $(metrica_gateway 'gateway_bulkhead_rejects_total{razon="saturado",service="tickets"}')"
echo "  rate limit rejects: $(metrica_gateway 'gateway_rate_limit_rejects_total')"

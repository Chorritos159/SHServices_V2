#!/bin/bash
# PRUEBA 3 (Fase 5, S34): 500,000 peticiones sostenidas con 18 trabajadores.
# Amplía TEMPORALMENTE el rate limit del gateway (para medir el throughput
# real del sistema y no el del limitador) y lo RESTAURA al terminar.
# Los 18 trabajadores por defecto se alinean con el bulkhead de tickets (12)
# para que ~todo se sirva (mide el throughput real del backend). Con HILOS
# mayores se mide la contención (rechazos controlados del bulkhead). Correr
# en background:
#   bash pruebas/03_carga_500k.sh > pruebas/resultados/03_consola.log 2>&1 &
# Variables opcionales: TOTAL=... HILOS=... (para una corrida más corta)
set -u
source "$(dirname "$0")/lib/comun.sh"
verificar_sistema

TOTAL="${TOTAL:-500000}"
HILOS="${HILOS:-18}"
NOMBRE="${NOMBRE:-03_carga500k}"

restaurar_limites() {
  banner "Restaurando límites normales del gateway (20 rps / 40 burst)"
  cd "$RAIZ" && unset RATE_LIMIT_RPS RATE_LIMIT_BURST && docker compose up -d api-gateway > /dev/null 2>&1
}
trap restaurar_limites EXIT

banner "PRUEBA 3: $TOTAL PETICIONES ($HILOS trabajadores)"
echo "Ampliando el rate limit del gateway para la prueba..."
cd "$RAIZ" && RATE_LIMIT_RPS=100000 RATE_LIMIT_BURST=100000 docker compose up -d api-gateway > /dev/null 2>&1
sleep 6

TOKEN=$(login admin admin123)
INICIO=$(date +%s)

python "$(dirname "$0")/lib/carga.py" \
  --total "$TOTAL" --hilos "$HILOS" \
  --ruta "api/v1/tickets/tickets/" \
  --token "$TOKEN" --nombre "$NOMBRE" --salida "$RESULTADOS"

echo ""
echo "--- Señales del gateway al final ---"
echo "  circuit_state tickets: $(metrica_gateway 'gateway_circuit_state{service="tickets"}')  (0=CLOSED)"
echo "  requests ok: $(metrica_gateway 'gateway_proxy_requests_total{outcome="ok",service="tickets"}')"
echo "  bulkhead rechazos (saturado): $(metrica_gateway 'gateway_bulkhead_rejects_total{razon="saturado",service="tickets"}')"
echo "  reintentos: $(metrica_gateway 'gateway_retries_total{service="tickets"}')"
echo "  logs muestreados: $(metrica_gateway 'gateway_logs_sampled_total')"

echo ""
echo "Duración total del script: $(( $(date +%s) - INICIO ))s"

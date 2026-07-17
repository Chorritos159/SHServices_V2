#!/bin/bash
# PRUEBA 5 (Fase 5, S34) — nivel "1M": 15 nodos concurrentes mandando
# bloques de 120 peticiones cada uno, durante una ventana de 15 minutos.
# El nivel de carga ofrecida más alto de los tres — no completa literalmente
# 1,000,000 de peticiones (ver nota del nivel 100k). Amplía el rate limit
# temporalmente y lo RESTAURA al terminar.
# Uso:  bash pruebas/05_carga_1M.sh
set -u
source "$(dirname "$0")/lib/comun.sh"
verificar_sistema

NODOS="${NODOS:-15}"
BLOQUE="${BLOQUE:-120}"
DURACION="${DURACION:-900}"   # 15 min
NOMBRE="${NOMBRE:-05_carga1M}"

restaurar_limites() {
  banner "Restaurando límites normales del gateway (20 rps / 40 burst)"
  cd "$RAIZ" && unset RATE_LIMIT_RPS RATE_LIMIT_BURST && docker compose up -d api-gateway > /dev/null 2>&1
}
trap restaurar_limites EXIT

banner "PRUEBA 5 — nivel 1M: $NODOS nodos x bloques de $BLOQUE, ventana ${DURACION}s"
echo "Ampliando el rate limit del gateway para la prueba..."
cd "$RAIZ" && RATE_LIMIT_RPS=100000 RATE_LIMIT_BURST=100000 docker compose up -d api-gateway > /dev/null 2>&1
sleep 6

python "$(dirname "$0")/lib/carga_nodos.py" \
  --nodos "$NODOS" --bloque "$BLOQUE" --duracion-seg "$DURACION" \
  --ruta "api/v1/tickets/tickets/" --objetivo "1M" \
  --usuario admin --password admin123 \
  --nombre "$NOMBRE" --salida "$RESULTADOS"

echo ""
echo "--- Señales del gateway al final ---"
echo "  circuit_state tickets: $(metrica_gateway 'gateway_circuit_state{service="tickets"}')  (0=CLOSED)"
echo "  bulkhead rechazos (saturado): $(metrica_gateway 'gateway_bulkhead_rejects_total{razon="saturado",service="tickets"}')"
echo "  reintentos: $(metrica_gateway 'gateway_retries_total{service="tickets"}')"
echo "  logs muestreados: $(metrica_gateway 'gateway_logs_sampled_total')"

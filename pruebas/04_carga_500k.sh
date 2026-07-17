#!/bin/bash
# PRUEBA 4 (Fase 5, S34) — nivel "500k": 10 nodos concurrentes mandando
# bloques de 80 peticiones cada uno, durante una ventana de 15 minutos.
# Más carga ofrecida que el nivel 100k (más nodos, bloques más grandes),
# misma ventana acotada — no completa literalmente 500,000 peticiones (ver
# nota del nivel 100k). Amplía el rate limit temporalmente y lo RESTAURA al
# terminar.
# Uso:  bash pruebas/04_carga_500k.sh
set -u
source "$(dirname "$0")/lib/comun.sh"
verificar_sistema

NODOS="${NODOS:-10}"
BLOQUE="${BLOQUE:-80}"
DURACION="${DURACION:-900}"   # 15 min
NOMBRE="${NOMBRE:-04_carga500k}"

restaurar_limites() {
  banner "Restaurando límites normales del gateway (20 rps / 40 burst)"
  cd "$RAIZ" && unset RATE_LIMIT_RPS RATE_LIMIT_BURST && docker compose up -d api-gateway > /dev/null 2>&1
}
trap restaurar_limites EXIT

banner "PRUEBA 4 — nivel 500k: $NODOS nodos x bloques de $BLOQUE, ventana ${DURACION}s"
echo "Ampliando el rate limit del gateway para la prueba..."
cd "$RAIZ" && RATE_LIMIT_RPS=100000 RATE_LIMIT_BURST=100000 docker compose up -d api-gateway > /dev/null 2>&1
sleep 6

python "$(dirname "$0")/lib/carga_nodos.py" \
  --nodos "$NODOS" --bloque "$BLOQUE" --duracion-seg "$DURACION" \
  --ruta "api/v1/tickets/tickets/" --objetivo "500k" \
  --usuario admin --password admin123 \
  --nombre "$NOMBRE" --salida "$RESULTADOS"

echo ""
echo "--- Señales del gateway al final ---"
echo "  circuit_state tickets: $(metrica_gateway 'gateway_circuit_state{service="tickets"}')  (0=CLOSED)"
echo "  bulkhead rechazos (saturado): $(metrica_gateway 'gateway_bulkhead_rejects_total{razon="saturado",service="tickets"}')"
echo "  reintentos: $(metrica_gateway 'gateway_retries_total{service="tickets"}')"
echo "  logs muestreados: $(metrica_gateway 'gateway_logs_sampled_total')"

#!/bin/bash
# PRUEBA 3 (Fase 5, S34) — nivel "100k": 6 nodos concurrentes mandando
# bloques de 40 peticiones cada uno, durante una ventana de 10 minutos.
# No completa literalmente 100,000 peticiones (a la tasa real del sistema
# tomaría más de una hora) — el número es la ETIQUETA del nivel de carga
# ofrecida; se reporta cuánto throughput real se sostuvo en la ventana fija.
# Amplía el rate limit temporalmente (mide el throughput real del backend,
# no el techo del limitador) y lo RESTAURA al terminar.
# Uso:  bash pruebas/03_carga_100k.sh
set -u
source "$(dirname "$0")/lib/comun.sh"
verificar_sistema

NODOS="${NODOS:-6}"
BLOQUE="${BLOQUE:-40}"
DURACION="${DURACION:-600}"   # 10 min
NOMBRE="${NOMBRE:-03_carga100k}"

restaurar_limites() {
  banner "Restaurando límites normales del gateway (20 rps / 40 burst)"
  cd "$RAIZ" && unset RATE_LIMIT_RPS RATE_LIMIT_BURST && docker compose up -d api-gateway > /dev/null 2>&1
}
trap restaurar_limites EXIT

banner "PRUEBA 3 — nivel 100k: $NODOS nodos x bloques de $BLOQUE, ventana ${DURACION}s"
echo "Ampliando el rate limit del gateway para la prueba..."
cd "$RAIZ" && RATE_LIMIT_RPS=100000 RATE_LIMIT_BURST=100000 docker compose up -d api-gateway > /dev/null 2>&1
sleep 6

python "$(dirname "$0")/lib/carga_nodos.py" \
  --nodos "$NODOS" --bloque "$BLOQUE" --duracion-seg "$DURACION" \
  --ruta "api/v1/tickets/tickets/" --objetivo "100k" \
  --usuario admin --password admin123 \
  --nombre "$NOMBRE" --salida "$RESULTADOS"

echo ""
echo "--- Señales del gateway al final ---"
echo "  circuit_state tickets: $(metrica_gateway 'gateway_circuit_state{service="tickets"}')  (0=CLOSED)"
echo "  bulkhead rechazos (saturado): $(metrica_gateway 'gateway_bulkhead_rejects_total{razon="saturado",service="tickets"}')"
echo "  reintentos: $(metrica_gateway 'gateway_retries_total{service="tickets"}')"

#!/bin/bash
# Utilidades comunes de la suite de pruebas (Fase 5, S34)
GW="http://localhost:8000/api/v1"
AUTH="http://localhost:8003/api/v1/auth"   # el Gateway bloquea /auth: login va directo
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RESULTADOS="$RAIZ/pruebas/resultados"
mkdir -p "$RESULTADOS"

login() {  # login <usuario> <password> -> imprime el token
  curl -s -X POST "$AUTH/login" -H "Content-Type: application/json" \
    -d "{\"usuario\":\"$1\",\"password\":\"$2\"}" \
    | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])"
}

json_get() {  # json_get <campo>  (lee JSON de stdin)
  python -c "import sys,json;print(json.load(sys.stdin)['$1'])"
}

banner() { echo ""; echo "============================================"; echo " $1"; echo "============================================"; }

verificar_sistema() {
  if ! curl -s -o /dev/null --max-time 5 "$GW/../health"; then
    echo "❌ El gateway no responde en http://localhost:8000. Levanta el sistema: docker compose up -d"
    exit 1
  fi
}

# Lee una metrica Prometheus puntual (sin labels o con un filtro simple de
# texto) desde /metrics del Gateway. Uso: metrica_gateway "gateway_circuit_state{service=\"tickets\"}"
metrica_gateway() {
  curl -s "http://localhost:8000/metrics" | grep -F "$1" | grep -v "^#" | tail -1 | awk '{print $NF}'
}

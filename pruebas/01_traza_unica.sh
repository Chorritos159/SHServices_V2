#!/bin/bash
# PRUEBA 1 (Fase 5, S34): una operación completa trazada de inicio a fin con
# UN correlation-id — crea un ticket y verifica que el mismo trace_id aparece
# en los logs estructurados del gateway, ticket-service, auditoria-service y
# notificacion-service, y que el evento quedó persistido en ambos.
# Uso:  bash pruebas/01_traza_unica.sh
set -u
source "$(dirname "$0")/lib/comun.sh"
verificar_sistema

SALIDA="$RESULTADOS/01_traza_$(date +%Y%m%d_%H%M%S).txt"
CID="prueba1-traza-$(date +%s)"

{
banner "PRUEBA 1: TRAZA ÚNICA — correlationId $CID"
TOKEN=$(login admin admin123)

echo "Creando ticket con X-Correlation-ID: $CID ..."
RESP=$(curl -s -X POST "$GW/tickets/tickets/" -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" -H "X-Correlation-ID: $CID" \
  -d '{"datosCliente":"Cliente Traza Unica","documento_cliente":"70605040","telefono_cliente":"987654321","tipoOperacion":"SOPORTE","equipo":"Laptop HP","numero_serie":"SN-TRAZA-1","caracteristicas_falla":"No enciende","prioridad":"ALTA"}')
TK=$(echo "$RESP" | json_get idTicket 2>/dev/null)
if [ -z "$TK" ]; then echo "❌ No se pudo crear el ticket: $RESP"; exit 1; fi
echo "Ticket creado: $TK"

echo "Esperando propagación asíncrona (RabbitMQ -> auditoría/notificaciones)..."
sleep 3

banner "1. Auditoría — el evento debe aparecer con este trace_id"
curl -s "$GW/auditoria/auditoria/eventos" -H "Authorization: Bearer $TOKEN" \
  | python -c "
import sys, json
eventos = json.load(sys.stdin)
match = [e for e in eventos if e.get('trace_id') == '$CID']
print(f'  eventos con este trace_id: {len(match)}')
for e in match: print(f\"    {e['evento']} idTicket={e['idTicket']}\")"

banner "2. Notificaciones — debe existir una alerta para TECNICO"
TOKEN_TEC=$(login tecnico01 tecnico123)
curl -s "$GW/notificaciones/notificaciones/mis-alertas" -H "Authorization: Bearer $TOKEN_TEC" \
  | python -c "
import sys, json
try:
    notifs = json.load(sys.stdin)
    match = [n for n in notifs if n.get('referencia') == '$TK']
    print(f'  notificaciones referidas a este ticket ($TK): {len(match)}')
    for n in match: print(f\"    {n['mensaje']}\")
except Exception as e:
    print(f'  (no se pudo leer la bandeja: {e})')"

banner "3. Logs estructurados de los contenedores — mismo correlationId"
for c in api-gateway ticket-service auditoria-service notificacion-service; do
  n=$(docker logs "$c" --since 30s 2>&1 | grep -c "\"correlationId\": \"$CID\"")
  echo "  $c: $n líneas con correlationId=$CID"
done

echo ""
echo "Reporte guardado en: $SALIDA"
} 2>&1 | tee "$SALIDA"

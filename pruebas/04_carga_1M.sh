#!/bin/bash
# PRUEBA 4 (Fase 5, S34): 1,000,000 de peticiones sostenidas (mismo runner
# que la 3). Correr en background:
#   bash pruebas/04_carga_1M.sh > pruebas/resultados/04_consola.log 2>&1 &
set -u
TOTAL="${TOTAL:-1000000}" HILOS="${HILOS:-18}" NOMBRE="04_carga1M" \
  bash "$(dirname "$0")/03_carga_500k.sh"

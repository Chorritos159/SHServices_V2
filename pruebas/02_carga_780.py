#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRUEBA 2 (Fase 5, S34): 780 peticiones A LA VEZ con los límites
NORMALES del gateway (rate limit 20/40, bulkhead tickets=12): se observa
el backpressure (429) y el bulkhead (503) rechazando de forma controlada,
sin que el gateway se caiga.

Uso:  python pruebas/02_carga_780.py
Variables opcionales de entorno: TOTAL, HILOS
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import GW, RESULTADOS, banner, correr_runner, login, metrica_gateway, verificar_sistema  # noqa: E402

import httpx  # noqa: E402


def main():
    verificar_sistema()
    total = int(os.environ.get("TOTAL", "780"))
    hilos = int(os.environ.get("HILOS", "100"))

    banner(f"PRUEBA 2: {total} PETICIONES ({hilos} trabajadores, límites normales)")
    token = login("admin", "admin123")

    correr_runner(
        "carga.py",
        "--total", total, "--hilos", hilos,
        "--ruta", "api/v1/tickets/tickets/",
        "--token", token, "--nombre", "02_carga780", "--salida", RESULTADOS,
    )

    print()
    print("--- Interpretación ---")
    print("HTTP 200 = atendida. 429 = rate limit (backpressure del Gateway).")
    print("503 = bulkhead de 'tickets' lleno (cupo=12, este endpoint es GET ->")
    print("prioridad 'media', no aplica shedding). Ninguno es una falla: es el")
    print("sistema degradando con contrato (Fases 1-2 de S34).")

    print()
    print("--- El Gateway sigue sano tras la ráfaga ---")
    try:
        r = httpx.get(f"{GW}/health", timeout=5.0)
        print(f"HTTP {r.status_code}")
    except Exception as e:
        print(f"error: {e}")

    circuit_tickets = metrica_gateway('gateway_circuit_state{service="tickets"}')
    bulkhead_tickets = metrica_gateway('gateway_bulkhead_rejects_total{razon="saturado",service="tickets"}')
    rate_limit = metrica_gateway('gateway_rate_limit_rejects_total')

    print()
    print("--- Señales del Gateway (/metrics) ---")
    print(f"  circuit_state tickets: {circuit_tickets}  (0=CLOSED)")
    print(f"  bulkhead rejects tickets: {bulkhead_tickets}")
    print(f"  rate limit rejects: {rate_limit}")


if __name__ == "__main__":
    main()

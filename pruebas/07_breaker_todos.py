#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRUEBA 7 (Fase 7, S34): el circuit breaker abre para TODOS los servicios.

Regresion de un bug real: `tickets` es el unico servicio que el Gateway
alcanza via Toxiproxy. Al caer su upstream, Toxiproxy sigue vivo y acepta
la conexion TCP, luego la cierra -> httpx.ReadError (no ConnectError). El
proxy solo capturaba ConnectError/TimeoutException, asi que el ReadError se
escapaba al manejador global: el cliente recibia un 500 opaco y el breaker
NUNCA se enteraba del fallo. El circuito de tickets se quedaba en CLOSED
con el servicio caido.

Esta prueba tumba CADA servicio, uno por uno, y exige lo mismo para todos:
503 (no 500) y circuito en OPEN. Al terminar, restaura todo.

Uso:  python pruebas/07_breaker_todos.py
"""
import os
import subprocess
import sys
import time
from datetime import datetime

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import GW, RESULTADOS, login, metrica_gateway, verificar_sistema  # noqa: E402

# servicio del Gateway -> (contenedor a tumbar, ruta de prueba)
SERVICIOS = {
    "tickets": ("ticket-service", "api/v1/tickets/tickets/"),
    "almacen": ("almacen-service", "api/v1/almacen/almacen/productos"),
    "diagnosticos": ("diagnostico-service", "api/v1/diagnosticos/diagnosticos/por-ticket/TICK-X"),
    "facturas": ("facturacion-service", "api/v1/facturas/facturas/"),
    "auditoria": ("auditoria-service", "api/v1/auditoria/auditoria/eventos"),
    "notificaciones": ("notificacion-service", "api/v1/notificaciones/notificaciones/mis-alertas"),
}
COOLDOWN = 15   # el breaker espera 15s antes de la sonda HALF_OPEN


def main():
    verificar_sistema()
    salida, fallos = [], []

    def out(linea=""):
        print(linea)
        salida.append(linea)

    token = login("admin", "admin123")
    headers = {"Authorization": f"Bearer {token}"}

    out("=" * 60)
    out(" PRUEBA 7: el circuit breaker abre para TODOS los servicios")
    out("=" * 60)
    out("Regresion del bug: 'tickets' va via Toxiproxy -> ReadError (no")
    out("ConnectError). Antes: 500 opaco y circuito CLOSED con el servicio caido.")

    for servicio, (contenedor, ruta) in SERVICIOS.items():
        out(f"\n--- {servicio}  (contenedor: {contenedor}) ---")
        estado_previo = metrica_gateway(f'gateway_circuit_state{{service="{servicio}"}}')
        out(f"  circuito antes: {estado_previo}  (0=CLOSED)")

        subprocess.run(["docker", "stop", contenedor], capture_output=True)
        time.sleep(1)

        codigos = []
        for _ in range(5):
            try:
                r = httpx.get(f"{GW}/{ruta}", headers=headers, timeout=15.0)
                codigos.append(r.status_code)
            except Exception as exc:
                codigos.append(type(exc).__name__)
        out(f"  respuestas con el servicio caido: {codigos}")

        estado = metrica_gateway(f'gateway_circuit_state{{service="{servicio}"}}')
        out(f"  circuito despues: {estado}  (2=OPEN esperado)")

        # Criterio: ni un solo 500 (eso seria el bug) y el circuito debe abrir.
        hubo_500 = any(c == 500 for c in codigos)
        abrio = estado.startswith("2")
        if hubo_500:
            fallos.append(f"{servicio}: devolvio 500 (el error se escapo del proxy)")
            out("  FALLO: hubo 500 -> el error no lo maneja el proxy resiliente")
        if not abrio:
            fallos.append(f"{servicio}: el circuito NO abrio (quedo en {estado})")
            out("  FALLO: el circuito no abrio")
        if not hubo_500 and abrio:
            out("  OK: 503 controlado y circuito OPEN")

        subprocess.run(["docker", "start", contenedor], capture_output=True)
        out(f"  {contenedor} restaurado; esperando cooldown ({COOLDOWN}s) + arranque...")
        time.sleep(COOLDOWN + 8)

        # Sonda: el circuito debe cerrarse solo tras el cooldown.
        try:
            httpx.get(f"{GW}/{ruta}", headers=headers, timeout=15.0)
        except Exception:
            pass
        estado_final = metrica_gateway(f'gateway_circuit_state{{service="{servicio}"}}')
        out(f"  circuito tras recuperacion: {estado_final}  (0=CLOSED esperado)")
        if not estado_final.startswith("0"):
            fallos.append(f"{servicio}: no se recupero solo (quedo en {estado_final})")

    out("\n" + "=" * 60)
    if fallos:
        out(f" RESULTADO: {len(fallos)} FALLO(S)")
        for f in fallos:
            out(f"   - {f}")
    else:
        out(" RESULTADO: OK — los 6 servicios abren el circuito y se recuperan solos.")
    out("=" * 60)

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_rep = f"{RESULTADOS}/07_breaker_todos_{marca}.txt"
    with open(ruta_rep, "w", encoding="utf-8") as f:
        f.write("\n".join(salida) + "\n")
    print(f"Reporte guardado en: {ruta_rep}")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()

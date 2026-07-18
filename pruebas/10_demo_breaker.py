#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRUEBA 10: DEMO VISIBLE del circuit breaker para UN servicio.

Sirve para MOSTRAR el circuit breaker en Grafana / /metrics, paso a paso:

  1. Estado inicial: circuito CLOSED (0).
  2. `docker pause` al contenedor -> el servicio queda caido pero NO se reinicia
     (pause congela; restart:always NO actua sobre un pausado).
  3. Se le manda TRAFICO: los primeros fallos ABREN el circuito (CLOSED->OPEN)
     y los siguientes son fail-fast (<100ms, sin tocar la dependencia).
  4. El circuito se queda OPEN unos segundos -> tiempo para verlo en Grafana.
  5. `docker unpause` y, SIN mandar mas trafico, la sonda activa del Gateway
     cierra el circuito solo (OPEN -> CLOSED) en ~15-20s.

Por que "pauso y no sale el circuit breaker": porque el breaker solo abre si VE
fallos, y solo los ve si le llega trafico mientras el servicio esta caido.
Pausar sin mandar peticiones deja el circuito CLOSED (no ha visto ningun fallo).

Uso:
  python pruebas/10_demo_breaker.py            # por defecto: tickets
  python pruebas/10_demo_breaker.py almacen
  python pruebas/10_demo_breaker.py diagnosticos|facturas|auditoria|notificaciones
"""
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import GW, banner, login, verificar_sistema, docker, metrica_gateway  # noqa: E402

# service (clave del Gateway) -> (contenedor docker, ruta GET para mandar trafico)
SERVICIOS = {
    "tickets":        ("ticket-service",       "/api/v1/tickets/tickets/pendientes"),
    "almacen":        ("almacen-service",      "/api/v1/almacen/almacen/productos"),
    "diagnosticos":   ("diagnostico-service",  "/api/v1/diagnosticos/asignaciones/mias"),
    "facturas":       ("facturacion-service",  "/api/v1/facturas/facturas/"),
    "auditoria":      ("auditoria-service",    "/api/v1/auditoria/auditoria/eventos"),
    "notificaciones": ("notificacion-service", "/api/v1/notificaciones/notificaciones/mis-alertas"),
}

ESTADO = {"0": "CLOSED", "0.0": "CLOSED", "1": "HALF_OPEN", "1.0": "HALF_OPEN", "2": "OPEN", "2.0": "OPEN"}


def estado_circuito(service: str) -> str:
    v = metrica_gateway(f'gateway_circuit_state{{service="{service}"}}')
    return f"{ESTADO.get(v, '?')} ({v})"


def main():
    service = sys.argv[1] if len(sys.argv) > 1 else "tickets"
    if service not in SERVICIOS:
        print(f"Servicio '{service}' no valido. Opciones: {', '.join(SERVICIOS)}")
        sys.exit(1)
    contenedor, ruta = SERVICIOS[service]

    banner(f"DEMO circuit breaker: servicio '{service}' (contenedor {contenedor})")
    verificar_sistema()
    token = login("admin", "admin123")
    hdr = {"Authorization": f"Bearer {token}"}

    print(f"\n1) Estado inicial del circuito: {estado_circuito(service)}")

    print(f"\n2) PAUSO el contenedor '{contenedor}' (queda caido, NO se reinicia solo)...")
    docker("pause", contenedor)
    time.sleep(1)

    print("\n3) Mando 6 peticiones mientras esta caido (esto ABRE el circuito):")
    for i in range(1, 7):
        t0 = time.monotonic()
        try:
            r = httpx.get(f"{GW}{ruta}", headers=hdr, timeout=10.0)
            code = r.status_code
        except httpx.HTTPError as exc:
            code = type(exc).__name__
        ms = round((time.monotonic() - t0) * 1000)
        print(f"   req{i}: HTTP {code}  ({ms} ms)   circuito -> {estado_circuito(service)}")
        time.sleep(0.5)

    print(f"\n   >>> El circuito quedo: {estado_circuito(service)}")
    print("   (fijate como los ultimos son fail-fast: pocos ms, ya ni llama a la dependencia)")

    ESPERA_OPEN = 15
    print(f"\n4) Dejo el circuito OPEN {ESPERA_OPEN}s para que lo veas en Grafana")
    print("   (panel 'gateway_circuit_state' -> 2 = OPEN) ...")
    for s in range(ESPERA_OPEN, 0, -5):
        print(f"   ... {s}s   circuito = {estado_circuito(service)}")
        time.sleep(5)

    print(f"\n5) UNPAUSE '{contenedor}'. A partir de aqui NO mando mas trafico:")
    docker("unpause", contenedor)
    time.sleep(2)
    # Red de seguridad: en algunos Docker Desktop (WSL2) el unpause deja el
    # contenedor Exited. Si es asi, lo arrancamos para que el servicio REALMENTE
    # vuelva; si no, el circuito seguiria OPEN con razon (el servicio no responde).
    estado_cont = docker("ps", "--filter", f"name={contenedor}", "--format", "{{.Status}}").stdout.strip()
    if not estado_cont.startswith("Up"):
        print(f"   ('{contenedor}' quedo caido tras el unpause; lo arranco con docker start)")
        docker("start", contenedor)
    print("   la SONDA ACTIVA del Gateway debe cerrar el circuito sola...")
    cerrado = False
    for i in range(1, 9):  # hasta ~40s
        time.sleep(5)
        est = estado_circuito(service)
        print(f"   +{i*5}s sin trafico: circuito = {est}")
        if est.startswith("CLOSED"):
            cerrado = True
            break

    print()
    if cerrado:
        print("   RESULTADO: el circuito se cerro SOLO tras revivir el servicio. OK.")
    else:
        print("   RESULTADO: el circuito aun no cerraba; dale unos segundos mas y revisa /metrics.")
    print(f"\n   Ver en vivo:  curl.exe http://localhost:8000/metrics | Select-String circuit_state")


if __name__ == "__main__":
    main()

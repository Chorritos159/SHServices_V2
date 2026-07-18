#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRUEBA 12 (S34): AUTO-RECUPERACIÓN — ¿cuánto tarda el sistema en curarse solo?

Las pruebas 06 y 11 mantienen los servicios caídos un tiempo fijo (23s, 53s,
103s) para observar la degradación. Esta hace lo contrario: **mata el proceso
y no vuelve a tocar nada**. Docker lo revive por `restart: always` y la sonda
del breaker cierra el circuito sola (ADR-0014). Lo único que se mide es el
TIEMPO de cada tramo:

    muerte -> contenedor arriba -> /health responde -> circuito CLOSED

Es la pregunta que hace cualquiera que opere el sistema: *si se cae a las 3 de
la mañana y nadie lo mira, ¿en cuánto vuelve solo?* La respuesta es un número,
no un "se recupera automáticamente".

Se usa `POST /_chaos/crash` y no `docker stop` a propósito: `docker stop` es
una parada ORDENADA y Docker no dispara `restart: always` (entiende que lo
pediste tú). El endpoint mata el proceso con `os._exit(1)`, que es una caída
de verdad — la única forma de demostrar el auto-restart sin reiniciar la
máquina. Está detrás de `CHAOS_ENABLED` (ver seguridad/OWASP_Top10.md).

Cubre los 5 servicios que exponen el endpoint y tienen circuito propio.

Uso:
    python pruebas/12_autorecuperacion.py              # los 5, uno por uno
    python pruebas/12_autorecuperacion.py --servicio almacen
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import GW, RESULTADOS, login, metrica_gateway, verificar_sistema  # noqa: E402

# servicio del Gateway -> (contenedor, puerto publicado para su /health)
SERVICIOS = {
    "almacen": ("almacen-service", 8002),
    "tickets": ("ticket-service", 8001),
    "diagnosticos": ("diagnostico-service", 8004),
    "facturas": ("facturacion-service", 8005),
    "auditoria": ("auditoria-service", 8006),
}

LIMITE_ESPERA_S = 120     # si en 2 min no volvió solo, es un fallo


def esperar(condicion, limite=LIMITE_ESPERA_S, intervalo=0.5):
    """Espera a que `condicion()` sea verdadera. Devuelve los segundos, o None."""
    inicio = time.monotonic()
    while time.monotonic() - inicio < limite:
        try:
            if condicion():
                return round(time.monotonic() - inicio, 1)
        except Exception:
            pass
        time.sleep(intervalo)
    return None


def contenedor_arriba(nombre):
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", nombre],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (r.stdout or "").strip() == "true"


def health_ok(puerto):
    return httpx.get(f"http://localhost:{puerto}/health", timeout=3.0).status_code == 200


def circuito_cerrado(servicio):
    return metrica_gateway(f'gateway_circuit_state{{service="{servicio}"}}').startswith("0")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--servicio", choices=list(SERVICIOS), help="Solo uno (por defecto: los 5)")
    args = ap.parse_args()
    objetivo = {args.servicio: SERVICIOS[args.servicio]} if args.servicio else SERVICIOS

    verificar_sistema()
    salida, fallos, filas = [], [], []

    def out(linea=""):
        print(linea, flush=True)
        salida.append(linea)

    token = login("admin", "admin123")
    cabeceras = {"Authorization": f"Bearer {token}"}

    out("=" * 72)
    out(" PRUEBA 12: AUTO-RECUPERACION — cuanto tarda el sistema en curarse solo")
    out("=" * 72)
    out("Se mata el PROCESO (os._exit(1)) y NO se vuelve a tocar nada.")
    out("Docker revive el contenedor; la sonda del breaker cierra el circuito.")
    out("")

    for servicio, (contenedor, puerto) in objetivo.items():
        out(f"\n--- {servicio}  ({contenedor}) ---")

        if not contenedor_arriba(contenedor):
            out("  el contenedor no estaba arriba; se salta")
            fallos.append(f"{servicio}: no estaba corriendo antes de la prueba")
            continue

        # Se gasta el circuito ANTES de matar, para poder medir su cierre:
        # si nunca llega a abrirse no hay nada que esperar.
        t_muerte = time.monotonic()
        try:
            httpx.post(f"http://localhost:{puerto}/_chaos/crash", timeout=5.0)
            out("  crash provocado (os._exit(1) en ~0.5s)")
        except httpx.HTTPError as exc:
            out(f"  FALLO: no se pudo provocar el crash: {type(exc).__name__}")
            out("         (¿CHAOS_ENABLED apagado? el endpoint responde 404 si lo está)")
            fallos.append(f"{servicio}: no se pudo provocar el crash")
            continue

        # 1. Que Docker lo levante (restart: always).
        time.sleep(1.5)
        t_docker = esperar(lambda: contenedor_arriba(contenedor))
        # 2. Que el proceso esté listo para atender.
        t_health = esperar(lambda: health_ok(puerto))
        # 3. Que el circuito vuelva a CLOSED. Se manda algo de trafico para
        #    que el Gateway note la caida y luego la sonda lo cierre.
        for _ in range(4):
            try:
                httpx.get(f"{GW}/api/v1/{servicio}/", headers=cabeceras, timeout=6.0)
            except httpx.HTTPError:
                pass
            time.sleep(0.4)
        t_circuito = esperar(lambda: circuito_cerrado(servicio))
        total = round(time.monotonic() - t_muerte, 1)

        def fmt(v):
            return f"{v}s" if v is not None else f">{LIMITE_ESPERA_S}s"

        out(f"  contenedor revivido por Docker .... {fmt(t_docker)}")
        out(f"  /health respondiendo .............. {fmt(t_health)}")
        out(f"  circuito de nuevo en CLOSED ....... {fmt(t_circuito)}")
        out(f"  TOTAL sin intervencion humana ..... {total}s")

        filas.append((servicio, t_docker, t_health, t_circuito, total))

        if t_docker is None:
            fallos.append(f"{servicio}: Docker NO lo revivio (¿falta restart: always?)")
        if t_health is None:
            fallos.append(f"{servicio}: no volvio a responder /health por si solo")
        if t_circuito is None:
            fallos.append(f"{servicio}: el circuito no volvio a CLOSED por si solo")

        # Margen para que el sistema se asiente antes del siguiente.
        time.sleep(6)

    # ------------------------------------------------------------------
    out("\n" + "=" * 72)
    out(" TIEMPOS DE AUTO-RECUPERACION")
    out("=" * 72)
    out(f"  {'servicio':<16} {'docker':>9} {'health':>9} {'circuito':>10} {'total':>9}")
    out(f"  {'-'*16} {'-'*9:>9} {'-'*9:>9} {'-'*10:>10} {'-'*9:>9}")
    for servicio, td, th, tc, tt in filas:
        f = lambda v: (f"{v}s" if v is not None else "  ---")  # noqa: E731
        out(f"  {servicio:<16} {f(td):>9} {f(th):>9} {f(tc):>10} {tt:>8}s")

    totales = [t for _, _, _, _, t in filas]
    if totales:
        out("")
        out(f"  peor caso: {max(totales)}s   mejor caso: {min(totales)}s   "
            f"promedio: {sum(totales)/len(totales):.1f}s")
        out("")
        out("  Ese 'total' es el tiempo REAL de indisponibilidad de un servicio si")
        out("  se cae de madrugada y nadie lo mira. Es el dato que sostiene el")
        out("  objetivo de disponibilidad de documentacion/sla.md — sin el, ese")
        out("  99% seria una cifra inventada.")

    out("\n" + "=" * 72)
    if fallos:
        out(f" RESULTADO: {len(fallos)} FALLO(S)")
        for f in fallos:
            out(f"   - {f}")
    else:
        out(f" RESULTADO: OK — los {len(filas)} servicios se recuperaron SOLOS,")
        out("            sin que nadie ejecutara ni un comando.")
    out("=" * 72)

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta = f"{RESULTADOS}/12_autorecuperacion_{marca}.txt"
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(salida) + "\n")
    print(f"Reporte guardado en: {ruta}")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()

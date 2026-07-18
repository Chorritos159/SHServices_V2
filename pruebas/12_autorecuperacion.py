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

CON CARGA DE FONDO (`--nivel`)
Medir la recuperación con el sistema en reposo da el MEJOR caso y lo presenta
como si fuera el habitual: un proceso arranca mucho más rápido en una máquina
que no está haciendo nada. Con `--nivel` se lanza carga real (igual que la
prueba 11) y los servicios se curan **mientras atienden tráfico**, que es lo
que pasaría de verdad. Además se reporta qué sufrió ese tráfico: si matar 5
procesos produjo o no alguna respuesta fuera de contrato.

Uso:
    python pruebas/12_autorecuperacion.py                 # reposo (mejor caso)
    python pruebas/12_autorecuperacion.py --nivel 500k    # ~6 min, el numero real
    python pruebas/12_autorecuperacion.py --nivel 1M      # ~8 min
    python pruebas/12_autorecuperacion.py --servicio almacen
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time
from datetime import datetime

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import (GW, LIB, RAIZ, RESULTADOS, ampliar_rate_limit, login,  # noqa: E402
                   metrica_gateway, restaurar_rate_limit, RUTAS_TODOS_SERVICIOS,
                   verificar_sistema)

# servicio del Gateway -> (contenedor, puerto publicado para su /health)
SERVICIOS = {
    "almacen": ("almacen-service", 8002),
    "tickets": ("ticket-service", 8001),
    "diagnosticos": ("diagnostico-service", 8004),
    "facturas": ("facturacion-service", 8005),
    "auditoria": ("auditoria-service", 8006),
}

# Carga de fondo mientras se mide. `reposo` = sin carga (mejor caso). Las
# ventanas dan de sobra para los 5 ciclos de crash + recuperacion.
NIVELES = {
    "reposo": None,
    "100k": {"nodos": 4, "bloque": 16, "duracion": 180},
    "500k": {"nodos": 6, "bloque": 20, "duracion": 300},
    "1M":   {"nodos": 8, "bloque": 24, "duracion": 420},
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
    ap.add_argument("--nivel", choices=list(NIVELES), default="reposo",
                    help="Carga de fondo mientras se mide (por defecto: reposo, sin carga)")
    args = ap.parse_args()
    objetivo = {args.servicio: SERVICIOS[args.servicio]} if args.servicio else SERVICIOS
    cfg = NIVELES[args.nivel]

    verificar_sistema()
    salida, fallos, filas = [], [], []
    proceso_carga = None

    def out(linea=""):
        print(linea, flush=True)
        salida.append(linea)

    token = login("admin", "admin123")
    cabeceras = {"Authorization": f"Bearer {token}"}

    out("=" * 72)
    out(f" PRUEBA 12: AUTO-RECUPERACION — cuanto tarda en curarse solo [{args.nivel}]")
    out("=" * 72)
    out("Se mata el PROCESO (os._exit(1)) y NO se vuelve a tocar nada.")
    out("Docker revive el contenedor; la sonda del breaker cierra el circuito.")
    out("")

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_carga = f"12_autorec_carga_{args.nivel}"

    if cfg:
        # Con trafico encima el numero es OTRO, y es el que vale: arrancar un
        # proceso mientras 6 nodos le piden cosas no es lo mismo que arrancarlo
        # en una maquina en reposo. Medir solo en reposo da el mejor caso y lo
        # presenta como si fuera el habitual.
        out(f"Carga de fondo: {cfg['nodos']} nodos x bloques de {cfg['bloque']} "
            f"durante {cfg['duracion']}s.")
        out("El sistema se esta curando MIENTRAS atiende trafico real.")
        out("")
        ampliar_rate_limit()
        proceso_carga = subprocess.Popen(
            [sys.executable, os.path.join(LIB, "carga_nodos.py"),
             "--nodos", str(cfg["nodos"]), "--bloque", str(cfg["bloque"]),
             "--duracion-seg", str(cfg["duracion"]),
             "--rutas", RUTAS_TODOS_SERVICIOS, "--objetivo", args.nivel,
             "--usuario", "admin", "--password", "admin123",
             "--nombre", nombre_carga, "--salida", RESULTADOS, "--mixto", "1"],
            cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        out("Calentando 15s antes del primer crash...")
        time.sleep(15)
    else:
        out("Sin carga de fondo (mejor caso). Usa --nivel 500k para el numero real.")
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
    # Cerrar la carga de fondo y ver qué sufrió el tráfico mientras el sistema
    # se curaba solo.
    resumen_carga = None
    if proceso_carga is not None:
        out("\n[fin de los crashes] Esperando a que la carga cierre su ventana...")
        try:
            proceso_carga.wait(timeout=cfg["duracion"] + 120)
        except subprocess.TimeoutExpired:
            proceso_carga.terminate()
        restaurar_rate_limit()

        reportes = sorted(glob.glob(os.path.join(RESULTADOS, f"{nombre_carga}_*.json")))
        if reportes:
            with open(reportes[-1], encoding="utf-8") as f:
                rep = json.load(f)
            codigos = {int(k): v for k, v in rep["codigos"].items() if k.isdigit()}
            total_req = rep["enviadas"]
            ok = sum(v for k, v in codigos.items() if k < 400)
            s500 = codigos.get(500, 0)
            resumen_carga = (rep, total_req, ok, s500)

            out("\n" + "=" * 72)
            out(" QUE SUFRIO EL TRAFICO MIENTRAS EL SISTEMA SE CURABA")
            out("=" * 72)
            out(f"  peticiones enviadas .......... {total_req}")
            out(f"  throughput ................... {rep['throughput_rps']} rps")
            out(f"  atendidas con exito .......... {ok}  ({ok/total_req*100:.1f}%)")
            out(f"  ERRORES OPACOS (500) ......... {s500}")
            out(f"  latencia p95 / p99 ........... {rep['latencia_ms']['p95']} / "
                f"{rep['latencia_ms']['p99']} ms")
            out(f"  codigos ...................... {rep['codigos']}")
            if s500 > 0:
                fallos.append(f"hubo {s500} respuestas 500 durante los crashes")
                out("\n  FALLO: aparecieron errores 500 (la falla no quedo contenida)")
            else:
                out("\n  OK: cero errores 500 — matar 5 procesos con trafico encima no")
                out("      produjo ni una respuesta fuera de contrato")

    out("\n" + "=" * 72)
    out(f" TIEMPOS DE AUTO-RECUPERACION [{args.nivel}]")
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
        if args.nivel == "reposo":
            out("")
            out("  OJO: medido en REPOSO, o sea el MEJOR caso. Con trafico encima el")
            out("  arranque compite por CPU y el numero sube. Corre --nivel 500k para")
            out("  el dato defendible.")
        else:
            out("")
            out(f"  Medido BAJO CARGA ({args.nivel}): el servicio arranco compitiendo por")
            out("  CPU con el trafico real. Este es el numero que vale, no el de reposo.")

    out("\n" + "=" * 72)
    if fallos:
        out(f" RESULTADO: {len(fallos)} FALLO(S)")
        for f in fallos:
            out(f"   - {f}")
    else:
        out(f" RESULTADO: OK — los {len(filas)} servicios se recuperaron SOLOS,")
        out("            sin que nadie ejecutara ni un comando.")
    out("=" * 72)

    ruta = f"{RESULTADOS}/12_autorecuperacion_{args.nivel}_{marca}.txt"
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(salida) + "\n")
    print(f"Reporte guardado en: {ruta}")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()

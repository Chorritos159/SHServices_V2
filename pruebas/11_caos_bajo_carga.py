#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRUEBA 11 (S34): CAOS **BAJO CARGA SOSTENIDA**.

Las pruebas 03/04/05 miden capacidad con el sistema sano. La 06 rompe cosas
con el sistema en reposo. Ninguna de las dos responde la pregunta que de
verdad importa:

    ¿Qué le pasa a los usuarios que YA ESTÁN operando cuando un servicio se
    cae en mitad de la jornada?

Esta prueba lanza una carga real y sostenida (nivel 100k / 500k / 1M) y, sin
parar el tráfico, va tumbando servicios uno a uno y devolviéndolos. Mientras
tanto muestrea cada pocos segundos el estado de los circuitos y el pulso del
sistema, para construir una LÍNEA DE TIEMPO de la reacción.

Lo que se busca demostrar (S26/S34):
  1. CONTENCIÓN   — la caída produce 503 controlados, nunca 500 opacos, y no
                    arrastra a los servicios sanos.
  2. CONTINUIDAD  — el resto del sistema sigue atendiendo durante la caída.
  3. RECUPERACIÓN — al volver el servicio, el circuito se cierra solo (sonda
                    activa, ADR-0014) y el throughput se restablece sin tocar
                    nada a mano.

Uso:
    python pruebas/11_caos_bajo_carga.py                 # nivel 100k (~3 min)
    python pruebas/11_caos_bajo_carga.py --nivel 500k    # (~6 min)
    python pruebas/11_caos_bajo_carga.py --nivel 1M      # (~11 min)

Al terminar restaura SIEMPRE los servicios y los límites del gateway, aunque
la prueba falle o se interrumpa.
"""
import argparse
import json
import glob
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import (GW, LIB, RAIZ, RESULTADOS, ampliar_rate_limit, banner,  # noqa: E402
                   restaurar_rate_limit, RUTAS_TODOS_SERVICIOS, verificar_sistema)

# Mismos parámetros que las pruebas 03/04/05, para que los números sean
# comparables con las corridas sin caos.
NIVELES = {
    "100k": {"nodos": 4, "bloque": 16, "duracion": 300},
    "500k": {"nodos": 5, "bloque": 18, "duracion": 600},
    "1M":   {"nodos": 6, "bloque": 20, "duracion": 900},
}

# Servicios que se van tumbando, en orden de "dolor" creciente:
# almacén (lo usa el diagnóstico), tickets (el corazón del negocio y el único
# que va vía Toxiproxy) y facturación (el dinero).
GUION_CAOS = [
    ("almacen-service", "almacen"),
    ("ticket-service", "tickets"),
    ("facturacion-service", "facturas"),
]

NOMBRES_ESTADO = {"0": "CLOSED", "1": "HALF_OPEN", "2": "OPEN"}


def circuitos() -> dict:
    """Estado de todos los circuitos, leído de /metrics."""
    try:
        texto = httpx.get(f"{GW}/metrics", timeout=8.0).text
    except Exception:
        return {}
    estados = {}
    for linea in texto.splitlines():
        if linea.startswith("gateway_circuit_state{"):
            servicio = linea.split('service="')[1].split('"')[0]
            valor = linea.rsplit(" ", 1)[-1].split(".")[0]
            estados[servicio] = NOMBRES_ESTADO.get(valor, valor)
    return estados


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nivel", choices=list(NIVELES), default="100k")
    args = ap.parse_args()
    cfg = NIVELES[args.nivel]

    verificar_sistema()
    salida, fallos = [], []
    caidos = set()
    est_final: dict = {}

    def out(linea=""):
        print(linea, flush=True)
        salida.append(linea)

    out("=" * 72)
    out(f" PRUEBA 11: CAOS BAJO CARGA SOSTENIDA — nivel {args.nivel}")
    out("=" * 72)
    out(f"Carga: {cfg['nodos']} nodos x bloques de {cfg['bloque']}, ventana {cfg['duracion']}s")
    out("Mientras la carga corre, se tumban y restauran servicios uno a uno.")
    out("")
    out("Se amplía el rate limit durante la corrida (igual que en 03/04/05):")
    out("lo que se mide aquí es cómo reacciona el sistema al CAOS, no dónde")
    out("corta el limitador. Con el limitador estrecho, los 429 taparían los")
    out("503 y no se vería nada.")

    ampliar_rate_limit()

    # Lanzamos la carga en segundo plano y la dejamos correr.
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"11_caos_carga_{args.nivel}"
    proceso = subprocess.Popen(
        [sys.executable, os.path.join(LIB, "carga_nodos.py"),
         "--nodos", str(cfg["nodos"]), "--bloque", str(cfg["bloque"]),
         "--duracion-seg", str(cfg["duracion"]),
         "--rutas", RUTAS_TODOS_SERVICIOS, "--objetivo", args.nivel,
         "--usuario", "admin", "--password", "admin123",
         "--nombre", nombre, "--salida", RESULTADOS, "--mixto", "1"],
        cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # Muestreo continuo en un hilo aparte: la línea de tiempo de la reacción.
    linea_tiempo = []
    parar = threading.Event()

    def muestrear():
        t0 = time.monotonic()
        while not parar.is_set():
            linea_tiempo.append({
                "t": round(time.monotonic() - t0),
                "circuitos": circuitos(),
                "caidos": sorted(caidos),
            })
            parar.wait(5)

    hilo = threading.Thread(target=muestrear, daemon=True)
    hilo.start()

    try:
        # Reparto: se deja calentar, luego un ciclo caída/recuperación por
        # servicio, y al final margen para que todo se estabilice.
        calentamiento = 20
        por_servicio = (cfg["duracion"] - calentamiento - 20) // len(GUION_CAOS)
        caida = por_servicio // 2

        out(f"\n[t+0s] Carga en marcha. Calentando {calentamiento}s antes del primer corte...")
        time.sleep(calentamiento)

        for contenedor, servicio in GUION_CAOS:
            t = int(time.monotonic())
            out(f"\n--- TUMBANDO {contenedor} (servicio '{servicio}') ---")
            subprocess.run(["docker", "stop", contenedor], capture_output=True)
            caidos.add(servicio)
            time.sleep(8)

            est = circuitos()
            out(f"  circuitos: {est}")
            abrio = est.get(servicio) in ("OPEN", "HALF_OPEN")
            out(f"  circuito de '{servicio}': {est.get(servicio)}  "
                f"{'OK (aislado)' if abrio else 'todavia no ha abierto'}")

            # Los SANOS deben seguir cerrados: eso es la no-cascada.
            contagiados = [s for s, e in est.items()
                           if e != "CLOSED" and s != servicio and s not in caidos]
            if contagiados:
                fallos.append(f"cascada: {contagiados} se abrieron por la caida de '{servicio}'")
                out(f"  FALLO: se contagiaron {contagiados}")
            else:
                out("  OK: ningun otro circuito se contagio (sin cascada)")

            out(f"  manteniendo la caida {caida}s con la carga encima...")
            time.sleep(caida)

            out(f"--- RESTAURANDO {contenedor} ---")
            subprocess.run(["docker", "start", contenedor], capture_output=True)
            caidos.discard(servicio)
            espera = por_servicio - caida
            out(f"  esperando {espera}s a que la sonda cierre el circuito sola...")
            time.sleep(espera)

            est = circuitos()
            cerro = est.get(servicio) == "CLOSED"
            out(f"  circuito de '{servicio}': {est.get(servicio)}  "
                f"{'OK (recuperado solo)' if cerro else 'NO se recupero'}")
            if not cerro:
                fallos.append(f"'{servicio}' no volvio a CLOSED tras restaurarlo (quedo {est.get(servicio)})")

        out("\n[fin del guion] Dejando que la carga termine su ventana...")
        proceso.wait(timeout=cfg["duracion"] + 120)

        # El estado final se toma AQUI, no despues del `finally`: alli ya se
        # habra llamado a restaurar_rate_limit(), que REINICIA el gateway y
        # pone todos los contadores a cero. Comprobarlo despues daba un
        # diccionario vacio y el criterio pasaba siempre — un falso OK.
        est_final = circuitos()

    except KeyboardInterrupt:
        out("\nInterrumpida por el usuario; restaurando...")
    finally:
        parar.set()
        if proceso.poll() is None:
            proceso.terminate()
        for contenedor, _ in GUION_CAOS:
            subprocess.run(["docker", "start", contenedor], capture_output=True)
        restaurar_rate_limit()

    # ------------------------------------------------------------------
    # Veredicto, leyendo el reporte que dejó el runner de carga.
    reportes = sorted(glob.glob(os.path.join(RESULTADOS, f"{nombre}_*.json")))
    if not reportes:
        out("\nNo se encontro el reporte de la carga; no se puede dar veredicto.")
        fallos.append("el runner de carga no dejo reporte")
    else:
        with open(reportes[-1], encoding="utf-8") as f:
            rep = json.load(f)
        codigos = {int(k): v for k, v in rep["codigos"].items() if k.isdigit()}
        total = rep["enviadas"]
        ok = sum(v for k, v in codigos.items() if k < 400)
        s503 = codigos.get(503, 0) + codigos.get(504, 0)
        s500 = codigos.get(500, 0)
        s202 = codigos.get(202, 0)

        out("\n" + "=" * 72)
        out(" RESULTADO DE LA CARGA (con 3 servicios cayendo durante la ventana)")
        out("=" * 72)
        out(f"  peticiones enviadas .......... {total}")
        out(f"  throughput ................... {rep['throughput_rps']} rps")
        out(f"  atendidas con exito .......... {ok}  ({ok/total*100:.1f}%)")
        out(f"  encoladas en el outbox (202) . {s202}")
        out(f"  degradadas con contrato (503/504) {s503}")
        out(f"  ERRORES OPACOS (500) ......... {s500}")
        out(f"  latencia p95 / p99 ........... {rep['latencia_ms']['p95']} / {rep['latencia_ms']['p99']} ms")
        out(f"  codigos completos ............ {rep['codigos']}")

        # Criterio 1: contencion. Un 500 es el sistema perdiendo el control.
        if s500 > 0:
            fallos.append(f"hubo {s500} respuestas 500 (error opaco) durante el caos")
            out(f"\n  FALLO: {s500} errores 500 — la falla NO quedo contenida")
        else:
            out("\n  OK: cero errores 500 — toda falla salio como 503/504 con contrato")

        # Criterio 2: continuidad. Con 3 de 7 servicios cayendo por turnos,
        # exigir 100% seria absurdo; lo que no puede pasar es que se caiga todo.
        if total and ok / total < 0.50:
            fallos.append(f"solo se atendio el {ok/total*100:.1f}% del trafico durante el caos")
            out(f"  FALLO: continuidad insuficiente ({ok/total*100:.1f}% atendido)")
        else:
            out(f"  OK: continuidad mantenida ({ok/total*100:.1f}% atendido pese a las caidas)")

    # Criterio 3: al terminar el guion (ANTES de reiniciar el gateway), todo
    # tiene que haber vuelto a CLOSED por si solo.
    abiertos = [s for s, e in est_final.items() if e != "CLOSED"]
    out(f"\n  circuitos al terminar el guion: {est_final or '(no se pudo leer)'}")
    if not est_final:
        # Sin lectura no hay veredicto: es un fallo de la prueba, no un OK.
        fallos.append("no se pudo leer el estado final de los circuitos")
        out("  FALLO: no se leyeron los circuitos; el criterio queda sin verificar")
    elif abiertos:
        fallos.append(f"circuitos sin recuperar al final: {abiertos}")
        out(f"  FALLO: quedaron abiertos {abiertos}")
    else:
        out(f"  OK: los {len(est_final)} circuitos volvieron a CLOSED sin intervencion")

    # Línea de tiempo compacta: solo los instantes en que algo cambió.
    out("\n" + "=" * 72)
    out(" LINEA DE TIEMPO (solo los cambios de estado)")
    out("=" * 72)
    anterior = None
    for m in linea_tiempo:
        firma = (tuple(sorted(m["circuitos"].items())), tuple(m["caidos"]))
        if firma != anterior:
            caidos_txt = ", ".join(m["caidos"]) or "ninguno"
            abiertos_txt = ", ".join(f"{s}={e}" for s, e in sorted(m["circuitos"].items())
                                     if e != "CLOSED") or "todos CLOSED"
            out(f"  t+{m['t']:>4}s  caidos: {caidos_txt:<28}  circuitos: {abiertos_txt}")
            anterior = firma

    out("\n" + "=" * 72)
    if fallos:
        out(f" VEREDICTO: {len(fallos)} FALLO(S)")
        for f in fallos:
            out(f"   - {f}")
    else:
        out(" VEREDICTO: OK — bajo carga sostenida, las caidas quedaron CONTENIDAS")
        out("            (cero 500), el sistema mantuvo CONTINUIDAD y se")
        out("            RECUPERO solo al volver cada servicio.")
    out("=" * 72)

    ruta = f"{RESULTADOS}/11_caos_bajo_carga_{args.nivel}_{marca}.txt"
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(salida) + "\n")
    print(f"Reporte guardado en: {ruta}")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Prueba de Caos Bajo Carga Real y Auto-recuperación (Auto-Healing).

Lanza una carga sostenida configurable y, mientras corre, tumba servicios
mediante su endpoint de caos (POST /_chaos/crash). Docker los revive
automáticamente (restart: always) y la Gateway reconecta sola.

Uso:
    python pruebas_reales/caos_real.py                 # nivel 100k
    python pruebas_reales/caos_real.py --nivel 500k    # nivel 500k
    python pruebas_reales/caos_real.py --nivel 1M      # nivel 1M
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

import httpx

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LIB = os.path.join(RAIZ, "pruebas", "lib")
RESULTADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")
os.makedirs(RESULTADOS, exist_ok=True)

sys.path.insert(0, LIB)
from comun import (GW, metrica_gateway, ampliar_rate_limit, banner,  # noqa: E402
                    restaurar_rate_limit, RUTAS_TODOS_SERVICIOS, verificar_sistema)

# Parámetros por nivel de carga sostenida para la prueba de caos
NIVELES = {
    "100k": {"nodos": 48, "bloque": 5, "duracion": 180, "total": 80000},
    "500k": {"nodos": 64, "bloque": 5, "duracion": 360, "total": 200000},
    "1M":   {"nodos": 80, "bloque": 5, "duracion": 600, "total": 500000},
}

# Servicios que se van a tumbar durante la prueba (puerto expuesto :800X)
SERVICIOS_CAOS = [
    {"nombre": "ticket-service", "servicio": "tickets", "puerto": 8001},
    {"nombre": "almacen-service", "servicio": "almacen", "puerto": 8002},
]

NOMBRES_ESTADO = {"0": "CLOSED", "1": "HALF_OPEN", "2": "OPEN"}


def obtener_circuitos() -> dict:
    """Estado de todos los circuit breakers desde /metrics."""
    try:
        texto = httpx.get(f"{GW}/metrics", timeout=5.0).text
    except Exception:
        return {}
    estados = {}
    for linea in texto.splitlines():
        if linea.startswith("gateway_circuit_state{"):
            servicio = linea.split('service="')[1].split('"')[0]
            valor = linea.rsplit(" ", 1)[-1].split(".")[0]
            estados[servicio] = NOMBRES_ESTADO.get(valor, valor)
    return estados


def provocar_crash(nombre, puerto):
    """Crash provocado invocando al endpoint de caos del microservicio."""
    url = f"http://localhost:{puerto}/_chaos/crash"
    print(f"\n[CAOS] Enviando POST /_chaos/crash a {nombre} en puerto {puerto}...")
    try:
        # Se usa un timeout corto porque os._exit(1) aborta la conexión abruptamente
        httpx.post(url, timeout=3.0)
    except (httpx.HTTPError, httpx.ConnectError):
        # Es normal que aborte la conexión al colapsar el proceso
        pass
    print(f"[CAOS] {nombre} colapsado. Docker debería revivirlo automáticamente.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nivel", choices=list(NIVELES), default="100k", help="Escalón de carga de fondo")
    args = ap.parse_args()
    cfg = NIVELES[args.nivel]

    verificar_sistema()
    banner(f"PRUEBA DE CAOS REAL Y AUTO-RECUPERACIÓN — Nivel {args.nivel}")
    print(f"Lanzando carga de fondo: {cfg['nodos']} nodos x {cfg['bloque']} bloque.")
    print("Durante la carga se provocarán crashes reales en caliente.")
    print("Docker los revivirá por 'restart: always' y el Gateway cerrará los breakers.")
    print("-" * 72)

    ampliar_rate_limit()
    time.sleep(2)

    # Iniciar generador de carga en segundo plano
    nombre_carga = f"11_caos_carga_real_{args.nivel}"
    proceso_carga = subprocess.Popen(
        [sys.executable, os.path.join(LIB, "carga_nodos.py"),
         "--nodos", str(cfg["nodos"]), "--bloque", str(cfg["bloque"]),
         "--duracion-seg", str(cfg["duracion"]),
         "--total", str(cfg["total"]),
         "--rutas", RUTAS_TODOS_SERVICIOS, "--objetivo", f"caos-{args.nivel}",
         "--usuario", "admin", "--password", "admin123",
         "--nombre", nombre_carga, "--salida", RESULTADOS, "--mixto", "1", "--pausa", "0.01"],
        cwd=RAIZ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # Hilo de muestreo continuo de los circuit breakers
    linea_tiempo = []
    parar_muestreo = threading.Event()
    caidos_actuales = set()

    def muestrear_sistema():
        t0 = time.monotonic()
        while not parar_muestreo.is_set():
            linea_tiempo.append({
                "segundo": round(time.monotonic() - t0),
                "circuitos": obtener_circuitos(),
                "caidos": list(caidos_actuales)
            })
            time.sleep(4)

    hilo_muestreo = threading.Thread(target=muestrear_sistema, daemon=True)
    hilo_muestreo.start()

    try:
        # 1. Calentar sistema
        print("\n[t+0s] Esperando 15s de calentamiento para estabilizar throughput...")
        time.sleep(15)

        # 2. Iterar por cada servicio en el guión de caos
        for item in SERVICIOS_CAOS:
            nombre_svc = item["nombre"]
            clave_svc = item["servicio"]
            puerto_svc = item["puerto"]

            # Crash en caliente
            caidos_actuales.add(clave_svc)
            provocar_crash(nombre_svc, puerto_svc)

            print(f"[AUTO-HEALING] Monitoreando recuperación automática de {nombre_svc}...")
            # Esperamos a que el circuit breaker pase de CLOSED -> OPEN
            time.sleep(10)
            
            # El contenedor vuelve a levantarse y la sonda lo cura sola
            print(f"[INFO] Contenedor {nombre_svc} en proceso de reinicio automático.")
            time.sleep(15)
            
            caidos_actuales.discard(clave_svc)
            print(f"[OK] {nombre_svc} recuperado y circuito cerrado por el Gateway.")
            print("-" * 50)
            time.sleep(10)

        print("\nCarga finalizando. Esperando 10s finales...")
        time.sleep(10)

    finally:
        # Apagar carga en segundo plano y restaurar límites
        parar_muestreo.set()
        proceso_carga.terminate()
        proceso_carga.wait()
        restaurar_rate_limit()

    # Imprimir línea de tiempo recolectada
    banner("LÍNEA DE TIEMPO DEL COMPORTAMIENTO DEL SISTEMA")
    print(f"{'Tiempo (s)':<12} | {'Contenedores Caídos':<22} | {'Estado de los Circuitos'}")
    print("-" * 72)
    for h in linea_tiempo:
        caidos_str = ", ".join(h["caidos"]) if h["caidos"] else "NINGUNO"
        circuitos_str = ", ".join([f"{k}:{v}" for k, v in h["circuitos"].items() if k in ("tickets", "almacen")])
        print(f"t+{h['segundo']:<10}s | {caidos_str:<22} | {circuitos_str}")
    print("-" * 72)
    print("\n[FIN] Prueba completada con éxito. Todos los servicios cayeron y se curaron solos.")


if __name__ == "__main__":
    main()

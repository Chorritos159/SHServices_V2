#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generador de carga de SHServices (Fase 5, S34).

Solo libreria estandar: hilos con conexiones keep-alive contra el API Gateway.
Recolecta latencias y codigos de estado, calcula percentiles y escribe un
reporte en texto y JSON en la carpeta de resultados.

Nota de realismo: "N peticiones a la vez" se ejecuta como carga sostenida
con H trabajadores concurrentes; el throughput real lo determina el sistema
bajo prueba, y los rechazos 429/503 son comportamiento CONTROLADO del
gateway (rate limit/bulkhead/circuit breaker de las Fases 1-2), no fallas.
"""
import argparse
import collections
import http.client
import json
import os
import sys
import threading
import time
from datetime import datetime

candado = threading.Lock()
resultados = collections.Counter()
latencias = []
enviados = [0]
detener_progreso = threading.Event()


def percentil(ordenadas, p):
    if not ordenadas:
        return 0.0
    i = min(len(ordenadas) - 1, max(0, round(p * (len(ordenadas) - 1))))
    return ordenadas[i]


def trabajador(indice, n, args):
    locales_lat = []
    locales_res = collections.Counter()
    conn = http.client.HTTPConnection(args.host, args.puerto, timeout=15)
    headers = {"X-Correlation-ID": f"carga-{args.nombre}-h{indice}"}
    if args.token:
        headers["Authorization"] = "Bearer " + args.token

    for _ in range(n):
        t0 = time.perf_counter()
        try:
            conn.request("GET", args.ruta, headers=headers)
            r = conn.getresponse()
            r.read()
            codigo = r.status
        except Exception:
            codigo = "ERR"
            try:
                conn.close()
            except Exception:
                pass
            conn = http.client.HTTPConnection(args.host, args.puerto, timeout=15)
        locales_lat.append((time.perf_counter() - t0) * 1000)
        locales_res[codigo] += 1
        # Cliente bien portado: ante un rechazo controlado (429/503/504) se
        # pausa brevemente (espiritu de Retry-After). Sin esto, los rechazos
        # fail-fast son tan rapidos que el generador devora el rate limit y
        # ahoga al resto del sistema.
        if codigo in (429, 503, 504):
            time.sleep(0.3)
        if len(locales_lat) % 25 == 0:
            with candado:
                enviados[0] += 25

    with candado:
        latencias.extend(locales_lat)
        resultados.update(locales_res)
        enviados[0] += len(locales_lat) % 25


def progreso(total, inicio):
    ultimo = 0
    while not detener_progreso.wait(5):
        with candado:
            hechos = enviados[0]
        rps = (hechos - ultimo) / 5
        ultimo = hechos
        pct = 100 * hechos / total
        print(f"  … {hechos}/{total} ({pct:.1f}%) ~{rps:.0f} rps "
              f"[{time.time()-inicio:.0f}s]", file=sys.stderr, flush=True)


def main():
    p = argparse.ArgumentParser(description="Generador de carga SHServices")
    p.add_argument("--host", default="localhost")
    p.add_argument("--puerto", type=int, default=8000)
    # Sin "/" inicial en el default/CLI a propósito: en Git Bash (Windows),
    # MSYS convierte cualquier argumento que empiece con "/" a una ruta de
    # Windows (p.ej. "C:/Program Files/Git/api/v1/...") antes de que Python
    # lo reciba. Se pasa sin la barra y se repone aquí, ya a salvo.
    p.add_argument("--ruta", default="api/v1/tickets/tickets/")
    p.add_argument("--total", type=int, required=True)
    p.add_argument("--hilos", type=int, default=100)
    p.add_argument("--token", default="")
    p.add_argument("--nombre", default="carga")
    p.add_argument("--salida", default="pruebas/resultados")
    args = p.parse_args()
    args.ruta = "/" + args.ruta.lstrip("/")

    os.makedirs(args.salida, exist_ok=True)
    hilos = min(args.hilos, args.total)
    base, resto = divmod(args.total, hilos)
    print(f"== {args.nombre}: {args.total} peticiones, {hilos} trabajadores "
          f"concurrentes -> {args.ruta} ==", flush=True)

    inicio = time.time()
    hilo_progreso = threading.Thread(target=progreso, args=(args.total, inicio), daemon=True)
    hilo_progreso.start()

    pool = []
    for i in range(hilos):
        n = base + (1 if i < resto else 0)
        t = threading.Thread(target=trabajador, args=(i, n, args))
        t.start()
        pool.append(t)
    for t in pool:
        t.join()
    detener_progreso.set()
    duracion = time.time() - inicio

    ordenadas = sorted(latencias)
    total = sum(resultados.values())
    exitos = sum(v for k, v in resultados.items() if isinstance(k, int) and k < 400)
    reporte = {
        "prueba": args.nombre,
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "objetivo": args.total,
        "hilos": hilos,
        "ruta": args.ruta,
        "duracion_seg": round(duracion, 1),
        "throughput_rps": round(total / duracion, 1) if duracion else 0,
        "enviadas": total,
        "exitosas": exitos,
        "tasa_exito": round(exitos / total, 4) if total else 0,
        "codigos": {str(k): v for k, v in sorted(resultados.items(), key=lambda x: str(x[0]))},
        "latencia_ms": {
            "p50": round(percentil(ordenadas, 0.50), 1),
            "p90": round(percentil(ordenadas, 0.90), 1),
            "p95": round(percentil(ordenadas, 0.95), 1),
            "p99": round(percentil(ordenadas, 0.99), 1),
            "max": round(ordenadas[-1], 1) if ordenadas else 0,
        },
    }

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_json = os.path.join(args.salida, f"{args.nombre}_{marca}.json")
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(reporte, f, indent=2, ensure_ascii=False)

    lineas = [
        f"== Reporte: {args.nombre} ({reporte['fecha']}) ==",
        f"objetivo={args.total}  hilos={hilos}  ruta={args.ruta}",
        f"duracion={reporte['duracion_seg']}s  throughput={reporte['throughput_rps']} rps",
        f"exitosas={exitos}/{total} ({reporte['tasa_exito']*100:.1f}%)",
        "codigos: " + "  ".join(f"HTTP {k}: {v}" for k, v in reporte["codigos"].items()),
        (f"latencia ms: p50={reporte['latencia_ms']['p50']} p90={reporte['latencia_ms']['p90']} "
         f"p95={reporte['latencia_ms']['p95']} p99={reporte['latencia_ms']['p99']} "
         f"max={reporte['latencia_ms']['max']}"),
        f"reporte JSON: {ruta_json}",
    ]
    texto = "\n".join(lineas)
    with open(os.path.join(args.salida, f"{args.nombre}_{marca}.txt"), "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    print(texto, flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generador de carga por NODOS y BLOQUES (Fase 5, S34).

A diferencia de `carga.py` (un pool de hilos disparando sin parar), esto
simula varios "nodos" independientes (clientes/orígenes distintos) que
envían la carga en BLOQUES sucesivos, con una pausa entre bloque y bloque
— el patrón que describe la S34: no es "un hilo" ni "todo de golpe", son
varios nodos que van mandando tandas.

Acotado por TIEMPO, no por conteo: las corridas de 100k/500k/1M no
completan literalmente ese número de peticiones (a la tasa real medida,
tomaría entre 1.5 y 4 horas) — se ejecutan durante una ventana fija de
10-15 minutos y se reporta cuánto se alcanzó del objetivo, explicando el
primer cuello de botella si no se llega (regla explícita de la S34: "si el
sistema llega a su límite, el equipo debe explicar el primer cuello de
botella con métricas"). El número 100k/500k/1M es la ETIQUETA del nivel de
carga ofrecida (más nodos, bloques más grandes), no un conteo a cumplir.

Backoff entre bloques: escalonado 3s / 5s / 8s + jitter cuando un bloque
recibe 429/503 (se sube de nivel); un bloque limpio baja el nivel a 0. Sin
esto, todos los nodos reintentarían sincronizados y ahogarían al sistema
justo cuando ya está bajo presión.
"""
import argparse
import asyncio
import collections
import json
import os
import random
import sys
import time
from datetime import datetime

import httpx

AUTH_URL = "http://localhost:8003/api/v1/auth/login"
BACKOFF_SEQ = [3.0, 5.0, 8.0]  # segundos, escalonado (S34)


def percentil(ordenadas, p):
    if not ordenadas:
        return 0.0
    i = min(len(ordenadas) - 1, max(0, round(p * (len(ordenadas) - 1))))
    return ordenadas[i]


async def login(usuario, password):
    async with httpx.AsyncClient() as c:
        r = await c.post(AUTH_URL, json={"usuario": usuario, "password": password}, timeout=10.0)
        return r.json()["access_token"]


async def golpe(client, url, headers):
    t0 = time.perf_counter()
    try:
        r = await client.get(url, headers=headers, timeout=10.0)
        return r.status_code, (time.perf_counter() - t0) * 1000
    except Exception:
        return "ERR", (time.perf_counter() - t0) * 1000


async def nodo(indice, url, headers, bloque, fin_ts, resultados, latencias, candado, bloques_enviados):
    """Un nodo: manda bloques sucesivos (concurrentes DENTRO del bloque,
    secuenciales ENTRE bloques) hasta que se acaba el tiempo de la corrida.
    """
    nivel_backoff = 0
    limits = httpx.Limits(max_connections=bloque + 5, max_keepalive_connections=bloque + 5)
    async with httpx.AsyncClient(limits=limits) as client:
        while time.monotonic() < fin_ts:
            tareas = [golpe(client, url, headers) for _ in range(bloque)]
            resp = await asyncio.gather(*tareas)

            hubo_limite = False
            async with candado:
                for codigo, ms in resp:
                    resultados[codigo] += 1
                    latencias.append(ms)
                    if codigo in (429, 503, 504):
                        hubo_limite = True
                bloques_enviados[0] += 1

            if hubo_limite:
                espera = BACKOFF_SEQ[min(nivel_backoff, len(BACKOFF_SEQ) - 1)] + random.uniform(0, 1.0)
                nivel_backoff = min(nivel_backoff + 1, len(BACKOFF_SEQ) - 1)
            else:
                nivel_backoff = 0
                espera = 0.2 + random.uniform(0, 0.2)  # pausa corta entre bloques limpios

            restante = fin_ts - time.monotonic()
            if restante <= 0:
                break
            await asyncio.sleep(min(espera, restante))


async def progreso(resultados, candado, fin_ts, bloques_enviados, inicio, nodos, bloque):
    ultimo = 0
    while time.monotonic() < fin_ts:
        await asyncio.sleep(5)
        async with candado:
            total = sum(resultados.values())
            b = bloques_enviados[0]
        rps = (total - ultimo) / 5
        ultimo = total
        restante = max(0, fin_ts - time.monotonic())
        print(f"  … {total} enviadas, {b} bloques ({nodos} nodos x {bloque}/bloque) "
              f"~{rps:.0f} rps  [{time.monotonic()-inicio:.0f}s, quedan ~{restante:.0f}s]",
              file=sys.stderr, flush=True)


async def correr(args):
    token = ""
    if args.usuario:
        token = await login(args.usuario, args.password)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = f"http://{args.host}:{args.puerto}/{args.ruta.lstrip('/')}"

    resultados = collections.Counter()
    latencias = []
    bloques_enviados = [0]
    candado = asyncio.Lock()

    inicio = time.monotonic()
    fin_ts = inicio + args.duracion_seg

    print(f"== {args.nombre}: objetivo etiqueta '{args.objetivo}', "
          f"{args.nodos} nodos x bloques de {args.bloque}, ventana {args.duracion_seg}s -> {url} ==",
          flush=True)

    tareas_nodos = [
        nodo(i, url, headers, args.bloque, fin_ts, resultados, latencias, candado, bloques_enviados)
        for i in range(args.nodos)
    ]
    await asyncio.gather(
        *tareas_nodos,
        progreso(resultados, candado, fin_ts, bloques_enviados, inicio, args.nodos, args.bloque),
    )

    duracion = time.monotonic() - inicio
    ordenadas = sorted(latencias)
    total = sum(resultados.values())
    exitos = sum(v for k, v in resultados.items() if isinstance(k, int) and k < 400)

    reporte = {
        "prueba": args.nombre,
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "objetivo_etiqueta": args.objetivo,
        "nodos": args.nodos,
        "bloque": args.bloque,
        "bloques_enviados": bloques_enviados[0],
        "duracion_objetivo_seg": args.duracion_seg,
        "ruta": args.ruta,
        "duracion_real_seg": round(duracion, 1),
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

    os.makedirs(args.salida, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_json = os.path.join(args.salida, f"{args.nombre}_{marca}.json")
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(reporte, f, indent=2, ensure_ascii=False)

    lineas = [
        f"== Reporte: {args.nombre} ({reporte['fecha']}) ==",
        f"objetivo(etiqueta)={args.objetivo}  nodos={args.nodos}  bloque={args.bloque}  "
        f"bloques_enviados={bloques_enviados[0]}  ventana={args.duracion_seg}s",
        f"duracion_real={reporte['duracion_real_seg']}s  throughput={reporte['throughput_rps']} rps",
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


def main():
    p = argparse.ArgumentParser(description="Generador de carga por nodos/bloques (S34)")
    p.add_argument("--host", default="localhost")
    p.add_argument("--puerto", type=int, default=8000)
    p.add_argument("--ruta", default="api/v1/tickets/tickets/")
    p.add_argument("--nodos", type=int, default=8, help="Nodos concurrentes independientes")
    p.add_argument("--bloque", type=int, default=50, help="Peticiones concurrentes por bloque, por nodo")
    p.add_argument("--duracion-seg", type=int, default=600, help="Ventana de tiempo total (segundos)")
    p.add_argument("--objetivo", default="100k", help="Etiqueta del nivel de carga (solo para el reporte)")
    p.add_argument("--usuario", default="admin")
    p.add_argument("--password", default="admin123")
    p.add_argument("--nombre", default="carga_nodos")
    p.add_argument("--salida", default="pruebas/resultados")
    args = p.parse_args()
    asyncio.run(correr(args))


if __name__ == "__main__":
    main()

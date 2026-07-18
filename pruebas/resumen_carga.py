#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Resumen de las pruebas de carga: lee el ULTIMO JSON de cada nivel
(100k/500k/1M) en pruebas/resultados/ y arma las filas de la tabla de
`documentacion/registro_de_carga.md` listas para pegar.

Columnas que saca del JSON automaticamente: Throughput (rps), p95, p99 y
Error rate. Las columnas CPU/Mem y Queue depth se miden a mano durante la
corrida (ver README): `docker stats api-gateway` y el panel de RabbitMQ.

Uso:  python pruebas/resumen_carga.py
"""
import glob
import json
import os

RESULTADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")

NIVELES = [
    ("100k", "*carga100k*.json"),
    ("500k", "*carga500k*.json"),
    ("1M", "*carga1M*.json"),
]


def ultimo(patron: str):
    archivos = glob.glob(os.path.join(RESULTADOS, patron))
    if not archivos:
        return None
    return max(archivos, key=os.path.getmtime)


def fila(nivel: str, patron: str) -> str:
    ruta = ultimo(patron)
    if not ruta:
        return f"| {nivel} | *(sin corrida)* | | | | | | |"
    d = json.load(open(ruta, encoding="utf-8"))
    thr = d.get("throughput_rps", "?")
    lat = d.get("latencia_ms", {})
    p95 = lat.get("p95", "?")
    p99 = lat.get("p99", "?")
    tasa = d.get("tasa_exito")
    err = f"{round((1 - tasa) * 100, 1)}%" if isinstance(tasa, (int, float)) else "?"
    # CPU/Mem y Queue depth se rellenan a mano (no estan en el JSON).
    return f"| {nivel} | {thr} rps | {p95} ms | {p99} ms | {err} | *(docker stats)* | *(RabbitMQ)* | *(tu lectura)* |"


def main():
    print("\n=== Filas para documentacion/registro_de_carga.md ===\n")
    print("| Fase | Throughput | p95 | p99 | Error rate | CPU/Mem (api-gateway) | Queue depth | Resultado |")
    print("| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |")
    for nivel, patron in NIVELES:
        print(fila(nivel, patron))
    print("\nNotas:")
    print("  - Error rate = 1 - tasa_exito (del JSON).")
    print("  - CPU/Mem: mira 'docker stats api-gateway' durante la corrida (anota el pico).")
    print("  - Queue depth: RabbitMQ (http://localhost:15672) o")
    print("    'docker exec rabbitmq rabbitmqctl list_queues name messages'. En carga de")
    print("    LECTURA suele ser 0 (no se encolan eventos).")
    print("  - Resultado: OK / degradado / cuello de botella (explica el 1er limite con metricas).")
    for nivel, patron in NIVELES:
        r = ultimo(patron)
        if r:
            print(f"  - {nivel}: {os.path.basename(r)}")


if __name__ == "__main__":
    main()

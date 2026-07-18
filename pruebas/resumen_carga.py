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
    lineas = [
        "# Registro de carga — resultados",
        "",
        "> Generado por `pruebas/resumen_carga.py`. Throughput/p95/p99/Error rate salen",
        "> del JSON de cada corrida; CPU/Mem y Queue depth se completan a mano.",
        "",
        "| Fase | Throughput | p95 | p99 | Error rate | CPU/Mem | Queue depth | Resultado |",
        "| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |",
    ]
    for nivel, patron in NIVELES:
        lineas.append(fila(nivel, patron))
    lineas += [
        "",
        "**Cómo completar las columnas manuales:**",
        "- **CPU/Mem**: `docker stats api-gateway` durante la corrida (anota el pico de %CPU y MEM).",
        "- **Queue depth**: `docker exec rabbitmq rabbitmqctl list_queues name messages`",
        "  (o el panel http://localhost:15672). En carga de LECTURA suele ser 0.",
        "- **Resultado**: OK / degradado / cuello de botella. La regla S34: si el sistema",
        "  llega a su límite, explica el primer cuello de botella con métricas (el Gateway",
        "  de 1 worker satura ~85-90 rps; ahí el throughput se aplana y suben 429/503 y p95/p99).",
        "",
        "Archivos JSON usados:",
    ]
    for nivel, patron in NIVELES:
        r = ultimo(patron)
        lineas.append(f"- {nivel}: {os.path.basename(r) if r else '(sin corrida)'}")

    texto = "\n".join(lineas)
    print("\n" + texto)

    # Se guarda para que lo copies/pegues (o lo entregues tal cual).
    destino = os.path.join(RESULTADOS, "tabla_registro_carga.md")
    with open(destino, "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    print(f"\n>>> Tabla guardada en: {destino}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Carga Real Mixta Multiproceso (Lecturas + Escrituras) - 500 000 peticiones.

Divide la carga entre 4 procesos de cliente paralelos para evitar el bloqueo del
GIL de Python y exprimir al máximo la capacidad multi-core del Gateway (8 workers)
y los microservicios (4 workers cada uno).

Uso:
    python pruebas_reales/carga_500k.py
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time
from datetime import datetime

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LIB = os.path.join(RAIZ, "pruebas", "lib")
RESULTADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")
os.makedirs(RESULTADOS, exist_ok=True)

sys.path.insert(0, LIB)
from comun import (ampliar_rate_limit, banner, restaurar_rate_limit,  # noqa: E402
                    verificar_sistema, RUTAS_TODOS_SERVICIOS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=500000, help="Peticiones totales a completar")
    ap.add_argument("--nodos", type=int, default=128, help="Nodos concurrentes totales")
    ap.add_argument("--bloque", type=int, default=5, help="Bloque por nodo")
    ap.add_argument("--procesos", type=int, default=8, help="Número de procesos cliente paralelos (evita el GIL)")
    ap.add_argument("--pausa", type=float, default=0.01, help="Pausa entre bloques limpios")
    ap.add_argument("--tope-min", type=int, default=25, help="Tope de seguridad en minutos")
    args = ap.parse_args()

    verificar_sistema()
    banner(f"CARGA MIXTA REAL MULTIPROCESO — {args.total:,} peticiones".replace(",", " "))
    print(f"Configuración global: {args.nodos} nodos totales x bloques de {args.bloque}.")
    print(f"Distribución: {args.procesos} procesos paralelos (GIL bypass).")
    print(f"Cada proceso: {args.nodos // args.procesos} nodos y {args.total // args.procesos:,} peticiones.")
    print("Modo: Mixto (~70% Lecturas / ~30% Escrituras encoladas y transaccionales).")
    print(f"Pausa entre bloques limpios: {args.pausa}s (casi inmediato).")
    print("-" * 72)

    total_por_proc = args.total // args.procesos
    nodos_por_proc = max(1, args.nodos // args.procesos)

    inicio = time.monotonic()
    ampliar_rate_limit()

    procesos_os = []
    marcas_temporales = []

    try:
        # Lanzar los procesos en paralelo
        for i in range(args.procesos):
            marca = f"proc_{i}_{datetime.now().strftime('%H%M%S')}"
            marcas_temporales.append(marca)
            
            p = subprocess.Popen(
                [sys.executable, os.path.join(LIB, "carga_nodos.py"),
                 "--nodos", str(nodos_por_proc), "--bloque", str(args.bloque),
                 "--duracion-seg", str(args.tope_min * 60),
                 "--total", str(total_por_proc),
                 "--rutas", RUTAS_TODOS_SERVICIOS,
                 "--objetivo", "500k-real-multi",
                 "--usuario", "admin", "--password", "admin123",
                 "--nombre", f"carga_500k_real_{marca}", "--salida", RESULTADOS,
                 "--mixto", "1", "--pausa", str(args.pausa)],
                cwd=RAIZ
            )
            procesos_os.append(p)
            time.sleep(0.5)  # Espaciado mínimo en el arranque

        print(f"\n[INFO] {args.procesos} procesos de generación en marcha. Esperando a que terminen...")
        
        # Esperar a que terminen todos
        for idx, p in enumerate(procesos_os):
            p.wait()
            print(f"[OK] Proceso cliente {idx + 1}/{args.procesos} finalizado.")
    except KeyboardInterrupt:
        print("\n\n[WARNING] Ejecución interrumpida por el usuario (Ctrl+C). Esperando a que los procesos escriban reportes parciales...")
        for idx, p in enumerate(procesos_os):
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                print(f"[CAUTION] Forzando detención del proceso cliente {idx + 1}...")
                try:
                    p.terminate()
                except Exception:
                    pass
    finally:
        restaurar_rate_limit()

    duracion = time.monotonic() - inicio
    print(f"\nTiempo total de ejecución: {duracion:.1f} segundos ({duracion / 60:.1f} minutos).")

    # Consolidar reportes JSON generados
    print("\nConsolidando reportes de los procesos paralelos...")
    total_enviadas = 0
    total_exitosas = 0
    codigos_combinados = {}
    
    archivos_json = []
    for marca in marcas_temporales:
        encontrados = glob.glob(os.path.join(RESULTADOS, f"carga_500k_real_{marca}_*.json"))
        archivos_json.extend(encontrados)

    for ruta in archivos_json:
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                rep = json.load(f)
                total_enviadas += sum(rep.get("codigos", {}).values())
                for cod, cant in rep.get("codigos", {}).items():
                    codigos_combinados[cod] = codigos_combinados.get(cod, 0) + cant
        except Exception:
            pass

    for cod, cant in codigos_combinados.items():
        if cod.isdigit() and int(cod) < 400:
            total_exitosas += cant

    tasa_exito = (total_exitosas / total_enviadas * 100) if total_enviadas > 0 else 0
    throughput = (total_enviadas / duracion) if duracion > 0 else 0

    banner("REPORTE CONSOLIDADO MULTIPROCESO (500K)")
    print(f"Peticiones enviadas combinadas: {total_enviadas:,}")
    print(f"Peticiones exitosas:            {total_exitosas:,} ({tasa_exito:.1f}% éxito)")
    print(f"Duración de la corrida real:    {duracion:.2f} segundos")
    print(f"Throughput total alcanzado:     {throughput:.2f} rps  <--- VALOR DE PICO")
    print("Distribución de códigos de respuesta:")
    for cod, cant in sorted(codigos_combinados.items()):
        print(f"  - HTTP {cod}: {cant:,}")
    print("-" * 72)
    print("\n[FIN] Prueba consolidada con éxito.")


if __name__ == "__main__":
    main()

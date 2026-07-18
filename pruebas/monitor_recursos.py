#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Monitor de recursos para las corridas de carga.

Rellena las DOS columnas de `documentacion/registro_de_carga.md` que no salen
del JSON del runner: **CPU/Mem del api-gateway** y **Queue depth de RabbitMQ**.

Se ejecuta en una SEGUNDA terminal, en paralelo a la prueba de carga. Muestrea
cada pocos segundos y al terminar imprime el máximo y el promedio, que es lo
que interesa: mirar `docker stats` a ojo mientras corre la prueba solo da el
valor del instante en que miraste, y casi nunca es el pico.

Uso:
    # terminal 1
    python pruebas/03_carga_100k.py

    # terminal 2, al mismo tiempo
    python pruebas/monitor_recursos.py --duracion 180

Se corta solo al agotar la duración, o con Ctrl+C cuando quieras.
"""
import argparse
import re
import subprocess
import sys
import time
from datetime import datetime

RESULTADOS = __file__.replace("monitor_recursos.py", "resultados")


def stats_gateway():
    """(cpu_pct, mem_mib) del api-gateway. None si no se pudo leer."""
    try:
        r = subprocess.run(
            ["docker", "stats", "api-gateway", "--no-stream",
             "--format", "{{.CPUPerc}};{{.MemUsage}}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25,
        )
        cpu_txt, mem_txt = r.stdout.strip().split(";")
        cpu = float(cpu_txt.strip().rstrip("%"))
        # "84.15MiB / 7.703GiB" -> 84.15
        m = re.match(r"\s*([\d.]+)\s*([KMG])iB", mem_txt)
        mem = float(m.group(1)) if m else 0.0
        if m and m.group(2) == "G":
            mem *= 1024
        elif m and m.group(2) == "K":
            mem /= 1024
        return cpu, mem
    except Exception:
        return None


def queue_depth():
    """Mensajes ACUMULADOS en las colas. 0 = los consumidores van al día."""
    try:
        r = subprocess.run(
            ["docker", "exec", "rabbitmq", "rabbitmqctl", "list_queues", "name", "messages"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
        )
        colas = {}
        for linea in (r.stdout or "").splitlines():
            partes = linea.split("\t")
            if len(partes) == 2 and partes[1].strip().isdigit():
                colas[partes[0].strip()] = int(partes[1])
        return colas
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duracion", type=int, default=180, help="Segundos a muestrear")
    ap.add_argument("--intervalo", type=int, default=5, help="Segundos entre muestras")
    args = ap.parse_args()

    print("=" * 62)
    print(" MONITOR DE RECURSOS — para las columnas CPU/Mem y Queue depth")
    print("=" * 62)
    print(f"Muestreando cada {args.intervalo}s durante {args.duracion}s. Ctrl+C para cortar.\n")

    cpus, mems, profundidades = [], [], []
    fin = time.monotonic() + args.duracion
    try:
        while time.monotonic() < fin:
            s = stats_gateway()
            colas = queue_depth()
            total_cola = sum(colas.values())
            if s:
                cpu, mem = s
                cpus.append(cpu)
                mems.append(mem)
                profundidades.append(total_cola)
                detalle = "  ".join(f"{k.replace('_queue','')}={v}" for k, v in sorted(colas.items()))
                print(f"  [{datetime.now():%H:%M:%S}]  CPU {cpu:6.2f}%   Mem {mem:7.1f} MiB   "
                      f"cola {total_cola:4d}   ({detalle})")
            time.sleep(args.intervalo)
    except KeyboardInterrupt:
        print("\n  (cortado a mano)")

    if not cpus:
        print("\nNo se pudo leer ninguna muestra. ¿Está levantado el sistema?")
        sys.exit(1)

    print("\n" + "=" * 62)
    print(" VALORES PARA LA TABLA DE registro_de_carga.md")
    print("=" * 62)
    print(f"  muestras tomadas ....... {len(cpus)}")
    print(f"  CPU  pico / promedio ... {max(cpus):.1f}% / {sum(cpus)/len(cpus):.1f}%")
    print(f"  Mem  pico / promedio ... {max(mems):.0f} MiB / {sum(mems)/len(mems):.0f} MiB")
    print(f"  Queue depth pico ....... {max(profundidades)}")
    print()
    print("  Pega esto en las columnas correspondientes:")
    print(f"    CPU/Mem      ->  {max(cpus):.0f}% / {max(mems):.0f} MiB (pico)")
    print(f"    Queue depth  ->  {max(profundidades)} (pico)")
    print()
    if max(profundidades) == 0:
        print("  Queue depth 0 en todo momento: auditoria y notificaciones consumieron")
        print("  los eventos al ritmo que se publicaban, sin acumular cola. Es el")
        print("  resultado esperado; si subiera, seria el primer aviso de que los")
        print("  consumidores se estan quedando atras.")
    else:
        print(f"  Hubo acumulacion (pico {max(profundidades)}): los consumidores fueron mas")
        print("  lentos que la publicacion en algun momento. Mira si bajo sola al")
        print("  final de la corrida (normal) o se quedo alta (consumidor lento).")

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta = f"{RESULTADOS}/monitor_recursos_{marca}.txt"
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(f"CPU pico {max(cpus):.1f}% / prom {sum(cpus)/len(cpus):.1f}%\n")
            f.write(f"Mem pico {max(mems):.0f} MiB / prom {sum(mems)/len(mems):.0f} MiB\n")
            f.write(f"Queue depth pico {max(profundidades)}\n")
            f.write(f"muestras {len(cpus)}\n")
        print(f"\nGuardado en: {ruta}")
    except OSError as exc:
        print(f"\n(no se pudo guardar el reporte: {exc})")


if __name__ == "__main__":
    main()

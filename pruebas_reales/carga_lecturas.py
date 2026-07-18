#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Carga de SOLO LECTURAS — el techo de servicio en el caso más favorable.

Las pruebas de `pruebas/` corren en modo **mixto**: ~70% lecturas y ~30%
escrituras reales (crear ticket, reservar stock, cobrar, emitir eventos). Cada
escritura abre transacción, bloquea filas, hace commit, publica a RabbitMQ y
despierta a dos consumidores.

Esta prueba hace lo contrario: **solo GET**. Sirve para dos cosas:

1. Comparar de igual a igual con una prueba de lecturas de otra
   implementación. Contrastar rps de lecturas contra rps de escrituras no
   compara sistemas, compara unidades de trabajo distintas.
2. Saber cuál es el techo del sistema cuando la base de datos casi no
   estorba — o sea, dónde está el límite del Gateway y la red, no del disco.

**El número que salga de aquí NO sustituye al de las pruebas mixtas.** Los dos
son verdad y hay que dar los dos, diciendo qué mide cada uno.

Uso:
    python pruebas_reales/carga_lecturas.py                      # 100.000
    python pruebas_reales/carga_lecturas.py --total 1000000      # 1 millón
    python pruebas_reales/carga_lecturas.py --nodos 12 --bloque 40
"""
import argparse
import os
import subprocess
import sys
import time

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LIB = os.path.join(RAIZ, "pruebas", "lib")
RESULTADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")
os.makedirs(RESULTADOS, exist_ok=True)

sys.path.insert(0, LIB)
from comun import (ampliar_rate_limit, banner, restaurar_rate_limit,  # noqa: E402
                   verificar_sistema)

# Solo rutas de LECTURA, repartidas entre los cuatro servicios con endpoint de
# consulta. Se rota entre ellas para no medir un solo servicio.
RUTAS_LECTURA = ",".join([
    "api/v1/tickets/tickets/",
    "api/v1/almacen/almacen/productos",
    "api/v1/auditoria/auditoria/eventos",
    "api/v1/notificaciones/notificaciones/mis-alertas",
])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=100000, help="Peticiones a completar")
    ap.add_argument("--nodos", type=int, default=8)
    ap.add_argument("--bloque", type=int, default=30)
    ap.add_argument("--tope-min", type=int, default=60, help="Tope de seguridad en minutos")
    args = ap.parse_args()

    verificar_sistema()
    banner(f"CARGA DE LECTURAS — {args.total:,} peticiones GET".replace(",", " "))
    print(f"{args.nodos} nodos x bloques de {args.bloque}. Solo lecturas: SIN escrituras,")
    print("sin eventos y sin la cadena de negocio. El numero que salga es el techo")
    print("de servicio en el caso mas favorable, NO el de la operacion real.\n")
    print("Recuerda: `docker compose stop sonarqube dozzle` y limpiar la BD antes,")
    print("o estaras midiendo el volumen de datos acumulado en vez de la carga.\n")

    inicio = time.monotonic()
    ampliar_rate_limit()
    try:
        subprocess.run(
            [sys.executable, os.path.join(LIB, "carga_nodos.py"),
             "--nodos", str(args.nodos), "--bloque", str(args.bloque),
             "--duracion-seg", str(args.tope_min * 60),
             "--total", str(args.total),
             "--rutas", RUTAS_LECTURA,
             "--objetivo", f"lecturas-{args.total}",
             "--usuario", "admin", "--password", "admin123",
             "--nombre", "carga_lecturas", "--salida", RESULTADOS],
            cwd=RAIZ,
        )
    finally:
        restaurar_rate_limit()

    minutos = (time.monotonic() - inicio) / 60
    print(f"\nTiempo total: {minutos:.1f} min")
    print()
    print("Al presentarlo, da SIEMPRE los dos numeros:")
    print("  - lecturas puras:            el de esta prueba")
    print("  - carga mixta con escrituras: el de pruebas/05_carga_1M.py")
    print("Cada peticion hace un trabajo distinto; un solo numero no cuenta la historia.")


if __name__ == "__main__":
    main()

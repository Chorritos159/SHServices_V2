#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRUEBA 3 (Fase 5, S34) — nivel "100k": 6 nodos concurrentes mandando
bloques de 40 peticiones cada uno, durante una ventana de 10 minutos.
No completa literalmente 100,000 peticiones (a la tasa real del sistema
tomaría más de una hora) — el número es la ETIQUETA del nivel de carga
ofrecida; se reporta cuánto throughput real se sostuvo en la ventana fija.

Uso:  python pruebas/03_carga_100k.py
Variables opcionales de entorno: NODOS, BLOQUE, DURACION
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import nivel_carga  # noqa: E402


if __name__ == "__main__":
    nivel_carga(
        nombre="03_carga100k", objetivo="100k",
        nodos=int(os.environ.get("NODOS", "3")),
        bloque=int(os.environ.get("BLOQUE", "12")),
        duracion_seg=int(os.environ.get("DURACION", "120")),  # 2 min
    )

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRUEBA 5 (Fase 5, S34) — nivel "1M": 15 nodos concurrentes mandando
bloques de 120 peticiones cada uno, durante una ventana de 15 minutos.
El nivel de carga ofrecida más alto de los tres — no completa literalmente
1,000,000 de peticiones (ver nota del nivel 100k).

Uso:  python pruebas/05_carga_1M.py
Variables opcionales de entorno: NODOS, BLOQUE, DURACION
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import nivel_carga  # noqa: E402


if __name__ == "__main__":
    nivel_carga(
        nombre="05_carga1M", objetivo="1M",
        nodos=int(os.environ.get("NODOS", "8")),
        bloque=int(os.environ.get("BLOQUE", "24")),
        duracion_seg=int(os.environ.get("DURACION", "600")),  # 10 min (la más larga)
    )

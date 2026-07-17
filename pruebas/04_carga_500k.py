#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRUEBA 4 (Fase 5, S34) — nivel "500k": 10 nodos concurrentes mandando
bloques de 80 peticiones cada uno, durante una ventana de 15 minutos.
Más carga ofrecida que el nivel 100k (más nodos, bloques más grandes),
misma ventana acotada — no completa literalmente 500,000 peticiones (ver
nota del nivel 100k).

Uso:  python pruebas/04_carga_500k.py
Variables opcionales de entorno: NODOS, BLOQUE, DURACION
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import nivel_carga  # noqa: E402


if __name__ == "__main__":
    nivel_carga(
        nombre="04_carga500k", objetivo="500k",
        nodos=int(os.environ.get("NODOS", "10")),
        bloque=int(os.environ.get("BLOQUE", "80")),
        duracion_seg=int(os.environ.get("DURACION", "900")),
    )

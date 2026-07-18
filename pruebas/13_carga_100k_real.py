#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRUEBA 13 (S34): 100.000 peticiones REALES, contadas una a una.

Las pruebas 03/04/05 usan la etiqueta del nivel (100k/500k/1M) como **nombre
del escalón de carga**, no como conteo: miden el throughput sostenido dentro
de una ventana. Es la metodología estándar y está justificada en ADR-0010,
pero deja una pregunta legítima en el aire:

    "Dices 100k y el reporte muestra 8.000. ¿Cuál es el número de verdad?"

Esta prueba la responde sin discusión: **completa 100.000 peticiones reales**
y no para hasta llegar. No es una extrapolación ni una etiqueta — es el
contador.

## Cuánto tarda

A los ~40 rps que sostiene el sistema, 100.000 peticiones son unos **40-45
minutos**. Está pensada para dejarla corriendo y volver, no para verla.

Cada 5 segundos imprime el avance con porcentaje y **minutos que faltan**,
así que se puede saber de un vistazo cuánto queda:

    … 34120/100000 (34.1%) ~41 rps  [832s, faltan 65880 -> ~26.8 min]

## Qué demuestra

Además del conteo, es la única corrida lo bastante larga como para enseñar
cosas que una ventana de 2 minutos no ve:

  - si el throughput **se degrada con el tiempo** (fugas de memoria o de
    conexiones se notan a los 20 minutos, no a los 2);
  - si el outbox y los consumidores van al día durante una sesión larga;
  - si la latencia p99 se mantiene o se va deteriorando.

## Antes de lanzarla

    docker compose stop sonarqube          # libera CPU
    python pruebas/limpiar_datos_carga.py --borrar

Lo segundo importa mucho aquí: 100.000 peticiones en modo mixto crean MUCHOS
tickets y productos, y los endpoints de listado devuelven todo sin paginar.
Si arrancas con la base ya llena, la corrida se degrada sola por el volumen
de datos y no por la carga — que es justo lo que NO se quiere medir.

Y en otra terminal, para las columnas de CPU/Mem y cola:

    python pruebas/monitor_recursos.py --duracion 2700

Uso:
    python pruebas/13_carga_100k_real.py                 # 100.000
    TOTAL=50000 python pruebas/13_carga_100k_real.py     # media corrida
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import nivel_carga  # noqa: E402


def main():
    total = int(os.environ.get("TOTAL", "100000"))
    # Tope de seguridad generoso (2 h): si algo se atasca, la prueba termina
    # sola en vez de quedarse colgada toda la noche. En condiciones normales
    # nunca se alcanza — corta el CONTEO, no el reloj.
    tope = int(os.environ.get("DURACION", "7200"))

    print(f"Objetivo: {total:,} peticiones reales.".replace(",", " "))
    print(f"A ~40 rps son unos {total/40/60:.0f} minutos. Tope de seguridad: {tope/60:.0f} min.")
    print("Puedes dejarla sola: cada 5s imprime el avance y los minutos que faltan.\n")

    nivel_carga(
        nombre="13_carga100k_real",
        objetivo="100k-REAL",
        # Concurrencia moderada A PROPÓSITO: es la que dio 99.6% de éxito en
        # las corridas cortas. Subirla no aumenta el throughput (el Gateway
        # va a 1 worker, ADR-0008) y sí dispara los timeouts, así que en una
        # corrida de 45 minutos solo serviría para acumular fallos.
        nodos=int(os.environ.get("NODOS", "4")),
        bloque=int(os.environ.get("BLOQUE", "16")),
        duracion_seg=tope,
        total=total,
    )


if __name__ == "__main__":
    main()

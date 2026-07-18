#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRUEBA 2 (S34): LÍNEA BASE de ~780 peticiones, por nodos y bloques.

Es el escalón más bajo de la serie 780 / 100k / 500k / 1M, y usa **la misma
metodología** que los otros tres: nodos concurrentes mandando bloques
sucesivos dentro de una ventana de tiempo, repartidos entre TODOS los
servicios y mezclando lecturas con escrituras.

POR QUÉ CAMBIÓ (2026-07-18)
La versión anterior disparaba las 780 peticiones **a la vez, con 20 hilos y
todas al MISMO endpoint de escritura** (`POST /tickets/`). Resultado medido:
3 exitosas de 780 (0.4%), con 757 respuestas 503 y 20 timeouts. Y no era un
fallo del sistema, sino de la prueba:

  - 20 escrituras simultáneas sostenidas contra un Gateway de 1 worker
    saturaban al ticket-service hasta el timeout;
  - esos timeouts abrían el circuito, y entonces TODO lo demás hacía
    fail-fast con 503 — que es exactamente lo que el breaker debe hacer.

Es decir: la prueba medía la reacción del breaker a una ráfaga mal repartida
y la presentaba como si fuese "capacidad del sistema", mientras su propio
texto decía "casi todo debe ser HTTP 200". Ese número no significaba nada y
además no era comparable con los otros tres niveles, que sí usan nodos.

Ahora comparte metodología con ellos, así que las cuatro filas de la tabla de
`documentacion/registro_de_carga.md` se pueden leer una al lado de la otra.

(La demostración de rate limit y bulkhead RECHAZANDO de forma controlada vive
en la prueba 06 de caos, fichas C y D, que es donde corresponde.)

Uso:  python pruebas/02_carga_780.py
Variables opcionales de entorno: NODOS, BLOQUE, DURACION
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import nivel_carga  # noqa: E402


def main():
    # ~780 peticiones: 2 nodos x bloques de 8 durante 25s a ~32 rps.
    # Concurrencia baja a propósito: es la línea BASE con la que se compara
    # el resto, así que tiene que medir el sistema descansado.
    nivel_carga(
        nombre="02_carga780",
        objetivo="780",
        nodos=int(os.environ.get("NODOS", "2")),
        bloque=int(os.environ.get("BLOQUE", "8")),
        duracion_seg=int(os.environ.get("DURACION", "25")),
    )


if __name__ == "__main__":
    main()

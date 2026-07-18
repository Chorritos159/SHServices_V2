#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Limpia los datos que generan las PRUEBAS DE CARGA en modo mixto.

Las escrituras de la carga crean tickets, productos, asignaciones,
diagnosticos y facturas marcados con el prefijo `CARGA` (ver
`pruebas/lib/carga_nodos.py`). Esto los borra para que la base quede limpia
para la demo, sin tocar los datos reales.

Uso:
  python pruebas/limpiar_datos_carga.py            # muestra cuanto hay
  python pruebas/limpiar_datos_carga.py --borrar   # borra de verdad
"""
import argparse
import subprocess
import sys

CONTENEDOR = "postgres-db"
USUARIO = "admin"
BD = "shservices_db"

# Orden: primero lo que depende del ticket, al final el ticket.
CONTEOS = [
    ("facturas de carga", "SELECT COUNT(*) FROM facturas WHERE id_ticket IN (SELECT id FROM tickets WHERE datos_cliente LIKE 'CARGA-%')"),
    ("diagnosticos de carga", "SELECT COUNT(*) FROM diagnosticos WHERE id_ticket IN (SELECT id FROM tickets WHERE datos_cliente LIKE 'CARGA-%')"),
    ("asignaciones de carga", "SELECT COUNT(*) FROM asignaciones WHERE id_ticket IN (SELECT id FROM tickets WHERE datos_cliente LIKE 'CARGA-%')"),
    ("tickets de carga", "SELECT COUNT(*) FROM tickets WHERE datos_cliente LIKE 'CARGA-%'"),
    ("productos de carga", "SELECT COUNT(*) FROM inventario WHERE nombre LIKE 'CARGA-%'"),
]

BORRADOS = [
    "DELETE FROM facturas WHERE id_ticket IN (SELECT id FROM tickets WHERE datos_cliente LIKE 'CARGA-%')",
    "DELETE FROM diagnosticos WHERE id_ticket IN (SELECT id FROM tickets WHERE datos_cliente LIKE 'CARGA-%')",
    "DELETE FROM asignaciones WHERE id_ticket IN (SELECT id FROM tickets WHERE datos_cliente LIKE 'CARGA-%')",
    "DELETE FROM garantias WHERE id_ticket IN (SELECT id FROM tickets WHERE datos_cliente LIKE 'CARGA-%')",
    "DELETE FROM tickets WHERE datos_cliente LIKE 'CARGA-%'",
    "DELETE FROM inventario WHERE nombre LIKE 'CARGA-%'",
]


def psql(sql: str) -> str:
    r = subprocess.run(
        ["docker", "exec", CONTENEDOR, "psql", "-U", USUARIO, "-d", BD, "-t", "-c", sql],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        return f"(error: {r.stderr.strip()[:120]})"
    return r.stdout.strip()


def main():
    p = argparse.ArgumentParser(description="Limpia los datos de las pruebas de carga")
    p.add_argument("--borrar", action="store_true", help="Borra de verdad (sin esto solo cuenta)")
    args = p.parse_args()

    print("\n=== Datos generados por las pruebas de carga (prefijo 'CARGA-') ===")
    for etiqueta, sql in CONTEOS:
        print(f"  {etiqueta}: {psql(sql)}")

    if not args.borrar:
        print("\n(solo conteo) Para borrarlos:  python pruebas/limpiar_datos_carga.py --borrar")
        return

    print("\nBorrando...")
    for sql in BORRADOS:
        salida = psql(sql)
        print(f"  {sql.split(' WHERE')[0][:55]}... -> {salida}")

    print("\n=== Despues de limpiar ===")
    for etiqueta, sql in CONTEOS:
        print(f"  {etiqueta}: {psql(sql)}")
    print("\nListo: la base queda sin datos de carga.")


if __name__ == "__main__":
    main()

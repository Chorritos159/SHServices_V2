#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Limpia TODO lo que generan las pruebas: base de datos y archivos.

Las pruebas de carga y de caos escriben en la base (tickets, productos,
facturas, notificaciones, eventos de auditoría) y dejan reportes en disco. Sin
limpiar entre corridas pasan dos cosas malas:

  - La base crece y las mediciones dejan de ser comparables: se acaba midiendo
    el VOLUMEN DE DATOS acumulado en vez de la carga. Ya ocurrió: con la base
    llena, `GET /tickets/` pasó de 64 ms a más de 90 segundos.
  - Los reportes viejos se mezclan con los nuevos en el informe.

QUÉ SE RECONOCE COMO DATO DE PRUEBA
Cada generador marca lo suyo, y hay que cubrirlos todos:

  - `CARGA-%`      -> escrituras de `pruebas/lib/carga_nodos.py`
  - `Cliente k6%`  -> escrituras de `pruebas_k6/carga.js`
  - `Cliente Flujo E2E`, `Cliente Caos%`, `Cliente Venta%` -> pruebas funcionales
  - trace_id `k6-%`, `carga%`, `e2e-%`, `caos%` -> notificaciones y auditoría

Las notificaciones y la auditoría son las que más crecen: una sola corrida dejó
**65.301** notificaciones y **60.866** eventos. No estaban contempladas antes.

Uso:
  python pruebas/limpiar_datos_carga.py             # solo cuenta, no borra
  python pruebas/limpiar_datos_carga.py --borrar    # borra de la BD
  python pruebas/limpiar_datos_carga.py --borrar --reportes   # + archivos
"""
import argparse
import glob
import os
import subprocess

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONTENEDOR = "postgres-db"
USUARIO = "admin"
BD = "shservices_db"

# Un ticket es "de prueba" si su cliente casa con alguno de estos patrones.
CLIENTES_PRUEBA = (
    "datos_cliente LIKE 'CARGA-%' OR "
    "datos_cliente LIKE 'Cliente k6%' OR "
    "datos_cliente LIKE 'Cliente Flujo E2E%' OR "
    "datos_cliente LIKE 'Cliente Caos%' OR "
    "datos_cliente LIKE 'Cliente Venta%' OR "
    "datos_cliente LIKE 'Cliente Mostrador%' OR "
    "datos_cliente LIKE 'Cliente Degradado%' OR "
    "datos_cliente LIKE 'Cliente Notis%' OR "
    "datos_cliente LIKE 'Repro %'"
)
TICKETS_PRUEBA = f"SELECT id FROM tickets WHERE {CLIENTES_PRUEBA}"

# Las notificaciones y los eventos se reconocen por el trace_id del generador.
TRAZAS_PRUEBA = (
    "trace_id LIKE 'k6-%' OR trace_id LIKE 'carga%' OR "
    "trace_id LIKE 'e2e-%' OR trace_id LIKE 'caos%' OR "
    "trace_id LIKE 'prueba%' OR trace_id LIKE 'lecturas%'"
)

CONTEOS = [
    ("tickets", f"SELECT COUNT(*) FROM tickets WHERE {CLIENTES_PRUEBA}"),
    ("facturas", f"SELECT COUNT(*) FROM facturas WHERE id_ticket IN ({TICKETS_PRUEBA})"),
    ("diagnosticos", f"SELECT COUNT(*) FROM diagnosticos WHERE id_ticket IN ({TICKETS_PRUEBA})"),
    ("asignaciones", f"SELECT COUNT(*) FROM asignaciones WHERE id_ticket IN ({TICKETS_PRUEBA})"),
    ("garantias", f"SELECT COUNT(*) FROM garantias WHERE id_ticket IN ({TICKETS_PRUEBA})"),
    ("productos", "SELECT COUNT(*) FROM inventario WHERE nombre LIKE 'CARGA-%'"),
    ("notificaciones", "SELECT COUNT(*) FROM notificaciones"),
    ("eventos de auditoria", "SELECT COUNT(*) FROM auditoria_eventos"),
]

# Orden: primero lo que depende del ticket, al final el ticket.
BORRADOS = [
    f"DELETE FROM facturas WHERE id_ticket IN ({TICKETS_PRUEBA})",
    f"DELETE FROM garantias WHERE id_ticket IN ({TICKETS_PRUEBA})",
    f"DELETE FROM diagnosticos WHERE id_ticket IN ({TICKETS_PRUEBA})",
    f"DELETE FROM asignaciones WHERE id_ticket IN ({TICKETS_PRUEBA})",
    f"DELETE FROM tickets WHERE {CLIENTES_PRUEBA}",
    "DELETE FROM inventario WHERE nombre LIKE 'CARGA-%'",
    f"DELETE FROM notificaciones WHERE {TRAZAS_PRUEBA}",
    f"DELETE FROM auditoria_eventos WHERE {TRAZAS_PRUEBA}",
    # El outbox del Gateway guarda las escrituras que no se pudieron entregar
    # durante las pruebas de caos; ya entregadas o descartadas, no aportan nada.
    "DELETE FROM gateway_outbox WHERE estado IN ('ENTREGADO', 'DESCARTADO')",

    # HUERFANAS. El generador de Python no manda X-Correlation-ID, asi que el
    # Gateway genera un UUID y esas notificaciones/eventos no se reconocen por
    # la traza. Pero SI se reconocen por lo que apuntan: si su `referencia` era
    # un ticket o un producto que acabamos de borrar, el registro ya no
    # describe nada. Va DESPUES de borrar tickets y productos, a proposito.
    """DELETE FROM notificaciones WHERE referencia IS NOT NULL AND referencia <> '-'
       AND referencia NOT IN (SELECT id FROM tickets)
       AND referencia NOT IN (SELECT codigo FROM inventario)""",
    """DELETE FROM auditoria_eventos WHERE id_ticket IS NOT NULL AND id_ticket <> '-'
       AND id_ticket NOT IN (SELECT id FROM tickets)
       AND id_ticket NOT IN (SELECT codigo FROM inventario)""",
]

# Carpetas de reportes que las pruebas van llenando.
REPORTES = [
    "pruebas/resultados",
    "pruebas_reales/resultados",
    "pruebas_k6/resultados",
]


def psql(sql: str) -> str:
    r = subprocess.run(
        ["docker", "exec", CONTENEDOR, "psql", "-U", USUARIO, "-d", BD, "-t", "-c", sql],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        return f"(error: {r.stderr.strip()[:120]})"
    return r.stdout.strip()


def limpiar_reportes(borrar: bool):
    print("\n=== Reportes en disco ===")
    total = 0
    for carpeta in REPORTES:
        ruta = os.path.join(RAIZ, carpeta)
        if not os.path.isdir(ruta):
            continue
        archivos = [f for f in glob.glob(os.path.join(ruta, "*"))
                    if os.path.isfile(f) and not f.endswith(".gitkeep")]
        peso = sum(os.path.getsize(f) for f in archivos) / 1024
        print(f"  {carpeta}: {len(archivos)} archivo(s), {peso:.0f} KB")
        total += len(archivos)
        if borrar:
            for f in archivos:
                try:
                    os.remove(f)
                except OSError as exc:
                    print(f"    no se pudo borrar {os.path.basename(f)}: {exc}")
    if borrar and total:
        print(f"  -> {total} archivo(s) borrados")
    elif not borrar and total:
        print("  (usa --reportes junto con --borrar para eliminarlos)")


def main():
    p = argparse.ArgumentParser(description="Limpia los datos y reportes de las pruebas")
    p.add_argument("--borrar", action="store_true", help="Borra de verdad (sin esto solo cuenta)")
    p.add_argument("--reportes", action="store_true",
                   help="Borra tambien los archivos de pruebas/*/resultados")
    args = p.parse_args()

    print("\n=== Datos generados por las pruebas ===")
    for etiqueta, sql in CONTEOS:
        print(f"  {etiqueta:22s} {psql(sql)}")

    if not args.borrar:
        limpiar_reportes(False)
        print("\n(solo conteo) Para borrar:")
        print("  python pruebas/limpiar_datos_carga.py --borrar              # BD")
        print("  python pruebas/limpiar_datos_carga.py --borrar --reportes   # BD + archivos")
        return

    print("\nBorrando de la base...")
    for sql in BORRADOS:
        tabla = sql.split("FROM ")[1].split()[0]
        print(f"  {tabla:22s} {psql(sql)}")

    print("\n=== Despues de limpiar ===")
    for etiqueta, sql in CONTEOS:
        print(f"  {etiqueta:22s} {psql(sql)}")

    limpiar_reportes(args.reportes)

    # VACUUM recupera el espacio de las filas borradas y actualiza las
    # estadisticas del planificador: sin esto, PostgreSQL sigue creyendo que
    # las tablas son enormes y elige planes malos en la siguiente corrida.
    print("\nCompactando tablas (VACUUM ANALYZE)...")
    psql("VACUUM ANALYZE tickets, inventario, notificaciones, auditoria_eventos, facturas")
    print("Listo: la base queda como para una corrida limpia.")


if __name__ == "__main__":
    main()

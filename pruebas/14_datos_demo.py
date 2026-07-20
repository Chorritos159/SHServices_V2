#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DATOS DE DEMO — deja el sistema con algo que ensenar.

Recien levantado, el sistema arranca con usuarios y almacen (los siembran solos
`auth_service/app/main.py` y `almacen_service/app/core/seed.py`), pero SIN
tickets: los paneles salen vacios y no hay nada que mostrar en una demo.

Este script rellena ese hueco creando el ciclo de negocio completo.

POR QUE POR LA API Y NO CON INSERTs
Todo va por el Gateway, como un usuario real. Asi los datos respetan las reglas
de negocio (estados validos, stock reservado de verdad, eventos publicados a
RabbitMQ, notificaciones generadas) en vez de ser filas sueltas que no cuadran
entre servicios. Un INSERT directo crearia un ticket que ningun evento anuncio
y que las notificaciones nunca verian.

ES IDEMPOTENTE. Cada escritura manda su `Idempotency-Key` derivada, asi que
correrlo dos veces NO duplica nada: la segunda vez el sistema devuelve lo que
ya habia.

Uso:
    python pruebas/14_datos_demo.py             # el juego completo
    python pruebas/14_datos_demo.py --tickets 5 # mas tickets
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, "reconfigure"):
        _f.reconfigure(encoding="utf-8", errors="replace")

GW = "http://localhost:8000"

# Estos usuarios NO se crean aqui: ya los siembra auth_service al arrancar.
# Se listan para que se vea con que credenciales entrar en la demo.
USUARIOS = [
    ("admin", "admin123", "ADMIN", "PIURA"),
    ("caja01", "caja123", "CAJA", "PIURA"),
    ("tecnico01", "tecnico123", "TECNICO", "PIURA"),
    ("caja02", "caja123", "CAJA", "TALARA"),
    ("tecnico02", "tecnico123", "TECNICO", "TALARA"),
]

CLIENTES = [
    ("Maria Quispe", "71234567", "959111222", "Laptop HP 240", "SN-HP-0091", "No enciende"),
    ("Jose Ramirez", "40551234", "958222333", "PC de escritorio", "SN-PC-0142", "Se apaga sola"),
    ("Ana Torres", "72998811", "957333444", "Laptop Lenovo", "SN-LN-0233", "Pantalla azul"),
    ("Luis Chavez", "43210987", "956444555", "Impresora Epson", "SN-EP-0077", "Atasca el papel"),
    ("Rosa Diaz", "70112233", "955555666", "All-in-One Dell", "SN-DL-0310", "No da video"),
]


def pedir(ruta, metodo="GET", cuerpo=None, token=None, clave=None, timeout=25):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cab = {"Content-Type": "application/json"}
    if token:
        cab["Authorization"] = f"Bearer {token}"
    if clave:
        cab["Idempotency-Key"] = clave
    pet = urllib.request.Request(f"{GW}{ruta}", data=datos, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(pet, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def login(usuario, password):
    _, cuerpo = pedir("/api/v1/auth/login", "POST",
                      {"usuario": usuario, "password": password})
    try:
        return json.loads(cuerpo).get("access_token", "")
    except Exception:
        return ""


def json_de(cuerpo):
    try:
        return json.loads(cuerpo)
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickets", type=int, default=3,
                    help="Cuantos tickets de soporte crear (por defecto 3)")
    args = ap.parse_args()
    cuantos = max(1, min(args.tickets, len(CLIENTES)))

    print("=" * 68)
    print(" DATOS DE DEMO — SHServices V2")
    print("=" * 68)

    token_admin = login("admin", "admin123")
    if not token_admin:
        print("\nNo se pudo iniciar sesion como admin.")
        print("Esta el sistema levantado? Comprueba con: docker compose ps")
        sys.exit(1)

    # ── Usuarios ──────────────────────────────────────────────────────
    print("\n[1/4] Usuarios (los siembra auth-service al arrancar)")
    cod, cuerpo = pedir("/api/v1/auth/auth/usuarios", token=token_admin)
    existentes = {u.get("usuario") for u in json_de(cuerpo)} if cod == 200 else set()
    for usuario, password, rol, sede in USUARIOS:
        marca = "OK" if usuario in existentes else "FALTA"
        print(f"  [{marca:5}] {usuario:10} {password:12} {rol:8} {sede}")

    # ── Almacen ───────────────────────────────────────────────────────
    print("\n[2/4] Almacen (lo siembra almacen-service al arrancar)")
    cod, cuerpo = pedir("/api/v1/almacen/almacen/productos?limite=500", token=token_admin)
    datos = json_de(cuerpo)
    items = datos if isinstance(datos, list) else datos.get("items", [])
    repuestos = [i for i in items if i.get("categoria") == "REPUESTO"]
    venta = [i for i in items if i.get("categoria") == "PRODUCTO_VENTA"]
    print(f"  repuestos ............ {len(repuestos)}")
    print(f"  productos de venta ... {len(venta)}")
    if not repuestos:
        print("  (sin repuestos: el diagnostico de abajo no podra reservar stock)")

    # ── Tickets ───────────────────────────────────────────────────────
    print(f"\n[3/4] Creando {cuantos} ticket(s) de soporte en PIURA")
    creados = []
    for i in range(cuantos):
        nombre, doc, tel, equipo, serie, falla = CLIENTES[i]
        # Clave DERIVADA del documento y la serie: correr esto dos veces NO
        # crea tickets nuevos, porque la clave es la misma.
        cod, cuerpo = pedir(
            "/api/v1/tickets/tickets/", "POST",
            {"datosCliente": nombre, "documento_cliente": doc,
             "telefono_cliente": tel, "tipoOperacion": "SOPORTE",
             "prioridad": ["ALTA", "MEDIA", "BAJA"][i % 3],
             "equipo": equipo, "numero_serie": serie,
             "caracteristicas_falla": falla},
            token=token_admin, clave=f"demo-ticket-{doc}-{serie}")
        tid = json_de(cuerpo).get("idTicket")
        if tid:
            creados.append((tid, nombre, equipo))
            print(f"  [{cod}] {tid}  {nombre} · {equipo}")
        else:
            print(f"  [{cod}] fallo con {nombre}: {cuerpo[:90]}")

    # ── Ciclo completo sobre el primero ───────────────────────────────
    print("\n[4/4] Ciclo completo sobre el primer ticket (diagnostico + cobro)")
    if not creados:
        print("  no hay tickets; se omite.")
    elif not repuestos:
        print("  no hay repuestos en almacen; se omite el diagnostico.")
    else:
        tid, nombre, _e = creados[0]
        repuesto = repuestos[0]["codigo"]
        token_tec = login("tecnico01", "tecnico123") or token_admin

        cod, cuerpo = pedir(
            "/api/v1/diagnosticos/diagnosticos/", "POST",
            {"idTicket": tid, "fallaDetectada": "Fuente de poder danada",
             "mano_obra": 60.0, "precio_reparacion": 180.0,
             "repuestos": [{"codigo_repuesto": repuesto, "cantidad": 1}]},
            token=token_tec, clave=f"demo-diag-{tid}")
        print(f"  [{cod}] diagnostico de {tid} (reserva 1x {repuesto})")

        token_caja = login("caja01", "caja123") or token_admin
        cod, cuerpo = pedir(
            "/api/v1/facturas/facturas/", "POST",
            {"idTicket": tid, "montoManoObra": 60.0, "montoRepuestos": 120.0,
             "lineas": [], "metodoPago": "EFECTIVO", "sede": "PIURA",
             "tipoOperacion": "SOPORTE", "documentoCliente": CLIENTES[0][1]},
            token=token_caja, clave=f"demo-fact-{tid}")
        factura = json_de(cuerpo)
        if cod in (200, 201):
            print(f"  [{cod}] comprobante {factura.get('idFactura')} por "
                  f"S/.{factura.get('montoTotal')} (emite garantia de 90 dias)")
        else:
            print(f"  [{cod}] cobro: {cuerpo[:100]}")

    # ── Resumen ───────────────────────────────────────────────────────
    print("\n" + "=" * 68)
    print(" LISTO. Entra en http://localhost:3001 con:")
    print("=" * 68)
    for usuario, password, rol, sede in USUARIOS[:3]:
        print(f"   {usuario:10} / {password:12}  ({rol} de {sede})")
    print("\n Que ver en cada rol:")
    print("   ADMIN    -> Listado de Almacen, Auditoria, Garantias y Facturas")
    print("   TECNICO  -> Diagnostico Tecnico (los tickets en cola)")
    print("   CAJA     -> Venta de mostrador y Garantias y Facturas")
    print("\n Para borrar lo que genera este script y las pruebas:")
    print("   python pruebas/limpiar_datos_carga.py --borrar")
    print("=" * 68)


if __name__ == "__main__":
    main()

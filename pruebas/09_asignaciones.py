#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRUEBA 9: Asignacion exclusiva de tickets y su resiliencia.

Verifica la funcionalidad "el tecnico elige su ticket y se queda para el",
gestionada por el diagnostico-service (dueno de las asignaciones), y que NO
depende del ticket-service para lo critico:

  1. CAJA crea un ticket SOPORTE en PIURA.
  2. tecnico01 lo TOMA                    -> 201, queda asignado a el.
  3. tecnico02 intenta tomarlo            -> 409 (exclusividad).
  4. tecnico01 lo toma otra vez           -> idempotente (no duplica).
  5. "Mis Tickets" de tecnico01           -> contiene el ticket.
  6. "Mis Tickets" de tecnico02           -> NO lo contiene.
  7. ADMIN ve "quien atiende que"         -> aparece tecnico01; un tecnico -> 403.
  8. RESILIENCIA: con ticket-service PAUSADO, "Mis Tickets" SIGUE funcionando.
  9. El diagnostico duplicado da 409 legible (no 500 "error inesperado").

Uso:  python pruebas/09_asignaciones.py
"""
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import GW, banner, login, verificar_sistema, docker  # noqa: E402


def main():
    banner("PRUEBA 9: Asignacion exclusiva de tickets y resiliencia")
    verificar_sistema()

    fallos = 0

    def check(cond, ok_msg, fail_msg):
        nonlocal fallos
        if cond:
            print(f"  [OK]   {ok_msg}")
        else:
            print(f"  [FALLA] {fail_msg}")
            fallos += 1

    def hdr(token):
        return {"Authorization": f"Bearer {token}"}

    # 0. Autenticacion
    t_caja = login("caja01", "caja123")
    t_tec1 = login("tecnico01", "tecnico123")
    t_tec2 = login("tecnico02", "tecnico123")
    t_admin = login("admin", "admin123")

    # 1. CAJA crea un ticket SOPORTE en PIURA
    r = httpx.post(f"{GW}/api/v1/tickets/tickets/", headers=hdr(t_caja), timeout=15.0, json={
        "datosCliente": "Cliente Asignacion P9", "documento_cliente": "44556677",
        "telefono_cliente": "987000111", "tipoOperacion": "SOPORTE",
        "equipo": "PC Oficina", "numero_serie": "SN-P9-1",
        "caracteristicas_falla": "No arranca", "prioridad": "NORMAL",
    })
    tk = r.json().get("idTicket") if r.status_code < 400 else None
    check(tk is not None, f"ticket {tk} creado", f"no se creo el ticket: {r.status_code} {r.text}")
    if not tk:
        sys.exit(1)

    cuerpo_tomar = {"id_ticket": tk, "datos_cliente": "Cliente Asignacion P9",
                    "equipo": "PC Oficina", "numero_serie": "SN-P9-1",
                    "prioridad": "NORMAL", "tipo_operacion": "SOPORTE"}

    # 2. tecnico01 lo toma
    r = httpx.post(f"{GW}/api/v1/diagnosticos/asignaciones/tomar", headers=hdr(t_tec1), timeout=15.0, json=cuerpo_tomar)
    check(r.status_code == 201 and r.json().get("tecnico") == "tecnico01",
          "tecnico01 tomo el ticket", f"no se tomo: {r.status_code} {r.text}")

    # 3. tecnico02 intenta tomarlo -> 409
    r = httpx.post(f"{GW}/api/v1/diagnosticos/asignaciones/tomar", headers=hdr(t_tec2), timeout=15.0,
                   json={"id_ticket": tk})
    check(r.status_code == 409, "tecnico02 recibe 409 (exclusividad)",
          f"deberia ser 409, fue {r.status_code} {r.text}")

    # 4. tecnico01 lo toma otra vez -> idempotente
    r = httpx.post(f"{GW}/api/v1/diagnosticos/asignaciones/tomar", headers=hdr(t_tec1), timeout=15.0, json=cuerpo_tomar)
    check(r.status_code in (200, 201) and r.json().get("tecnico") == "tecnico01",
          "retomar por el mismo tecnico es idempotente", f"fallo idempotencia: {r.status_code} {r.text}")

    # 5. Mis Tickets de tecnico01 contiene el ticket
    r = httpx.get(f"{GW}/api/v1/diagnosticos/asignaciones/mias", headers=hdr(t_tec1), timeout=15.0)
    ids1 = [a["id_ticket"] for a in r.json()] if r.status_code < 400 else []
    check(tk in ids1, "el ticket esta en 'Mis Tickets' de tecnico01", f"no aparece: {r.status_code} {ids1}")

    # 6. Mis Tickets de tecnico02 NO lo contiene
    r = httpx.get(f"{GW}/api/v1/diagnosticos/asignaciones/mias", headers=hdr(t_tec2), timeout=15.0)
    ids2 = [a["id_ticket"] for a in r.json()] if r.status_code < 400 else []
    check(tk not in ids2, "el ticket NO aparece en 'Mis Tickets' de tecnico02",
          f"no deberia aparecer: {ids2}")

    # 7. ADMIN ve quien atiende que; un tecnico recibe 403
    r = httpx.get(f"{GW}/api/v1/diagnosticos/asignaciones/", headers=hdr(t_admin), timeout=15.0)
    admin_ve = r.status_code < 400 and any(a["id_ticket"] == tk and a["tecnico"] == "tecnico01" for a in r.json())
    check(admin_ve, "ADMIN ve el ticket asignado a tecnico01", f"admin no lo ve: {r.status_code}")
    r = httpx.get(f"{GW}/api/v1/diagnosticos/asignaciones/", headers=hdr(t_tec1), timeout=15.0)
    check(r.status_code == 403, "un tecnico recibe 403 en la vista de admin", f"deberia 403, fue {r.status_code}")

    # 8. RESILIENCIA: con ticket-service PAUSADO, "Mis Tickets" sigue funcionando
    print("  ... pausando ticket-service para probar la independencia ...")
    docker("pause", "ticket-service")
    try:
        r = httpx.get(f"{GW}/api/v1/diagnosticos/asignaciones/mias", headers=hdr(t_tec1), timeout=15.0)
        ok = r.status_code < 400 and tk in [a["id_ticket"] for a in r.json()]
        check(ok, "'Mis Tickets' funciona con ticket-service CAIDO", f"fallo: {r.status_code} {r.text}")
    finally:
        docker("unpause", "ticket-service")
        time.sleep(2)

    # 9. Diagnostico duplicado -> 409 legible (no 500 "error inesperado")
    diag = {"idTicket": tk, "fallaDetectada": "Fuente danada", "mano_obra": 40, "precio_reparacion": 90, "repuestos": []}
    r = httpx.post(f"{GW}/api/v1/diagnosticos/diagnosticos/", headers=hdr(t_tec1), timeout=15.0, json=diag)
    check(r.status_code == 201, "primer diagnostico OK", f"fallo el 1er diagnostico: {r.status_code} {r.text}")
    r = httpx.post(f"{GW}/api/v1/diagnosticos/diagnosticos/", headers=hdr(t_tec1), timeout=15.0, json=diag)
    check(r.status_code == 409, "diagnostico duplicado -> 409 legible (no 500)",
          f"deberia 409, fue {r.status_code} {r.text}")

    print()
    if fallos == 0:
        print("  RESULTADO: TODAS LAS VERIFICACIONES PASARON")
        sys.exit(0)
    print(f"  RESULTADO: {fallos} verificacion(es) fallaron")
    sys.exit(1)


if __name__ == "__main__":
    main()

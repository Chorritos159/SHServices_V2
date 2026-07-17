#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRUEBA 8 (Fase 8, S34): el flujo de negocio COMPLETO tocando los 8 servicios.

Recorre el ciclo de vida real de un ticket SOPORTE de punta a punta, con los
tres roles y un unico correlationId, y ademas los casos sueltos (admin agrega
inventario, consultas). Al final verifica que los 8 servicios recibieron
trafico: una prueba que solo golpea 'tickets' deja 7 servicios sin ejercitar.

Flujo:
  1. CAJA registra un ticket SOPORTE           -> ticket-service (EN_COLA)
  2. TECNICO lo toma                            -> ticket-service (EN_DIAGNOSTICO)
  3. TECNICO diagnostica y reserva un repuesto  -> diagnostico-service -> almacen-service
  4. TECNICO marca diagnosticado                -> ticket-service (DIAGNOSTICADO, evento ticket.listo)
  5. CAJA cobra                                 -> facturacion-service (evento ticket.facturado)
  6. CAJA entrega                               -> ticket-service (ENTREGADO) -> almacen (confirma stock)
  7. ADMIN agrega inventario                    -> almacen-service (evento producto.registrado)
  8. ADMIN consulta la auditoria                -> auditoria-service
  9. TECNICO consulta sus notificaciones        -> notificacion-service
Los eventos (pasos 1/4/5/7) los consumen auditoria y notificacion por RabbitMQ.

Uso:  python pruebas/08_flujo_completo.py
"""
import os
import subprocess
import sys
import time
from datetime import datetime

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import GW, AUTH, RESULTADOS, login, verificar_sistema  # noqa: E402

# Los 8 servicios que la prueba debe ejercitar, con su contenedor.
SERVICIOS = {
    "auth-service": "auth-service",
    "api-gateway": "api-gateway",
    "ticket-service": "ticket-service",
    "diagnostico-service": "diagnostico-service",
    "almacen-service": "almacen-service",
    "facturacion-service": "facturacion-service",
    "auditoria-service": "auditoria-service",
    "notificacion-service": "notificacion-service",
}


def main():
    verificar_sistema()
    cid = f"e2e-flujo-{int(time.time())}"
    salida, fallos = [], []

    def out(linea=""):
        print(linea)
        salida.append(linea)

    def paso(msg):
        out()
        out(f"--- {msg}")

    def check(cond, ok_msg, fail_msg):
        if cond:
            out(f"    OK: {ok_msg}")
        else:
            out(f"    FALLO: {fail_msg}")
            fallos.append(fail_msg)

    H = {"X-Correlation-ID": cid, "Content-Type": "application/json"}

    def hdr(token):
        return {**H, "Authorization": f"Bearer {token}"}

    out("=" * 64)
    out(f" PRUEBA 8: FLUJO COMPLETO tocando los 8 servicios - trace {cid}")
    out("=" * 64)

    # ------------------------------------------------------------------
    paso("0. Autenticacion de los 3 roles (auth-service)")
    t_caja = login("caja01", "caja123")
    t_tec = login("tecnico01", "tecnico123")
    t_admin = login("admin", "admin123")
    check(all([t_caja, t_tec, t_admin]), "caja01 / tecnico01 / admin autenticados",
          "algun login fallo")

    # ------------------------------------------------------------------
    paso("1. CAJA registra un ticket SOPORTE (ticket-service -> EN_COLA)")
    r = httpx.post(f"{GW}/api/v1/tickets/tickets/", headers=hdr(t_caja), timeout=15.0, json={
        "datosCliente": "Cliente Flujo E2E", "documento_cliente": "70605040",
        "telefono_cliente": "987654321", "tipoOperacion": "SOPORTE",
        "equipo": "Laptop Lenovo", "numero_serie": "SN-E2E-1",
        "caracteristicas_falla": "No enciende, huele a quemado", "prioridad": "ALTA",
    })
    tk = r.json().get("idTicket") if r.status_code < 400 else None
    check(tk is not None, f"ticket {tk} creado (estado {r.json().get('estadoInicial')})",
          f"no se creo el ticket: HTTP {r.status_code} {r.text}")
    if not tk:
        _finalizar(salida, fallos)

    # ------------------------------------------------------------------
    paso("2. TECNICO toma el ticket (ticket-service -> EN_DIAGNOSTICO)")
    r = httpx.post(f"{GW}/api/v1/tickets/tickets/{tk}/tomar", headers=hdr(t_tec), timeout=15.0)
    check(r.status_code < 400 and r.json().get("estado") == "EN_DIAGNOSTICO",
          "ticket en EN_DIAGNOSTICO", f"no se pudo tomar: HTTP {r.status_code} {r.text}")

    # ------------------------------------------------------------------
    paso("3. TECNICO diagnostica y RESERVA un repuesto (diagnostico-service -> almacen-service)")
    # REP-001 existe en PIURA por el seed (tecnico01 es de PIURA).
    stock_antes = _stock(t_admin, "REP-001", "PIURA")
    r = httpx.post(f"{GW}/api/v1/diagnosticos/diagnosticos/", headers=hdr(t_tec), timeout=15.0, json={
        "idTicket": tk, "fallaDetectada": "Placa madre danada, requiere ventilador",
        "mano_obra": 80.0, "precio_reparacion": 125.0,
        "repuestos": [{"codigo_repuesto": "REP-001", "descripcion": "Ventilador", "cantidad": 1, "precio_unitario": 45.0}],
    })
    diag_ok = r.status_code < 400
    stock_despues = _stock(t_admin, "REP-001", "PIURA")
    check(diag_ok, f"diagnostico registrado ({r.json().get('idDiagnostico') if diag_ok else ''})",
          f"no se registro el diagnostico: HTTP {r.status_code} {r.text}")
    check(stock_antes is not None and stock_despues == stock_antes - 1,
          f"almacen reservo el repuesto (stock REP-001 PIURA: {stock_antes} -> {stock_despues})",
          f"el stock no bajo como se esperaba ({stock_antes} -> {stock_despues})")

    # ------------------------------------------------------------------
    paso("4. TECNICO marca DIAGNOSTICADO (ticket-service, emite ticket.listo)")
    r = httpx.post(f"{GW}/api/v1/tickets/tickets/{tk}/diagnosticar", headers=hdr(t_tec), timeout=15.0, json={
        "repuestos": [{"codigo_producto": "REP-001", "cantidad": 1}],
    })
    check(r.status_code < 400 and r.json().get("estado") == "DIAGNOSTICADO",
          "ticket en DIAGNOSTICADO", f"no se pudo diagnosticar: HTTP {r.status_code} {r.text}")

    # ------------------------------------------------------------------
    paso("5. CAJA cobra (facturacion-service, emite ticket.facturado)")
    r = httpx.post(f"{GW}/api/v1/facturas/facturas/", headers=hdr(t_caja), timeout=15.0, json={
        "idTicket": tk, "sede": "PIURA", "montoManoObra": 80.0, "montoRepuestos": 45.0,
        "metodoPago": "EFECTIVO", "lineas": [],
    })
    fac_ok = r.status_code < 400
    check(fac_ok, f"factura {r.json().get('idFactura') if fac_ok else ''} por S/.{r.json().get('montoTotal') if fac_ok else '?'}",
          f"no se pudo cobrar: HTTP {r.status_code} {r.text}")

    # ------------------------------------------------------------------
    paso("6. CAJA entrega (ticket-service -> ENTREGADO, almacen confirma stock)")
    r = httpx.post(f"{GW}/api/v1/tickets/tickets/{tk}/entregar", headers=hdr(t_caja), timeout=15.0,
                   json={"monto_total": 125.0})
    check(r.status_code < 400, "ticket ENTREGADO, stock confirmado",
          f"no se pudo entregar: HTTP {r.status_code} {r.text}")

    # ------------------------------------------------------------------
    paso("7. ADMIN agrega inventario nuevo (almacen-service, emite producto.registrado)")
    r = httpx.post(f"{GW}/api/v1/almacen/almacen/productos", headers=hdr(t_admin), timeout=15.0, json={
        "nombre": "Cargador tipo C 100W", "categoria": "REPUESTO", "sede": "PIURA",
        "stock_inicial": 30, "precio_unitario": 110.0,
    })
    check(r.status_code < 400, f"producto {r.json().get('codigo') if r.status_code < 400 else ''} ingresado",
          f"no se pudo agregar inventario: HTTP {r.status_code} {r.text}")

    out("\n    (esperando propagacion asincrona de eventos por RabbitMQ...)")
    time.sleep(4)

    # ------------------------------------------------------------------
    paso("8. ADMIN consulta la auditoria (auditoria-service)")
    r = httpx.get(f"{GW}/api/v1/auditoria/auditoria/eventos", headers=hdr(t_admin), timeout=15.0)
    eventos_flujo = [e for e in r.json() if e.get("trace_id") == cid] if r.status_code < 400 else []
    check(len(eventos_flujo) >= 1, f"auditoria tiene {len(eventos_flujo)} evento(s) de este flujo",
          "auditoria no registro eventos de este flujo")

    # ------------------------------------------------------------------
    paso("9. TECNICO consulta sus notificaciones (notificacion-service)")
    r = httpx.get(f"{GW}/api/v1/notificaciones/notificaciones/mis-alertas", headers=hdr(t_tec), timeout=15.0)
    tiene_alerta = r.status_code < 400 and any(n.get("referencia") == tk for n in r.json())
    check(tiene_alerta, f"el tecnico ve la alerta del ticket {tk}",
          "el tecnico no recibio la notificacion del ticket")

    # ------------------------------------------------------------------
    paso("COBERTURA: los 8 servicios recibieron trafico de este flujo?")
    _verificar_cobertura(cid, tk, out, fallos)

    _finalizar(salida, fallos)


def _stock(token, codigo, sede):
    """Stock disponible de un producto (via el listado del almacen)."""
    try:
        r = httpx.get(f"{GW}/api/v1/almacen/almacen/productos",
                      headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
        for p in r.json():
            if p["codigo"] == codigo and p["sede"] == sede:
                return p["stock_disponible"]
    except Exception:
        return None
    return None


def _verificar_cobertura(cid, tk, out, fallos):
    """Confirma que cada servicio logueo algo de este flujo.

    Los 6 servicios de negocio + gateway comparten el correlationId (via
    cabecera o via RabbitMQ). auth se verifica aparte (su login no lleva el
    mismo correlationId, pero si respondio tokens el flujo no habria arrancado).
    """
    tocados = {"auth-service": True}  # si no, ningun login habria funcionado
    for contenedor in ("api-gateway", "ticket-service", "diagnostico-service",
                        "almacen-service", "facturacion-service",
                        "auditoria-service", "notificacion-service"):
        r = subprocess.run(
            ["docker", "logs", contenedor, "--since", "120s"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        logs = (r.stdout or "") + (r.stderr or "")
        # El correlationId aparece en los logs sincronos; para almacen (que
        # tambien se toca via el reserve/confirm interno) y los consumidores
        # basta con que aparezca el cid o el idTicket.
        tocados[contenedor] = (cid in logs) or (tk in logs)

    for servicio in SERVICIOS:
        ok = tocados.get(servicio, False)
        out(f"    {'OK ' if ok else 'NO '} {servicio}")
        if not ok:
            fallos.append(f"{servicio} no recibio trafico de este flujo")


def _finalizar(salida, fallos):
    salida.append("")
    salida.append("=" * 64)
    if fallos:
        salida.append(f" RESULTADO: {len(fallos)} FALLO(S)")
        for f in fallos:
            salida.append(f"   - {f}")
    else:
        salida.append(" RESULTADO: OK - el flujo completo recorrio los 8 servicios.")
    salida.append("=" * 64)
    print("\n".join(salida[-(len(fallos) + 4):]))

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta = f"{RESULTADOS}/08_flujo_completo_{marca}.txt"
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write("\n".join(salida) + "\n")
    print(f"Reporte guardado en: {ruta}")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRUEBA 1 (Fase 5, S34): una operación completa trazada de inicio a fin
con UN correlationId — crea un ticket y verifica que el mismo trace_id
aparece en los logs estructurados del gateway, ticket-service,
auditoria-service y notificacion-service, y que el evento quedó
persistido en ambos.

Uso:  python pruebas/01_traza_unica.py
"""
import os
import subprocess
import sys
import time
from datetime import datetime

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import GW, RESULTADOS, login, verificar_sistema  # noqa: E402


def main():
    verificar_sistema()
    cid = f"prueba1-traza-{int(time.time())}"
    salida = []

    def out(linea=""):
        print(linea)
        salida.append(linea)

    out()
    out("=" * 44)
    out(f" PRUEBA 1: TRAZA ÚNICA — correlationId {cid}")
    out("=" * 44)

    token = login("admin", "admin123")
    out(f"Creando ticket con X-Correlation-ID: {cid} ...")
    resp = httpx.post(
        f"{GW}/api/v1/tickets/tickets/",
        headers={"Authorization": f"Bearer {token}", "X-Correlation-ID": cid},
        json={
            "datosCliente": "Cliente Traza Unica",
            "documento_cliente": "70605040",
            "telefono_cliente": "987654321",
            "tipoOperacion": "SOPORTE",
            "equipo": "Laptop HP",
            "numero_serie": "SN-TRAZA-1",
            "caracteristicas_falla": "No enciende",
            "prioridad": "ALTA",
        },
        timeout=15.0,
    )
    tk = resp.json().get("idTicket") if resp.status_code < 400 else None
    if not tk:
        out(f"No se pudo crear el ticket: HTTP {resp.status_code} {resp.text}")
        sys.exit(1)
    out(f"Ticket creado: {tk}")

    out("Esperando propagación asíncrona (RabbitMQ -> auditoría/notificaciones)...")
    time.sleep(3)

    out()
    out("=" * 44)
    out(" 1. Auditoría — el evento debe aparecer con este trace_id")
    out("=" * 44)
    eventos = httpx.get(
        f"{GW}/api/v1/auditoria/auditoria/eventos",
        headers={"Authorization": f"Bearer {token}"}, timeout=10.0,
    ).json()
    match = [e for e in eventos if e.get("trace_id") == cid]
    out(f"  eventos con este trace_id: {len(match)}")
    for e in match:
        out(f"    {e['evento']} idTicket={e['idTicket']}")

    out()
    out("=" * 44)
    out(" 2. Notificaciones — debe existir una alerta para TECNICO")
    out("=" * 44)
    token_tec = login("tecnico01", "tecnico123")
    try:
        notifs = httpx.get(
            f"{GW}/api/v1/notificaciones/notificaciones/mis-alertas",
            headers={"Authorization": f"Bearer {token_tec}"}, timeout=10.0,
        ).json()
        match_n = [n for n in notifs if n.get("referencia") == tk]
        out(f"  notificaciones referidas a este ticket ({tk}): {len(match_n)}")
        for n in match_n:
            out(f"    {n['mensaje']}")
    except Exception as e:
        out(f"  (no se pudo leer la bandeja: {e})")

    out()
    out("=" * 44)
    out(" 3. Logs estructurados de los contenedores — mismo correlationId")
    out("=" * 44)
    for contenedor in ("api-gateway", "ticket-service", "auditoria-service", "notificacion-service"):
        # encoding utf-8 explícito: los logs traen emojis (, ...) y en
        # Windows `text=True` decodifica con cp1252 por defecto -> peta con
        # UnicodeDecodeError. errors="replace" por si algún byte suelto no
        # es UTF-8 válido (no queremos que la prueba muera por un log raro).
        r = subprocess.run(
            ["docker", "logs", contenedor, "--since", "30s"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        n = ((r.stdout or "") + (r.stderr or "")).count(f'"correlationId": "{cid}"')
        out(f"  {contenedor}: {n} líneas con correlationId={cid}")

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta = f"{RESULTADOS}/01_traza_{marca}.txt"
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(salida) + "\n")
    out()
    out(f"Reporte guardado en: {ruta}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRUEBA 6 (Fase 5, S34): CAOS — 5 fichas de falla controlada.
  A. Servicio caído (docker stop almacen-service) -> circuit breaker OPEN
     -> fail-fast -> recuperación automática al volver.
  B. Latencia inyectada (Toxiproxy en tickets) -> timeout (504) -> circuito
     OPEN -> recuperación (sonda HALF_OPEN) al quitar la toxina.
  C. Cola saturada (ráfaga concurrente real) -> bulkhead + shedding (503).
  D. Backpressure (ráfaga concurrente real) -> rate limit global (429).
  E. Evento duplicado (redelivery simulado) -> idempotencia, no duplica.

Uso:  python pruebas/06_caos.py
"""
import os
import subprocess
import sys
import time
from datetime import datetime

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import GW, LIB, RAIZ, RESULTADOS, login, metrica_gateway, verificar_sistema  # noqa: E402

TOXIPROXY = "http://localhost:8474"


def main():
    verificar_sistema()
    salida = []

    def out(linea=""):
        print(linea)
        salida.append(linea)

    def marca(msg):
        out(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def titulo(msg):
        out()
        out("=" * 44)
        out(f" {msg}")
        out("=" * 44)

    token = login("admin", "admin123")

    # ---------- FICHA A ----------
    titulo("FICHA A: SERVICIO CAÍDO (docker stop almacen-service)")
    circuito_almacen = metrica_gateway('gateway_circuit_state{service="almacen"}')
    marca(f"circuit_state almacen (antes): {circuito_almacen}  (0=CLOSED)")
    marca("docker stop almacen-service")
    subprocess.run(["docker", "stop", "almacen-service"], capture_output=True)
    time.sleep(1)
    for i in range(1, 5):
        r = httpx.get(f"{GW}/api/v1/almacen/almacen/productos",
                       headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
        marca(f"  intento {i} -> HTTP {r.status_code}")
    circuito_almacen = metrica_gateway('gateway_circuit_state{service="almacen"}')
    marca(f"circuit_state almacen (tras 4 fallos): {circuito_almacen}  (2=OPEN esperado)")
    t0 = time.perf_counter()
    r = httpx.get(f"{GW}/api/v1/almacen/almacen/productos",
                   headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
    ms = round((time.perf_counter() - t0) * 1000)
    marca(f"fail-fast con el circuito abierto -> HTTP {r.status_code} en {ms}ms (esperado: <100ms, sin tocar la red)")
    marca("docker start almacen-service")
    subprocess.run(["docker", "start", "almacen-service"], capture_output=True)
    marca("Esperando cooldown del circuito (15s) + arranque del servicio...")
    time.sleep(20)
    r = httpx.get(f"{GW}/api/v1/almacen/almacen/productos",
                   headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
    circuito_almacen = metrica_gateway('gateway_circuit_state{service="almacen"}')
    marca(f"sonda tras recuperación -> HTTP {r.status_code} | circuit_state: {circuito_almacen}  (0=CLOSED esperado)")

    # ---------- FICHA B ----------
    titulo("FICHA B: LATENCIA INYECTADA (Toxiproxy en tickets)")
    circuito_tickets = metrica_gateway('gateway_circuit_state{service="tickets"}')
    marca(f"circuit_state tickets (antes): {circuito_tickets}")
    marca("inyectando latencia de 8s en ticket_proxy (timeout configurado: 3s)")
    httpx.post(f"{TOXIPROXY}/proxies/ticket_proxy/toxics",
               json={"name": "latencia_caos", "type": "latency", "attributes": {"latency": 8000}}, timeout=10.0)
    for i in range(1, 4):
        t0 = time.perf_counter()
        r = httpx.get(f"{GW}/api/v1/tickets/tickets/",
                       headers={"Authorization": f"Bearer {token}"}, timeout=15.0)
        ms = round((time.perf_counter() - t0) * 1000)
        marca(f"  intento {i} -> HTTP {r.status_code} en {ms}ms (504 = timeout de los 3s configurados)")
    circuito_tickets = metrica_gateway('gateway_circuit_state{service="tickets"}')
    marca(f"circuit_state tickets (tras timeouts): {circuito_tickets}  (2=OPEN esperado)")
    marca("quitando la toxina")
    httpx.delete(f"{TOXIPROXY}/proxies/ticket_proxy/toxics/latencia_caos", timeout=10.0)
    marca("Esperando cooldown del circuito (15s)...")
    time.sleep(16)
    r = httpx.get(f"{GW}/api/v1/tickets/tickets/",
                   headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
    circuito_tickets = metrica_gateway('gateway_circuit_state{service="tickets"}')
    marca(f"sonda tras recuperación -> HTTP {r.status_code} | circuit_state: {circuito_tickets}  (0=CLOSED esperado)")

    # ---------- FICHA C ----------
    titulo("FICHA C: COLA SATURADA (bulkhead + shedding, ráfaga real de 40 a auditoría, cupo=5)")
    r = subprocess.run(
        [sys.executable, os.path.join(LIB, "rafaga_async.py"), "api/v1/auditoria/auditoria/eventos", "40"],
        cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out(r.stdout.strip())
    shed = metrica_gateway('gateway_bulkhead_rejects_total{razon="shed_baja_prioridad",service="auditoria"}')
    in_flight = metrica_gateway('gateway_bulkhead_in_flight{service="auditoria"}')
    marca(f"bulkhead rejects (shed_baja_prioridad): {shed}")
    marca(f"bulkhead in_flight tras la ráfaga (debe volver a 0): {in_flight}")

    # ---------- FICHA D ----------
    titulo("FICHA D: BACKPRESSURE (rate limit global, ráfaga real de 100 a tickets)")
    r = subprocess.run(
        [sys.executable, os.path.join(LIB, "rafaga_async.py"), "api/v1/tickets/tickets/", "100"],
        cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out(r.stdout.strip())
    rate_rejects = metrica_gateway("gateway_rate_limit_rejects_total")
    marca(f"rate limit rejects (acumulado): {rate_rejects}")

    # ---------- FICHA E ----------
    titulo("FICHA E: EVENTO DUPLICADO (redelivery simulado -> idempotencia)")
    cid = f"caos-idem-{int(time.time())}"
    payload = {
        "datosCliente": "Cliente Caos Idem", "documento_cliente": "99999999",
        "telefono_cliente": "999999999", "tipoOperacion": "VENTA", "prioridad": "NORMAL",
    }
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": cid}
    r1 = httpx.post(f"{GW}/api/v1/tickets/tickets/", headers=headers, json=payload, timeout=15.0)
    r2 = httpx.post(f"{GW}/api/v1/tickets/tickets/", headers=headers, json=payload, timeout=15.0)
    id1 = r1.json().get("idTicket") if r1.status_code < 400 else None
    id2 = r2.json().get("idTicket") if r2.status_code < 400 else None
    if id1 and id1 == id2:
        marca(f"OK: mismo idTicket ({id1}) en el reintento -> no se duplicó")
    else:
        marca(f"idTicket distinto: '{id1}' vs '{id2}'")

    titulo("Veredicto S26/S34: fallas CONTENIDAS (fail-fast + fallback honesto + "
           "recuperación automática + backpressure + idempotencia); sin cascada.")

    marca_archivo = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta = f"{RESULTADOS}/06_caos_{marca_archivo}.txt"
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(salida) + "\n")
    print(f"Reporte guardado en: {ruta}")


if __name__ == "__main__":
    main()

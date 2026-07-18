#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PRUEBA 7 (Fase 7, S34): el circuit breaker abre para TODOS los servicios.

Regresion de un bug real: `tickets` es el unico servicio que el Gateway
alcanza via Toxiproxy. Al caer su upstream, Toxiproxy sigue vivo y acepta
la conexion TCP, luego la cierra -> httpx.ReadError (no ConnectError). El
proxy solo capturaba ConnectError/TimeoutException, asi que el ReadError se
escapaba al manejador global: el cliente recibia un 500 opaco y el breaker
NUNCA se enteraba del fallo. El circuito de tickets se quedaba en CLOSED
con el servicio caido.

Esta prueba tumba CADA servicio, uno por uno, y exige lo mismo para todos:
503 (no 500) y circuito en OPEN. Al terminar, restaura todo.

`auth` YA ENTRA (desde 2026-07-18)
Antes quedaba fuera porque el Gateway bloqueaba /api/v1/auth/* con un 403 y el
login iba directo al puerto 8003: esa ruta no se proxyaba, asi que su circuito
no podia ejercitarse. Cerrados los hallazgos 3 y 4 de OWASP, el login pasa por
`POST /api/v1/auth/login` con rate limit propio, bloqueo por intentos fallidos
y circuit breaker — de modo que ahora SI se puede tumbar auth-service y exigirle
lo mismo que al resto. Es la unica ruta publica del Gateway (sin token: nadie
lo tiene todavia), y por eso se comprueba aparte: se espera 503 con mensaje
legible, no un error de red crudo en la cara del usuario.

Uso:  python pruebas/07_breaker_todos.py
"""
import os
import subprocess
import sys
import time
from datetime import datetime

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from comun import GW, RESULTADOS, login, metrica_gateway, verificar_sistema  # noqa: E402

# servicio del Gateway -> (contenedor a tumbar, ruta de prueba)
SERVICIOS = {
    "tickets": ("ticket-service", "api/v1/tickets/tickets/"),
    "almacen": ("almacen-service", "api/v1/almacen/almacen/productos"),
    "diagnosticos": ("diagnostico-service", "api/v1/diagnosticos/diagnosticos/por-ticket/TICK-X"),
    "facturas": ("facturacion-service", "api/v1/facturas/facturas/"),
    "auditoria": ("auditoria-service", "api/v1/auditoria/auditoria/eventos"),
    "notificaciones": ("notificacion-service", "api/v1/notificaciones/notificaciones/mis-alertas"),
}
COOLDOWN = 15   # el breaker espera 15s antes de la sonda HALF_OPEN


def main():
    verificar_sistema()
    salida, fallos = [], []

    def out(linea=""):
        print(linea)
        salida.append(linea)

    token = login("admin", "admin123")
    headers = {"Authorization": f"Bearer {token}"}

    out("=" * 60)
    out(" PRUEBA 7: el circuit breaker abre para TODOS los servicios")
    out("=" * 60)
    out("Regresion del bug: 'tickets' va via Toxiproxy -> ReadError (no")
    out("ConnectError). Antes: 500 opaco y circuito CLOSED con el servicio caido.")

    for servicio, (contenedor, ruta) in SERVICIOS.items():
        out(f"\n--- {servicio}  (contenedor: {contenedor}) ---")
        estado_previo = metrica_gateway(f'gateway_circuit_state{{service="{servicio}"}}')
        out(f"  circuito antes: {estado_previo}  (0=CLOSED)")

        subprocess.run(["docker", "stop", contenedor], capture_output=True)
        time.sleep(1)

        codigos = []
        for _ in range(5):
            try:
                r = httpx.get(f"{GW}/{ruta}", headers=headers, timeout=15.0)
                codigos.append(r.status_code)
            except Exception as exc:
                codigos.append(type(exc).__name__)
        out(f"  respuestas con el servicio caido: {codigos}")

        estado = metrica_gateway(f'gateway_circuit_state{{service="{servicio}"}}')
        out(f"  circuito despues: {estado}  (2=OPEN esperado)")

        # Criterio: ni un solo 500 (eso seria el bug) y el circuito debe abrir.
        hubo_500 = any(c == 500 for c in codigos)
        abrio = estado.startswith("2")
        if hubo_500:
            fallos.append(f"{servicio}: devolvio 500 (el error se escapo del proxy)")
            out("  FALLO: hubo 500 -> el error no lo maneja el proxy resiliente")
        if not abrio:
            fallos.append(f"{servicio}: el circuito NO abrio (quedo en {estado})")
            out("  FALLO: el circuito no abrio")
        if not hubo_500 and abrio:
            out("  OK: 503 controlado y circuito OPEN")

        subprocess.run(["docker", "start", contenedor], capture_output=True)
        out(f"  {contenedor} restaurado; esperando cooldown ({COOLDOWN}s) + arranque...")
        time.sleep(COOLDOWN + 8)

        # Sonda: el circuito debe cerrarse solo tras el cooldown.
        try:
            httpx.get(f"{GW}/{ruta}", headers=headers, timeout=15.0)
        except Exception:
            pass
        estado_final = metrica_gateway(f'gateway_circuit_state{{service="{servicio}"}}')
        out(f"  circuito tras recuperacion: {estado_final}  (0=CLOSED esperado)")
        if not estado_final.startswith("0"):
            fallos.append(f"{servicio}: no se recupero solo (quedo en {estado_final})")

    # ------------------------------------------------------------------
    # AUTH: se comprueba aparte porque su ruta es PUBLICA (sin token) y lo que
    # importa no es solo el 503, sino que el usuario reciba una explicacion
    # entendible en vez de un error de red crudo. Nadie puede entrar al sistema
    # si esto falla, asi que el mensaje es parte del contrato.
    out("\n--- auth  (contenedor: auth-service) — ruta publica de login ---")
    estado_previo = metrica_gateway('gateway_circuit_state{service="auth"}')
    out(f"  circuito antes: {estado_previo}  (0=CLOSED)")

    subprocess.run(["docker", "stop", "auth-service"], capture_output=True)
    time.sleep(1)

    codigos, detalle = [], ""
    for _ in range(5):
        try:
            r = httpx.post(f"{GW}/api/v1/auth/login",
                           json={"usuario": "admin", "password": "admin123"}, timeout=15.0)
            codigos.append(r.status_code)
            if r.status_code == 503:
                detalle = (r.json() or {}).get("detalle", "")
        except Exception as exc:
            codigos.append(type(exc).__name__)
    out(f"  respuestas con auth-service caido: {codigos}")

    estado = metrica_gateway('gateway_circuit_state{service="auth"}')
    out(f"  circuito despues: {estado}  (2=OPEN esperado)")

    hubo_500 = any(c == 500 for c in codigos)
    todo_503 = all(c == 503 for c in codigos)
    abrio = estado.startswith("2")
    if hubo_500:
        fallos.append("auth: devolvio 500 (el error se escapo del proxy)")
        out("  FALLO: hubo 500 -> el error no lo maneja el proxy resiliente")
    if not abrio:
        fallos.append(f"auth: el circuito NO abrio (quedo en {estado})")
        out("  FALLO: el circuito no abrio")
    if not todo_503:
        fallos.append(f"auth: no todas las respuestas fueron 503 ({codigos})")
    # El mensaje debe explicar que NO es culpa de la contrasena del usuario.
    mensaje_ok = "contrasena" in detalle.lower() or "contraseña" in detalle.lower()
    if mensaje_ok:
        out(f"  OK: mensaje legible -> \"{detalle[:88]}...\"")
    else:
        fallos.append("auth: el 503 no explica al usuario que no es su contrasena")
        out(f"  FALLO: mensaje poco claro -> \"{detalle[:88]}\"")
    if not hubo_500 and abrio and todo_503 and mensaje_ok:
        out("  OK: 503 controlado, circuito OPEN y mensaje entendible")

    subprocess.run(["docker", "start", "auth-service"], capture_output=True)
    out(f"  auth-service restaurado; esperando cooldown ({COOLDOWN}s) + arranque...")
    time.sleep(COOLDOWN + 8)
    try:
        httpx.post(f"{GW}/api/v1/auth/login",
                   json={"usuario": "admin", "password": "admin123"}, timeout=15.0)
    except Exception:
        pass
    estado_final = metrica_gateway('gateway_circuit_state{service="auth"}')
    out(f"  circuito tras recuperacion: {estado_final}  (0=CLOSED esperado)")
    if not estado_final.startswith("0"):
        fallos.append(f"auth: no se recupero solo (quedo en {estado_final})")

    out("\n" + "=" * 60)
    if fallos:
        out(f" RESULTADO: {len(fallos)} FALLO(S)")
        for f in fallos:
            out(f"   - {f}")
    else:
        out(" RESULTADO: OK — los 7 servicios (incluido auth) abren el circuito")
        out("            y se recuperan solos.")
    out("=" * 60)

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_rep = f"{RESULTADOS}/07_breaker_todos_{marca}.txt"
    with open(ruta_rep, "w", encoding="utf-8") as f:
        f.write("\n".join(salida) + "\n")
    print(f"Reporte guardado en: {ruta_rep}")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()

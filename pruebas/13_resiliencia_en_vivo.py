#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""RESILIENCIA EN VIVO — 4 demos cortas, para enseñar en la sustentación.

Cada demo dura menos de un minuto, dice EN CONSOLA qué servicio está tocando y
en qué panel de Grafana se ve, e imprime los logs REALES del Gateway que lo
prueban. Está pensada para proyectarla mientras se explica.

  1. SONDA ACTIVA — se corta 'almacen', el circuito se abre, se restaura la
     conectividad y NADIE toca el circuito: la sonda lo cierra sola.
  2. TIMEOUT + RETRY — se mete latencia con una toxina de Toxiproxy; el Gateway
     agota su timeout y reintenta.
  3. BULKHEAD — se lanzan más llamadas concurrentes que huecos tiene el
     mamparo, y las que sobran se rechazan sin tumbar al servicio.
  4. AUTO-HEALING DE PROCESO — se mata un worker de uvicorn y el maestro lo
     respawnea; el servicio NUNCA deja de responder.

Uso:
    python pruebas/13_resiliencia_en_vivo.py            # las cuatro
    python pruebas/13_resiliencia_en_vivo.py --demo 1   # solo una
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, "reconfigure"):
        _f.reconfigure(encoding="utf-8", errors="replace")

GW = "http://localhost:8000"
TOXI = "http://localhost:8474"
PROXY = {"almacen": "almacen_proxy", "tickets": "ticket_proxy",
         "facturas": "factura_proxy", "diagnosticos": "diagnostico_proxy"}
ESTADOS = {0: "CLOSED", 1: "HALF_OPEN", 2: "OPEN"}


def pedir(url, metodo="GET", cuerpo=None, token=None, timeout=20):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cab = {"Content-Type": "application/json"}
    if token:
        cab["Authorization"] = f"Bearer {token}"
    pet = urllib.request.Request(url, data=datos, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(pet, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def login():
    _, cuerpo = pedir(f"{GW}/api/v1/auth/login", "POST",
                      {"usuario": "admin", "password": "admin123"})
    try:
        return json.loads(cuerpo).get("access_token", "")
    except Exception:
        return ""


def proxy(nombre, habilitado):
    pedir(f"{TOXI}/proxies/{nombre}", "POST", {"enabled": habilitado})


def toxina(nombre_proxy, latencia_ms):
    """Añade latencia en el proxy. Devuelve el nombre para poder quitarla."""
    pedir(f"{TOXI}/proxies/{nombre_proxy}/toxics", "POST",
          {"name": "lentitud", "type": "latency", "stream": "downstream",
           "attributes": {"latency": latencia_ms, "jitter": 0}})
    return "lentitud"


def quitar_toxina(nombre_proxy, nombre="lentitud"):
    pedir(f"{TOXI}/proxies/{nombre_proxy}/toxics/{nombre}", "DELETE")


def circuito(servicio):
    _, texto = pedir(f"{GW}/metrics")
    for linea in texto.splitlines():
        if linea.startswith(f'gateway_circuit_state{{service="{servicio}"}}'):
            return ESTADOS.get(int(float(linea.rsplit(" ", 1)[-1])), "?")
    return "?"


def logs(patron, segundos=90, cuantos=6):
    """Los logs REALES del Gateway que prueban lo que se acaba de ver."""
    r = subprocess.run(["docker", "logs", "api-gateway", "--since", f"{segundos}s"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    salida = []
    for linea in (r.stdout + r.stderr).splitlines():
        if patron.lower() in linea.lower():
            try:
                d = json.loads(linea)
                salida.append(f"    [{d.get('level','')}] {d.get('message','')[:130]}")
            except Exception:
                salida.append(f"    {linea[:130]}")
    if not salida:
        print("    (sin logs que casen; mira `docker logs api-gateway`)")
    for l in salida[-cuantos:]:
        print(l)


def titulo(n, texto, panel):
    print("\n" + "=" * 72)
    print(f" DEMO {n}: {texto}")
    print("=" * 72)
    print(f" En Grafana: {panel}")


# ----------------------------------------------------------------------
def demo1(token):
    titulo(1, "SONDA ACTIVA — el circuito se cierra SOLO",
           "panel 'Estado del circuito por servicio'")
    print(" Servicio comprometido: ALMACEN (se corta su proxy en Toxiproxy)\n")

    print(f"  estado inicial ............ {circuito('almacen')}")
    print("  cortando la conectividad de 'almacen'...")
    proxy(PROXY["almacen"], False)

    for _ in range(8):
        pedir(f"{GW}/api/v1/almacen/almacen/inventario", token=token, timeout=8)
    time.sleep(3)
    print(f"  tras unos fallos .......... {circuito('almacen')}  <-- fail-fast")

    codigo, _ = pedir(f"{GW}/api/v1/almacen/almacen/inventario", token=token, timeout=8)
    print(f"  una peticion mas .......... HTTP {codigo}  (503 con contrato, NO un 500)")
    print(f"  'tickets' mientras tanto .. {circuito('tickets')}  <-- sin cascada")

    print("\n  restauro la conectividad y NO toco el circuito.")
    print("  A partir de aqui nadie interviene: la sonda va sola cada 5s.")
    proxy(PROXY["almacen"], True)

    t0 = time.monotonic()
    while time.monotonic() - t0 < 90:
        if circuito("almacen") == "CLOSED":
            print(f"\n  >>> el circuito se CERRO SOLO en {time.monotonic()-t0:.0f}s <<<")
            break
        time.sleep(2)
    else:
        print("\n  el circuito NO se cerro en 90s — revisar la sonda")

    print("\n  Los logs del Gateway que lo prueban:")
    logs("circuit_breaker", 180)


def demo2(token):
    titulo(2, "TIMEOUT + RETRY — la dependencia se vuelve LENTA",
           "paneles 'Timeouts (/s)' y 'Reintentos (/s)'")
    print(" Servicio comprometido: FACTURAS (latencia de 9s inyectada)\n")

    print("  metiendo 9s de latencia en el proxy de 'facturas'...")
    toxina(PROXY["facturas"], 9000)
    time.sleep(1)

    t0 = time.monotonic()
    codigo, _ = pedir(f"{GW}/api/v1/facturas/facturas/", token=token, timeout=40)
    print(f"  respuesta ................. HTTP {codigo} en {time.monotonic()-t0:.1f}s")
    print("  (el Gateway corta por timeout y reintenta con backoff en vez de")
    print("   quedarse colgado esperando indefinidamente)")

    quitar_toxina(PROXY["facturas"])
    print("  latencia retirada.")
    print("\n  Los logs del Gateway:")
    logs("timeout", 90)
    logs("reintent", 90, 3)


def demo3(token):
    titulo(3, "BULKHEAD — mas llamadas concurrentes que huecos",
           "paneles 'Bulkhead: llamadas en vuelo' y 'rechazos (/s) por razon'")
    print(" Servicio comprometido: DIAGNOSTICOS (lento + 40 llamadas a la vez)\n")

    toxina(PROXY["diagnosticos"], 3000)
    time.sleep(1)
    print("  lanzando 40 peticiones simultaneas...")

    def una(_):
        c, _cuerpo = pedir(f"{GW}/api/v1/diagnosticos/diagnosticos/", token=token, timeout=30)
        return c

    with ThreadPoolExecutor(max_workers=40) as ex:
        codigos = list(ex.map(una, range(40)))

    quitar_toxina(PROXY["diagnosticos"])
    resumen = {}
    for c in codigos:
        resumen[c] = resumen.get(c, 0) + 1
    print(f"  respuestas ................ {resumen}")
    print("  Las 503 son el mamparo rechazando lo que no cabe: prefiere decir")
    print("  'ahora no' a aceptarlo todo y tumbar el servicio (y con el, a los")
    print("  demas que comparten el Gateway).")
    print("\n  Los logs del Gateway:")
    logs("bulkhead", 90)


def demo4(token):
    titulo(4, "AUTO-HEALING DE PROCESO — muere un worker y vuelve solo",
           "ninguno: almacen no esta en el panel de CPU (solo salen los "
           "servicios instrumentados). La evidencia son los logs de abajo.")
    print(" Servicio comprometido: ALMACEN (se mata 1 de sus 4 workers)\n")
    print("  OJO, se honesto en la exposicion: esto NO tumba el contenedor.")
    print("  Estos servicios corren con `uvicorn --workers 4`. Se mata el worker")
    print("  que atiende la peticion; el maestro lo respawnea en ~1s y los otros")
    print("  3 siguen sirviendo, asi que el servicio nunca deja de responder.")
    print("  Eso es auto-healing a nivel de PROCESO, y es real.\n")

    codigo, _ = pedir("http://localhost:8002/_chaos/crash", "POST", timeout=8)
    print(f"  crash provocado ........... HTTP {codigo}")

    caidas = 0
    for i in range(12):
        c, _cuerpo = pedir("http://localhost:8002/health", timeout=5)
        if c != 200:
            caidas += 1
        time.sleep(0.5)
    print(f"  12 sondeos en 6s .......... {12 - caidas} OK, {caidas} fallidos")
    if caidas == 0:
        print("  >>> el servicio NUNCA dejo de responder: el maestro respawneo <<<")
        print("  >>> el worker muerto sin que se notara desde fuera.          <<<")
    else:
        print("  (hubo un hueco: el worker muerto atendia parte del trafico)")

    print("\n  El log del propio servicio:")
    r = subprocess.run(["docker", "logs", "almacen-service", "--since", "60s"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    for linea in (r.stdout + r.stderr).splitlines():
        if "CHAOS" in linea or "Started server process" in linea:
            print(f"    {linea[:130]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", type=int, choices=[1, 2, 3, 4],
                    help="Correr solo una (por defecto: las cuatro)")
    args = ap.parse_args()

    token = login()
    if not token:
        print("No se pudo iniciar sesion. Esta todo levantado? (docker compose ps)")
        sys.exit(1)

    demos = {1: demo1, 2: demo2, 3: demo3, 4: demo4}
    elegidas = [args.demo] if args.demo else [1, 2, 3, 4]
    try:
        for n in elegidas:
            demos[n](token)
    finally:
        # Pase lo que pase: ni un proxy cortado ni una toxina viva.
        for nombre in PROXY.values():
            quitar_toxina(nombre)
            proxy(nombre, True)

    print("\n" + "=" * 72)
    print(" Todo restaurado. Para ver los logs completos de cualquier servicio:")
    print("   docker logs api-gateway --since 10m")
    print("   docker logs almacen-service --since 10m")
    print(" Y en Grafana (http://localhost:3000) los paneles citados arriba.")
    print("=" * 72)


if __name__ == "__main__":
    main()

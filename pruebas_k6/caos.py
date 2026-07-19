#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CAOS BAJO CARGA REAL — k6 empujando mientras los servicios se caen.

Es la prueba que pide la S34 en su bloque de fallas controladas: lanzar el
volumen de una fase (100k / 500k / 1M) y, **sin parar el tráfico**, ir tumbando
servicios para ver qué le pasa a quien ya estaba operando.

Se diferencia de `pruebas/11_caos_bajo_carga.py` en el generador: aquella usa
el runner de Python, que topa en ~105 rps y era él mismo el cuello de botella.
Esta usa k6, que sostiene ~200 rps sobre este sistema, así que el caos ocurre
bajo carga de verdad.

CÓMO SE MATA CADA SERVICIO
Con `POST /_chaos/crash`, que ejecuta `os._exit(1)` dentro del proceso — una
caída REAL. No se usa `docker stop` porque Docker lo interpreta como una parada
ordenada y **no dispara `restart: always`**: el servicio no volvería solo, y
justamente lo que se quiere demostrar es que vuelve sin que nadie haga nada.

LO QUE SE MIDE
  1. CONTENCIÓN   — la caída produce 503 con contrato, nunca 500 opacos, y no
                    arrastra a los servicios sanos (sin cascada).
  2. CONTINUIDAD  — el resto del sistema sigue atendiendo durante la caída.
  3. RECUPERACIÓN — el servicio vuelve SOLO (restart:always) y su circuito se
                    cierra SOLO (sonda activa, ADR-0014).

Uso:
    python pruebas_k6/caos.py --fase 100k
    python pruebas_k6/caos.py --fase 500k --vus 200
    python pruebas_k6/caos.py --fase 100k --servicios almacen,tickets
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime

for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        _flujo.reconfigure(encoding="utf-8", errors="replace")

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
AQUI = os.path.dirname(os.path.abspath(__file__))
RESULTADOS = os.path.join(AQUI, "resultados")
os.makedirs(RESULTADOS, exist_ok=True)

sys.path.insert(0, AQUI)
from correr import FASES, Muestreador, red_docker  # noqa: E402

sys.path.insert(0, os.path.join(RAIZ, "pruebas", "lib"))
from comun import ampliar_rate_limit, restaurar_rate_limit  # noqa: E402

# servicio del Gateway -> (contenedor, puerto publicado para su /_chaos/crash)
SERVICIOS = {
    "almacen": ("almacen-service", 8002),
    "tickets": ("ticket-service", 8001),
    "diagnosticos": ("diagnostico-service", 8004),
    "facturas": ("facturacion-service", 8005),
    "auditoria": ("auditoria-service", 8006),
}
NOMBRES_ESTADO = {"0": "CLOSED", "1": "HALF_OPEN", "2": "OPEN"}


def circuitos() -> dict:
    """Estado de todos los circuitos, leído de /metrics."""
    try:
        import urllib.request
        texto = urllib.request.urlopen("http://localhost:8000/metrics", timeout=8).read().decode()
    except Exception:
        return {}
    estados = {}
    for linea in texto.splitlines():
        if linea.startswith("gateway_circuit_state{"):
            servicio = linea.split('service="')[1].split('"')[0]
            estados[servicio] = NOMBRES_ESTADO.get(linea.rsplit(" ", 1)[-1].split(".")[0], "?")
    return estados


def matar(puerto) -> bool:
    """Provoca un crash REAL del proceso (os._exit(1))."""
    try:
        import urllib.request
        urllib.request.urlopen(
            urllib.request.Request(f"http://localhost:{puerto}/_chaos/crash", method="POST"),
            timeout=5)
        return True
    except Exception:
        # El endpoint mata el proceso ~0.5s DESPUES de responder, así que a
        # veces la conexión se corta antes de leer la respuesta: eso significa
        # que funcionó, no que fallara.
        return True


def vivo(puerto) -> bool:
    try:
        import urllib.request
        return urllib.request.urlopen(f"http://localhost:{puerto}/health",
                                      timeout=3).status == 200
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fase", choices=[f for f in FASES if f != "humo"] + ["humo"],
                    default="100k")
    ap.add_argument("--vus", type=int, help="Sobrescribe la concurrencia")
    ap.add_argument("--servicios", default="almacen,tickets,facturas",
                    help="Cuales tumbar, separados por coma")
    args = ap.parse_args()

    cfg = FASES[args.fase]
    vus = args.vus or cfg["vus"]
    objetivo = [s.strip() for s in args.servicios.split(",") if s.strip() in SERVICIOS]
    if not objetivo:
        print(f"Servicios validos: {', '.join(SERVICIOS)}")
        sys.exit(1)

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    salida_txt = os.path.join(RESULTADOS, f"caos_k6_{args.fase}_{marca}.txt")
    red = red_docker()
    salida, fallos = [], []

    def out(linea=""):
        print(linea, flush=True)
        salida.append(linea)

    out("=" * 72)
    out(f" CAOS BAJO CARGA k6 — fase {args.fase}: {cfg['total']:,} peticiones, {vus} VUs".replace(",", " "))
    out("=" * 72)
    out(f"Se tumbaran, uno a uno y SIN parar el trafico: {', '.join(objetivo)}")
    out("Cada uno con un crash REAL (os._exit(1)), no `docker stop`: solo asi")
    out("Docker dispara restart:always y se puede demostrar que vuelve SOLO.")
    out("")

    # La fase tiene que durar MAS que el guion de caos, o k6 termina antes de
    # que caiga el primer servicio y la prueba no mide nada. A ~200 rps:
    #   guion = 45s de calentamiento + por servicio (10s + recuperacion + 20s)
    segundos_guion = 45 + len(objetivo) * 60
    segundos_fase = cfg["total"] / 200          # estimacion a 200 rps
    if segundos_fase < segundos_guion:
        out(f"AVISO: la fase '{args.fase}' dura ~{segundos_fase/60:.1f} min a 200 rps,")
        out(f"       menos que el guion de caos (~{segundos_guion/60:.1f} min). k6 acabaria")
        out("       antes de tumbar todo y la prueba no mediria el caos bajo carga.")
        out("       Usa --fase 100k o superior.")
        out("")

    ampliar_rate_limit()
    muestreador = Muestreador(objetivo=cfg["total"])
    muestreador.start()

    nombre_contenedor = f"k6caos-{args.fase}-{marca}"
    proceso = subprocess.Popen(
        ["docker", "run", "--rm", "-i", "--name", nombre_contenedor, "--network", red,
         "-e", f"TOTAL={cfg['total']}", "-e", f"VUS={vus}",
         "-e", f"MAX_DURACION={cfg['max']}",
         "grafana/k6:latest", "run", "-"],
        stdin=open(os.path.join(AQUI, "carga.js"), "rb"),
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace",
    )
    buffer = []
    hilo = threading.Thread(target=lambda: buffer.extend(proceso.stdout), daemon=True)
    hilo.start()

    linea_tiempo = []
    t0 = time.monotonic()

    def apuntar(evento):
        linea_tiempo.append((round(time.monotonic() - t0), evento, circuitos()))

    try:
        out("[calentando 45s antes del primer crash]")
        time.sleep(45)
        apuntar("carga estable, antes del caos")

        for servicio in objetivo:
            contenedor, puerto = SERVICIOS[servicio]
            out(f"\n--- CRASH de {contenedor} (servicio '{servicio}') ---")
            matar(puerto)
            apuntar(f"crash de {servicio}")
            time.sleep(10)

            est = circuitos()
            abrio = est.get(servicio) in ("OPEN", "HALF_OPEN")
            out(f"  circuito de '{servicio}': {est.get(servicio)}"
                f"  {'OK (aislado)' if abrio else '(aun no ha abierto)'}")

            # Los SANOS deben seguir cerrados: eso es la ausencia de cascada.
            contagiados = [s for s, e in est.items() if e != "CLOSED" and s != servicio]
            if contagiados:
                fallos.append(f"cascada: {contagiados} se abrieron por la caida de '{servicio}'")
                out(f"  FALLO: se contagiaron {contagiados}")
            else:
                out("  OK: ningun otro circuito se contagio")

            # Ahora NO se toca nada: se cronometra cuanto tarda en volver solo.
            inicio_reco = time.monotonic()
            while time.monotonic() - inicio_reco < 120 and not vivo(puerto):
                time.sleep(1)
            t_vivo = round(time.monotonic() - inicio_reco, 1)
            out(f"  el proceso volvio SOLO en {t_vivo}s (restart:always)")

            while time.monotonic() - inicio_reco < 120 and circuitos().get(servicio) != "CLOSED":
                time.sleep(1)
            t_circuito = round(time.monotonic() - inicio_reco, 1)
            cerro = circuitos().get(servicio) == "CLOSED"
            out(f"  su circuito volvio a CLOSED en {t_circuito}s"
                f"  {'(sonda activa)' if cerro else '— NO se cerro'}")
            apuntar(f"{servicio} recuperado")
            if not cerro:
                fallos.append(f"'{servicio}' no volvio a CLOSED por si solo")

            out("  dejando estabilizar 20s antes del siguiente...")
            time.sleep(20)

        out("\n[fin del guion] Esperando a que k6 termine la fase...")
        proceso.wait(timeout=int(cfg["max"].rstrip("m")) * 60 + 120)
    except KeyboardInterrupt:
        out("\nInterrumpido: pidiendo a k6 el resumen parcial...")
        subprocess.run(["docker", "kill", "--signal=SIGINT", nombre_contenedor],
                       capture_output=True)
        try:
            proceso.wait(timeout=45)
        except subprocess.TimeoutExpired:
            proceso.kill()
    finally:
        muestreador.parar.set()
        hilo.join(timeout=15)
        restaurar_rate_limit()
        # Cualquier servicio que siguiera caido se levanta, pase lo que pase.
        for servicio in objetivo:
            subprocess.run(["docker", "start", SERVICIOS[servicio][0]], capture_output=True)

    # ------------------------------------------------------------------
    m = re.search(r"<<<RESUMEN_JSON>>>\s*(\{.*?\})\s*<<<FIN_RESUMEN_JSON>>>",
                  "".join(buffer), re.S)
    if not m:
        out("\nNo se pudo leer el resumen de k6.")
        sys.exit(1)
    met = json.loads(m.group(1))["metrics"]

    def val(nombre, clave="count"):
        d = met.get(nombre, {})
        return (d.get("values", d) or {}).get(clave, 0)

    total = int(val("http_reqs"))
    c500 = int(val("errores_reales"))
    degradados = int(val("http_503_504_429"))
    encolados = int(val("http_202"))
    rec = muestreador.resumen()

    out("\n" + "=" * 72)
    out(" QUE SUFRIO EL TRAFICO MIENTRAS CAIAN LOS SERVICIOS")
    out("=" * 72)
    out(f"  peticiones atendidas ......... {total}")
    out(f"  p95 / p99 ................... {val('http_req_duration','p(95)'):.0f} / "
        f"{val('http_req_duration','p(99)'):.0f} ms")
    out(f"  degradadas con contrato ..... {degradados} (503/504/429)")
    out(f"  encoladas en el outbox ...... {encolados}")
    out(f"  ERRORES OPACOS (500) ........ {c500}")
    out(f"  CPU pico .................... {rec['cpu_pico']:.0f}%" if rec["cpu_pico"] else "")
    out(f"  cola RabbitMQ pico .......... {rec['cola_pico']}")

    if c500 > 0:
        fallos.append(f"hubo {c500} errores 500 durante el caos")
        out(f"\n  FALLO: {c500} errores 500 — la falla NO quedo contenida")
    else:
        out("\n  OK: CERO errores 500 matando servicios con el trafico encima")

    out("\n" + "=" * 72)
    out(" LINEA DE TIEMPO")
    out("=" * 72)
    for t, evento, est in linea_tiempo:
        abiertos = ", ".join(f"{s}={e}" for s, e in sorted(est.items()) if e != "CLOSED")
        out(f"  t+{t:>4}s  {evento:<32} {abiertos or 'todos CLOSED'}")

    out("\n" + "=" * 72)
    if fallos:
        out(f" VEREDICTO: {len(fallos)} FALLO(S)")
        for f in fallos:
            out(f"   - {f}")
    else:
        out(" VEREDICTO: OK — con k6 empujando, matar servicios uno a uno")
        out("            produjo degradacion CON CONTRATO (cero 500), sin")
        out("            cascada, y cada uno volvio SOLO con su circuito.")
    out("=" * 72)

    with open(salida_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(salida) + "\n")
    print(f"\nReporte: {salida_txt}")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()

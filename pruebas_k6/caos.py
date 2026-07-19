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

CÓMO SE TUMBA CADA SERVICIO: TOXIPROXY
El Gateway no habla directo con estos servicios, sino a través de Toxiproxy
(ver `toxiproxy/toxiproxy.json` y el mapa MICROSERVICIOS del Gateway). Para
tumbar uno se DESHABILITA su proxy por la API de control (:8474): el Gateway
deja de poder conectar al instante, igual que si el servicio hubiera muerto,
pero sin tocar contenedores. Eso lo hace reversible, inmediato y repetible —
que es justo lo que se quiere de una prueba de caos.

Se descartaron las otras vías, midiendo:

  - `POST /_chaos/crash` mata UN worker de los 4 (`uvicorn --workers 4`), el
    maestro lo respawnea y los otros 3 siguen atendiendo: el servicio nunca cae
    y el circuito ni se entera. Se comprobó: `/health` seguía dando 200.
  - `docker stop` sí tumba el servicio, pero tarda segundos en parar y en
    volver, y deja al contenedor fuera de su ciclo normal.
  - Matar el PID 1 desde dentro no funciona: `os.kill(1, SIGKILL)` devuelve 0
    pero el contenedor sigue con `RestartCount=0`, porque el kernel descarta
    las señales al PID 1 dentro de su propio namespace.
  - `docker kill` desde fuera tampoco revive: Docker lo trata como parada
    pedida por el usuario y NO aplica `restart: always` (quedó `Exited (137)`).

SÉ HONESTO EN LA SUSTENTACIÓN con qué se recupera solo y qué no:
  - La CONECTIVIDAD la restaura esta prueba (rehabilita el proxy), igual que en
    la vida real la restauraría el equipo de infra al arreglar la caída.
  - El CIRCUITO sí vuelve a CLOSED por sí mismo, por la sonda activa
    (ADR-0014), sin que nadie lo toque: eso es lo que se cronometra abajo, y es
    la propiedad que se está demostrando.

LO QUE SE MIDE
  1. CONTENCIÓN   — la caída produce 503 con contrato, nunca 500 opacos, y no
                    arrastra a los servicios sanos (sin cascada).
  2. CONTINUIDAD  — el resto del sistema sigue atendiendo durante la caída.
  3. RECUPERACIÓN — restaurada la conectividad, el circuito se cierra SOLO por
                    la sonda activa (ADR-0014), sin intervención.

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

# servicio del Gateway -> (proxy de Toxiproxy, puerto publicado para /health)
SERVICIOS = {
    "almacen": ("almacen_proxy", 8002),
    "tickets": ("ticket_proxy", 8001),
    "diagnosticos": ("diagnostico_proxy", 8004),
    "facturas": ("factura_proxy", 8005),
    "auditoria": ("auditoria_proxy", 8006),
    "notificaciones": ("notificacion_proxy", 8007),
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


TOXIPROXY_API = "http://localhost:8474"


def _proxy(nombre, habilitado) -> bool:
    """Habilita/deshabilita un proxy. Deshabilitado = el Gateway no conecta."""
    import urllib.request
    cuerpo = json.dumps({"enabled": habilitado}).encode()
    pet = urllib.request.Request(f"{TOXIPROXY_API}/proxies/{nombre}",
                                 data=cuerpo, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(pet, timeout=5)
        return True
    except Exception as exc:
        print(f"  (no se pudo tocar el proxy {nombre}: {exc})")
        return False


def parar(nombre_proxy) -> bool:
    return _proxy(nombre_proxy, False)


def levantar(nombre_proxy) -> bool:
    return _proxy(nombre_proxy, True)


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
    ap.add_argument("--servicios", default="almacen,tickets,facturas,diagnosticos,notificaciones,auditoria",
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
    out("Se tumban con TOXIPROXY: se deshabilita su proxy y el Gateway deja de")
    out("poder conectar al instante, sin tocar contenedores. La conectividad la")
    out("restaura la prueba; lo que se recupera SOLO es el CIRCUITO, por la")
    out("sonda activa (ADR-0014).")
    out("")

    # La fase tiene que durar MAS que el guion de caos, o k6 termina antes de
    # que caiga el primer servicio y la prueba no mide nada. A ~200 rps:
    #   guion = 45s de calentamiento + por servicio (10s + recuperacion + 20s)
    segundos_guion = 45 + len(objetivo) * 90
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
            proxy, puerto = SERVICIOS[servicio]
            out(f"\n--- CAIDA de '{servicio}' (proxy {proxy} deshabilitado) ---")
            parar(proxy)
            apuntar(f"cae {servicio}")
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

            # 30s fuera: tiempo de sobra para que el circuito abra y se vea la
            # degradacion con contrato en el trafico que sigue entrando.
            out("  servicio FUERA; dejandolo caido 30s con el trafico encima...")
            time.sleep(30)

            out(f"  restaurando la conectividad de '{servicio}'...")
            inicio_reco = time.monotonic()
            levantar(proxy)
            # Con Toxiproxy la conectividad vuelve al instante; no se mide con
            # /health directo al contenedor porque ese NUNCA cayo (el proxy es
            # quien cortaba), asi que daria 200 siempre y no probaria nada.

            # ESTO es lo automatico: nadie toca el circuito, se cierra solo.
            while time.monotonic() - inicio_reco < 120 and circuitos().get(servicio) != "CLOSED":
                time.sleep(1)
            t_circuito = round(time.monotonic() - inicio_reco, 1)
            cerro = circuitos().get(servicio) == "CLOSED"
            out(f"  su circuito volvio a CLOSED SOLO en {t_circuito}s"
                f"  {'(sonda activa, ADR-0014)' if cerro else '— NO se cerro'}")
            apuntar(f"{servicio} recuperado")
            if not cerro:
                fallos.append(f"el circuito de '{servicio}' no volvio a CLOSED por si solo")

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
        # Pase lo que pase, ningun proxy queda deshabilitado.
        for servicio in objetivo:
            levantar(SERVICIOS[servicio][0])

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
        out(" VEREDICTO: OK — con k6 empujando, tumbar servicios uno a uno")
        out("            produjo degradacion CON CONTRATO (cero 500) y sin")
        out("            cascada; al volver, cada circuito se cerro SOLO.")
    out("=" * 72)

    with open(salida_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(salida) + "\n")
    print(f"\nReporte: {salida_txt}")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()

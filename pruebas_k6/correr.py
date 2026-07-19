#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Ejecuta una carga con k6 y ESCRIBE LA FILA DE LA TABLA de registro de carga.

Cada corrida deja, además del JSON crudo de k6, la fila lista para pegar:

    | Fase | Throughput | p95 | p99 | Error rate | CPU/Mem | Queue depth | Resultado |

Las ocho columnas salen de una medición, ninguna se escribe a mano:

  - Throughput, p95, p99, error rate .... del resumen de k6
  - CPU/Mem y Queue depth .............. muestreados en paralelo durante la
                                         corrida (docker stats + rabbitmqctl)
  - Resultado .......................... redactado a partir de los códigos
                                         observados, con la regla de la S34:
                                         explicar el primer cuello de botella
                                         con métricas

k6 corre DENTRO de la red Docker, así que habla con `api-gateway:80` sin pasar
por la traducción de red de Windows. No hace falta instalar nada: se usa la
imagen oficial `grafana/k6`.

Uso:
    python pruebas_k6/correr.py --fase 100k
    python pruebas_k6/correr.py --fase 500k
    python pruebas_k6/correr.py --fase 1M
    python pruebas_k6/correr.py --fase 100k --vus 100      # afinar concurrencia
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

# La consola de Windows usa cp1252: la salida de k6 trae simbolos que la
# revientan con UnicodeEncodeError. Se fuerza UTF-8 como en pruebas/lib/comun.py.
for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        _flujo.reconfigure(encoding="utf-8", errors="replace")

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
AQUI = os.path.dirname(os.path.abspath(__file__))
RESULTADOS = os.path.join(AQUI, "resultados")
TABLA = os.path.join(RAIZ, "documentacion", "tabla_registro_carga_k6.md")
os.makedirs(RESULTADOS, exist_ok=True)

# Las tres fases que pide la S34. Los VUs son concurrencia, no peticiones:
# suben con el nivel para que la 1M no tarde una eternidad.
FASES = {
    "100k": {"total": 100_000, "vus": 50, "max": "30m"},
    "500k": {"total": 500_000, "vus": 80, "max": "60m"},
    "1M": {"total": 1_000_000, "vus": 120, "max": "90m"},
    # Nivel corto para comprobar que todo funciona antes de una corrida larga.
    "humo": {"total": 2_000, "vus": 20, "max": "5m"},
}


def red_docker() -> str:
    """Red a la que está conectado ESTE api-gateway.

    Se le pregunta al contenedor en vez de adivinar por el nombre: si hay
    varias copias del proyecto en la misma máquina (p. ej. `shservices_v2` y
    `shservices_yassir`), elegir por parecido de cadena mete a k6 en la red
    equivocada y la prueba mide otro sistema — que es justo lo que pasó la
    primera vez que se ejecutó esto.
    """
    r = subprocess.run(
        ["docker", "inspect", "api-gateway",
         "--format", "{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    redes = (r.stdout or "").split()
    if not redes:
        print("No se encontró el contenedor `api-gateway`. ¿Está levantado el sistema?")
        sys.exit(1)
    return redes[0]


class Muestreador(threading.Thread):
    """Muestrea CPU/Mem del gateway y la profundidad de cola durante la corrida."""

    def __init__(self, intervalo=5):
        super().__init__(daemon=True)
        self.intervalo = intervalo
        self.parar = threading.Event()
        self.cpu, self.mem, self.cola = [], [], []

    def run(self):
        while not self.parar.is_set():
            try:
                r = subprocess.run(
                    ["docker", "stats", "api-gateway", "--no-stream",
                     "--format", "{{.CPUPerc}};{{.MemUsage}}"],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=25)
                cpu_txt, mem_txt = r.stdout.strip().split(";")
                self.cpu.append(float(cpu_txt.strip().rstrip("%")))
                m = re.match(r"\s*([\d.]+)\s*([KMG])iB", mem_txt)
                if m:
                    valor = float(m.group(1))
                    self.mem.append(valor * 1024 if m.group(2) == "G" else valor)
            except Exception:
                pass
            try:
                r = subprocess.run(
                    ["docker", "exec", "rabbitmq", "rabbitmqctl", "list_queues",
                     "name", "messages"],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=45)
                total = sum(int(p[1]) for p in
                            (l.split("\t") for l in (r.stdout or "").splitlines())
                            if len(p) == 2 and p[1].strip().isdigit())
                self.cola.append(total)
            except Exception:
                pass
            self.parar.wait(self.intervalo)

    def resumen(self):
        return {
            "cpu_pico": max(self.cpu) if self.cpu else None,
            "cpu_prom": sum(self.cpu) / len(self.cpu) if self.cpu else None,
            "mem_pico": max(self.mem) if self.mem else None,
            "cola_pico": max(self.cola) if self.cola else None,
            "muestras": len(self.cpu),
        }


def redactar_resultado(m, rec):
    """Frase de la columna 'Resultado', con la regla de la S34.

    No es decorativa: si el sistema llegó a su límite hay que decir CUÁL fue el
    primer cuello de botella y con qué métrica se sostiene.
    """
    partes = []
    if m["c500"] > 0:
        partes.append(f"**{m['c500']} errores 500** — el fallo NO quedó contenido")
    else:
        partes.append("cero errores 500")

    if m["degradados"] > 0:
        pct = m["degradados"] / m["total"] * 100
        partes.append(f"{m['degradados']} respuestas 503/504/429 ({pct:.1f}%): "
                      "degradación con contrato, no caídas")
    if m["encolados"] > 0:
        partes.append(f"{m['encolados']} escrituras salvadas por el outbox")

    # Primer cuello de botella, deducido de lo medido.
    if rec["cpu_pico"] and rec["cpu_pico"] > 700:
        partes.append(f"CPU del Gateway al {rec['cpu_pico']:.0f}% "
                      f"({rec['cpu_pico']/100:.1f} núcleos): **primer cuello de botella**")
    elif rec["cola_pico"] and rec["cola_pico"] > 100:
        partes.append(f"cola RabbitMQ hasta {rec['cola_pico']} mensajes: "
                      "los consumidores se quedaron atrás")
    elif m["p95"] > 2000:
        partes.append(f"p95 de {m['p95']:.0f} ms: la latencia absorbe la carga "
                      "antes que los errores")
    return ". ".join(partes) + "."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fase", choices=list(FASES), default="humo")
    ap.add_argument("--vus", type=int, help="Sobrescribe la concurrencia de la fase")
    args = ap.parse_args()
    cfg = FASES[args.fase]
    vus = args.vus or cfg["vus"]

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    salida_json = os.path.join(RESULTADOS, f"k6_{args.fase}_{marca}.json")
    red = red_docker()

    print("=" * 70)
    print(f" CARGA k6 — fase {args.fase}: {cfg['total']:,} peticiones, {vus} VUs".replace(",", " "))
    print("=" * 70)
    print(f"Red Docker: {red}")
    print("k6 corre DENTRO de la red, hablando con api-gateway:80 directamente.")
    print()

    # Se amplian rate limit y bulkhead durante la corrida, igual que hacen las
    # pruebas de Python. Sin esto se mide DONDE CORTA EL LIMITADOR (20 rps por
    # defecto), no la capacidad del sistema: la primera corrida de humo dio un
    # 66% de 503 simplemente porque k6 empujaba mas rapido que el limite.
    # Se restauran siempre en el `finally`.
    print("Ampliando rate limit y bulkhead para medir capacidad, no el limitador...")
    sys.path.insert(0, os.path.join(RAIZ, "pruebas", "lib"))
    from comun import ampliar_rate_limit, restaurar_rate_limit  # noqa: E402
    ampliar_rate_limit()

    muestreador = Muestreador()
    muestreador.start()
    inicio = time.monotonic()

    # Nombre fijo del contenedor: hace falta para poder pararlo con SIGINT
    # desde fuera si el usuario interrumpe (ver más abajo).
    nombre_contenedor = f"k6-{args.fase}-{marca}"
    interrumpido = False

    print("Corriendo. Puedes cortar con Ctrl+C: k6 emitirá el resumen de lo")
    print("que llevara hecho hasta ese momento y se mostrará igualmente.\n")

    proceso = subprocess.Popen(
        ["docker", "run", "--rm", "-i", "--name", nombre_contenedor,
         "--network", red,
         "-e", f"TOTAL={cfg['total']}", "-e", f"VUS={vus}",
         "-e", f"MAX_DURACION={cfg['max']}",
         "grafana/k6:latest", "run", "-"],
        stdin=open(os.path.join(AQUI, "carga.js"), "rb"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )

    try:
        salida, err = proceso.communicate()
    except KeyboardInterrupt:
        # Ctrl+C: se manda SIGINT AL CONTENEDOR, no se mata el proceso local.
        # k6 atiende SIGINT parando los VUs de forma ordenada y ejecutando
        # `handleSummary`, así que el resumen de lo ya hecho sí se emite. Un
        # `kill` directo perdería todas las mediciones de la corrida.
        interrumpido = True
        print("\n\nInterrumpido. Pidiendo a k6 que cierre y emita el resumen parcial...")
        subprocess.run(["docker", "kill", "--signal=SIGINT", nombre_contenedor],
                       capture_output=True)
        try:
            salida, err = proceso.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            proceso.kill()
            salida, err = proceso.communicate()

    proc = subprocess.CompletedProcess(
        args=[], returncode=proceso.returncode, stdout=salida or "", stderr=err or "")
    duracion = time.monotonic() - inicio
    restaurar_rate_limit()
    muestreador.parar.set()
    muestreador.join(timeout=10)
    rec = muestreador.resumen()

    # El script emite el resumen entre marcas (ver handleSummary en carga.js):
    # k6 v2 ya no tiene --summary-export, y buscar "el primer {...}" en la
    # salida legible es fragil porque esa salida tambien lleva llaves.
    resumen = None
    m = re.search(r"<<<RESUMEN_JSON>>>\s*(\{.*?\})\s*<<<FIN_RESUMEN_JSON>>>",
                  proc.stdout or "", re.S)
    if m:
        try:
            resumen = json.loads(m.group(1))
        except json.JSONDecodeError:
            resumen = None

    if not resumen:
        print(proc.stdout[-3000:])
        print(proc.stderr[-2000:])
        print("\nNo se pudo leer el resumen de k6. Revisa la salida de arriba.")
        sys.exit(1)

    met = resumen["metrics"]

    def valores(nombre):
        """k6 v2 anida las cifras en `.values`."""
        return met.get(nombre, {}).get("values", met.get(nombre, {}))

    def contador(nombre):
        return int(valores(nombre).get("count", 0))

    dur = valores("http_req_duration")
    total = contador("http_reqs")
    # `http_req_failed` cuenta TODO >= 400 (incluidos los 409 de negocio). Para
    # el error rate de la tabla interesan solo los fallos REALES del sistema.
    fallidas = int(valores("errores_reales").get("count", 0))
    m = {
        "total": total,
        "rps": total / duracion if duracion else 0,
        "p95": dur.get("p(95)", 0),
        "p99": dur.get("p(99)", 0),
        "error_rate": (fallidas / total * 100) if total else 0,
        "c500": contador("http_500"),
        "c409": contador("http_409"),
        "degradados": contador("http_503_504_429"),
        "encolados": contador("http_202"),
        "lecturas": contador("op_lecturas"),
        "escrituras": contador("op_escrituras"),
    }

    with open(salida_json, "w", encoding="utf-8") as f:
        json.dump({"fase": args.fase, "vus": vus, "duracion_seg": round(duracion, 1),
                   "metricas": m, "recursos": rec, "k6": met}, f, indent=2, ensure_ascii=False)

    cpu_mem = (f"{rec['cpu_pico']:.0f}% / {rec['mem_pico']:.0f} MiB"
               if rec["cpu_pico"] else "—")
    cola = str(rec["cola_pico"]) if rec["cola_pico"] is not None else "—"
    resultado = redactar_resultado(m, rec)

    fila = (f"| **{args.fase}** | {m['rps']:.0f} rps | {m['p95']:.0f} ms | "
            f"{m['p99']:.0f} ms | {m['error_rate']:.2f}% | {cpu_mem} | {cola} | {resultado} |")

    print()
    print("=" * 70)
    print(" FILA PARA LA TABLA DE REGISTRO DE CARGA")
    print("=" * 70)
    print()
    print("| Fase | Throughput | p95 | p99 | Error rate | CPU/Mem | Queue depth | Resultado |")
    print("| :-- | --: | --: | --: | --: | :-- | --: | :-- |")
    print(fila)
    print()
    print(f"  peticiones ....... {m['total']:,}".replace(",", " "))
    print(f"  duracion ......... {duracion/60:.1f} min")
    print(f"  lecturas/escrituras {m['lecturas']:,} / {m['escrituras']:,}".replace(",", " "))
    print(f"  409 (negocio) .... {m['c409']}")
    print(f"  202 (outbox) ..... {m['encolados']}")
    print(f"  503/504/429 ...... {m['degradados']}")
    print(f"  500 .............. {m['c500']}", "  <-- ATENCION" if m["c500"] else "")
    print(f"  CPU pico/prom .... {rec['cpu_pico']:.0f}% / {rec['cpu_prom']:.0f}%"
          if rec["cpu_pico"] else "  CPU ............. sin muestras")
    print()

    if interrumpido:
        print("=" * 70)
        print(" CORRIDA INTERRUMPIDA — estadisticas parciales")
        print("=" * 70)
        print(f"  Se completaron {m['total']:,} de {cfg['total']:,} peticiones "
              f"({m['total']/cfg['total']*100:.1f}%).".replace(",", " "))
        print("  Los numeros de arriba son REALES pero PARCIALES.")
        print()
        print("  NO se anade la fila a la tabla: mezclar una corrida a medias")
        print("  con las completas haria la tabla incomparable. El JSON si se")
        print("  guarda, por si quieres consultarlo.")
        print()
        print(f"  JSON: {salida_json}")
        sys.exit(0)

    # Acumula la fila en el documento, sin borrar las corridas anteriores.
    nuevo = not os.path.exists(TABLA)
    with open(TABLA, "a", encoding="utf-8") as f:
        if nuevo:
            f.write("# Registro de carga — corridas con k6\n\n")
            f.write("> Generado por `python pruebas_k6/correr.py --fase X`. Cada corrida\n")
            f.write("> añade una fila; ninguna columna se escribe a mano.\n\n")
            f.write("| Fase | Throughput | p95 | p99 | Error rate | CPU/Mem | Queue depth | Resultado |\n")
            f.write("| :-- | --: | --: | --: | --: | :-- | --: | :-- |\n")
        f.write(fila + f"  <!-- {marca} -->\n")

    print(f"Fila añadida a: {TABLA}")
    print(f"JSON completo en: {salida_json}")

    if m["c500"] > 0:
        print("\nHUBO ERRORES 500: revisa los logs antes de dar por buena esta corrida.")
        sys.exit(1)


if __name__ == "__main__":
    main()

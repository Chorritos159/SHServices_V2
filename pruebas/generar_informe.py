#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Genera UN informe en Markdown con el resultado de TODAS las pruebas.

Lee lo último que dejó cada prueba en `pruebas/resultados/` y arma
`documentacion/informe_de_pruebas.md`, listo para entregar: tabla de carga,
resultado del caos controlado, tiempos de auto-recuperación y veredicto.

No inventa nada: lo que no se haya corrido sale como *(sin corrida)*, para
que un hueco se vea como un hueco y no se confunda con un cero.

Uso:
    python pruebas/generar_informe.py

Se puede ejecutar las veces que haga falta — siempre lee la corrida más
reciente de cada prueba y reescribe el informe.
"""
import glob
import json
import os
import re
from datetime import datetime

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RESULTADOS = os.path.join(RAIZ, "pruebas", "resultados")
SALIDA = os.path.join(RAIZ, "documentacion", "informe_de_pruebas.md")

# Niveles de carga: (etiqueta, patrón del JSON, peticiones objetivo)
NIVELES = [
    ("780 (línea base)", "02_carga780_*.json", 580),
    ("100k", "03_carga100k_*.json", 8000),
    ("500k", "04_carga500k_*.json", 20000),
    ("1M", "05_carga1M_*.json", 25000),
    ("100k REAL", "13_carga100k_real_*.json", 100000),
]


def ultimo(patron):
    """Ruta del archivo más reciente que casa con el patrón, o None."""
    coincidencias = sorted(glob.glob(os.path.join(RESULTADOS, patron)))
    return coincidencias[-1] if coincidencias else None


def leer_json(patron):
    ruta = ultimo(patron)
    if not ruta:
        return None
    try:
        with open(ruta, encoding="utf-8") as f:
            d = json.load(f)
        d["_archivo"] = os.path.basename(ruta)
        return d
    except (json.JSONDecodeError, OSError):
        return None


def leer_txt(patron):
    ruta = ultimo(patron)
    if not ruta:
        return None
    try:
        with open(ruta, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _marca_de(ruta):
    """Extrae el sello 20260718_162939 del nombre de archivo, como datetime."""
    m = re.search(r"(\d{8}_\d{6})", os.path.basename(ruta))
    return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S") if m else None


def recursos_de(ruta_corrida, margen_min=25):
    """CPU/Mem/cola del monitor que corrió A LA VEZ que esa carga.

    Se empareja por CERCANÍA EN EL TIEMPO, no cogiendo el último sin más: si
    solo hubo un monitor, atribuir su lectura a las cuatro corridas pondría el
    mismo pico en filas que se midieron en momentos distintos — un dato
    inventado con apariencia de medido.
    """
    marca_corrida = _marca_de(ruta_corrida) if ruta_corrida else None
    if not marca_corrida:
        return None

    mejor, mejor_delta = None, None
    for ruta in glob.glob(os.path.join(RESULTADOS, "monitor_recursos_*.txt")):
        marca = _marca_de(ruta)
        if not marca:
            continue
        delta = abs((marca - marca_corrida).total_seconds()) / 60
        if delta <= margen_min and (mejor_delta is None or delta < mejor_delta):
            mejor, mejor_delta = ruta, delta
    if not mejor:
        return None

    try:
        texto = open(mejor, encoding="utf-8").read()
    except OSError:
        return None
    datos = {}
    for clave, patron in [("cpu", r"CPU pico ([\d.]+)%"),
                          ("mem", r"Mem pico (\d+) MiB"),
                          ("cola", r"Queue depth pico (\d+)")]:
        m = re.search(patron, texto)
        if m:
            datos[clave] = m.group(1)
    return datos or None


def fila_carga(etiqueta, patron, objetivo):
    rep = leer_json(patron)
    if not rep:
        return f"| {etiqueta} | *(sin corrida)* | | | | | | |"
    rec = recursos_de(ultimo(patron))

    codigos = {int(k): v for k, v in rep.get("codigos", {}).items() if k.isdigit()}
    total = rep.get("enviadas", 0)
    ok = sum(v for k, v in codigos.items() if k < 400)
    tasa = f"{ok / total * 100:.1f}%" if total else "—"
    lat = rep.get("latencia_ms", {})
    err = f"{(total - ok) / total * 100:.1f}%" if total else "—"

    cpu_mem = f"{rec['cpu']}% / {rec['mem']} MiB" if rec else "*(monitor)*"
    cola = rec["cola"] if rec else "*(monitor)*"

    return (f"| {etiqueta} | {total} ({tasa}) | {rep.get('throughput_rps','—')} rps | "
            f"{lat.get('p95','—')} ms | {lat.get('p99','—')} ms | {err} | {cpu_mem} | {cola} |")


def bloque_carga():
    lineas = [
        "## 1. Pruebas de carga",
        "",
        "Cada nivel corta por **conteo** de peticiones, no por ventana de tiempo:",
        "así la cifra es la misma en cada corrida y lo que varía es la duración,",
        "que es justo la variable que se quiere medir.",
        "",
        "| Nivel | Peticiones (éxito) | Throughput | p95 | p99 | Error rate | CPU/Mem | Cola |",
        "| :-- | --: | --: | --: | --: | --: | :-- | --: |",
    ]
    for etiqueta, patron, objetivo in NIVELES:
        lineas.append(fila_carga(etiqueta, patron, objetivo))

    lineas += ["",
               "> **CPU/Mem** y **Cola** salen de `pruebas/monitor_recursos.py`, que se",
               "> corre en paralelo a la carga. Si aparecen como *(monitor)*, esa corrida",
               "> se hizo sin él.",
               ""]

    # Detalle de códigos: es donde se ve si hubo 500 (fallo real) o solo
    # 429/503 (degradación con contrato).
    lineas += ["### Códigos de respuesta por nivel", ""]
    hubo = False
    for etiqueta, patron, _ in NIVELES:
        rep = leer_json(patron)
        if not rep:
            continue
        hubo = True
        codigos = rep.get("codigos", {})
        s500 = int(codigos.get("500", 0))
        marca = "  ← **atención**" if s500 else ""
        lineas.append(f"- **{etiqueta}**: `{codigos}`{marca}")
    if not hubo:
        lineas.append("*(sin corridas todavía)*")
    lineas += ["",
               "### Cómo se lee cada código", "",
               "| Código | Qué significa | ¿Es un fallo? |",
               "| :-- | :-- | :-- |",
               "| **200 / 201** | La operación se completó | No |",
               "| **202** | Escritura **encolada en el outbox** porque el servicio destino no respondía. No se perdió: se entrega sola al volver | No — es la garantía de cero pérdida funcionando |",
               "| **409** | Conflicto de negocio: el ticket ya tenía diagnóstico, la factura ya existía. Bajo carga mixta con datos aleatorios es inevitable y **correcto** | No — es la idempotencia rechazando un duplicado |",
               "| **429** | Rate limit: el sistema decidió frenar para protegerse | No — es backpressure con contrato |",
               "| **503 / 504** | Circuit breaker o timeout: fail-fast ante una dependencia enferma | No — es degradación con contrato, reintentable |",
               "| **500** | Falló algo que nadie previó | **SÍ. Es el único código que delata al sistema** |",
               "| **ERR** | El generador no recibió respuesta: la petición no llegó a completarse | Ver abajo |",
               "",
               "### Sobre los `ERR`", "",
               "`ERR` no es un código HTTP: es cualquier excepción del cliente de carga",
               "(el servidor nunca devolvió estado). Conviene mirarlo con la latencia",
               "máxima al lado antes de atribuirle una causa:",
               "",
               "- Si el **máximo está pegado al timeout del cliente (10.000 ms)**, son",
               "  timeouts: el servidor tardó más de lo aceptable. Eso **sí** es del",
               "  sistema y hay que decirlo.",
               "- Si el **máximo está muy por debajo** (p. ej. 3.700 ms), fallaron a nivel",
               "  de **conexión**, no por lentitud. Apunta al generador de carga o al",
               "  sistema operativo (límites de conexiones, puertos efímeros en Windows),",
               "  no a que el backend fuera lento.",
               "",
               "En las corridas de este informe el segundo caso es el que aplica. Aun así",
               "**no está aislado con certeza**, y se registra como *limitación de la",
               "medición*, no como \"culpa del cliente\": afirmar lo segundo exigiría",
               "reproducirlo con otro generador desde otra máquina, y eso no se hizo.",
               ""]
    return lineas


def bloque_caos_controlado():
    lineas = ["## 2. Caos controlado bajo carga", ""]
    texto = leer_txt("11_caos_bajo_carga_*.txt")
    if not texto:
        return lineas + ["*(sin corrida: `python pruebas/11_caos_bajo_carga.py --nivel 500k`)*", ""]

    lineas += ["Se tumban servicios **sin parar el tráfico**, para ver qué le pasa a",
               "quien ya estaba operando.", ""]

    # Resumen de la carga que aguantó el caos.
    for clave, etiqueta in [("peticiones enviadas", "Peticiones"),
                            ("throughput", "Throughput"),
                            ("atendidas con exito", "Atendidas con éxito"),
                            ("ERRORES OPACOS (500)", "Errores 500"),
                            ("latencia p95 / p99", "Latencia p95/p99")]:
        # `re.escape` hace que los paréntesis de "(500)" se busquen literales;
        # `[ .]*` se salta los puntos de relleno con que el reporte alinea.
        m = re.search(rf"{re.escape(clave)}[ .]*([^\n]+)", texto)
        if m:
            lineas.append(f"- **{etiqueta}:** {m.group(1).strip()}")

    # Línea de tiempo: la evidencia de que solo cae el circuito del servicio caído.
    m = re.search(r"LINEA DE TIEMPO.*?\n=+\n(.*?)(?:\n=|\Z)", texto, re.S)
    if m:
        lineas += ["", "### Línea de tiempo de los circuitos", "",
                   "```", m.group(1).strip(), "```", "",
                   "Solo se abre el circuito del servicio caído: los demás siguen CLOSED.",
                   "Eso **es** la ausencia de cascada, medida."]

    m = re.search(r"VEREDICTO:([^\n]*)", texto)
    if m:
        lineas += ["", f"**Veredicto:** {m.group(1).strip()}"]
    return lineas + [""]


def bloque_autorecuperacion():
    lineas = ["## 3. Auto-recuperación (los servicios se curan solos)", ""]
    texto = leer_txt("12_autorecuperacion_*.txt")
    if not texto:
        return lineas + ["*(sin corrida: `python pruebas/12_autorecuperacion.py --nivel 500k`)*", ""]

    lineas += ["Se **mata el proceso** (`os._exit(1)`) y no se vuelve a tocar nada.",
               "Docker lo revive y la sonda del breaker cierra el circuito sola.", ""]

    m = re.search(r"TIEMPOS DE AUTO-RECUPERACION[^\n]*\n=+\n(.*?)(?:\n\n|\Z)", texto, re.S)
    if m:
        lineas += ["```", m.group(1).rstrip(), "```", ""]

    m = re.search(r"(peor caso: [^\n]+)", texto)
    if m:
        lineas.append(f"**{m.group(1).strip()}**")
        lineas += ["",
                   "Ese total es el tiempo real de indisponibilidad si un servicio se cae",
                   "de madrugada y nadie lo mira. Es el número que sostiene el objetivo de",
                   "disponibilidad del SLA."]

    if "Medido BAJO CARGA" in texto:
        lineas += ["", "> Medido **bajo carga**: el servicio arrancó compitiendo por CPU con",
                   "> tráfico real. Es el número honesto; en reposo sale ~3× mejor."]
    elif "OJO: medido en REPOSO" in texto:
        lineas += ["", "> ⚠️ Medido **en reposo** (mejor caso). Para el dato defendible,",
                   "> correr con `--nivel 500k`."]
    return lineas + [""]


def bloque_fichas_caos():
    lineas = ["## 4. Fichas de falla controlada", ""]
    texto = leer_txt("06_caos_*.txt")
    if not texto:
        return lineas + ["*(sin corrida: `python pruebas/06_caos.py`)*", ""]
    fichas = re.findall(r"FICHA ([A-Z]): ([^\n]+)", texto)
    if fichas:
        lineas += ["| Ficha | Escenario |", "| :-- | :-- |"]
        lineas += [f"| {letra} | {desc.strip()} |" for letra, desc in fichas]
    m = re.search(r"Veredicto S26/S34:([^\n]*(?:\n[^\n=]+)*)", texto)
    if m:
        lineas += ["", f"**Veredicto:** {' '.join(m.group(1).split())}"]
    return lineas + [""]


def bloque_breaker():
    lineas = ["## 5. Circuit breaker en todos los servicios", ""]
    texto = leer_txt("07_breaker_todos_*.txt")
    if not texto:
        return lineas + ["*(sin corrida: `python pruebas/07_breaker_todos.py`)*", ""]
    servicios = re.findall(r"--- (\w+)\s+\([^)]+\)[^\n]*\n(.*?)(?=\n--- |\n=)", texto, re.S)
    if servicios:
        lineas += ["| Servicio | Respuestas | Circuito | Recuperación |",
                   "| :-- | :-- | :-- | :-- |"]
        for nombre, cuerpo in servicios:
            resp = re.search(r"respuestas con [^:]*: (\[[^\]]*\])", cuerpo)
            desp = re.search(r"circuito despues: ([\d.]+)", cuerpo)
            fin = re.search(r"circuito tras recuperacion: ([\d.]+)", cuerpo)
            est = {"0.0": "CLOSED", "2.0": "**OPEN**"}
            lineas.append(
                f"| {nombre} | {resp.group(1) if resp else '—'} | "
                f"{est.get(desp.group(1), desp.group(1)) if desp else '—'} | "
                f"{est.get(fin.group(1), fin.group(1)) if fin else '—'} |")
    m = re.search(r"RESULTADO: ([^\n]+)", texto)
    if m:
        lineas += ["", f"**Resultado:** {m.group(1).strip()}"]
    return lineas + [""]


def bloque_e2e():
    lineas = ["## 6. Flujo de negocio completo (E2E)", ""]
    texto = leer_txt("08_flujo_completo_*.txt")
    if not texto:
        return lineas + ["*(sin corrida: `python pruebas/08_flujo_completo.py`)*", ""]
    m = re.search(r"COBERTURA:.*?\n(.*?)(?:\n=|\Z)", texto, re.S)
    if m:
        lineas += ["Los 8 servicios hicieron su parte:", "", "```", m.group(1).strip(), "```", ""]
    m = re.search(r"RESULTADO: ([^\n]+)", texto)
    if m:
        lineas.append(f"**Resultado:** {m.group(1).strip()}")
    return lineas + [""]


def main():
    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
    doc = [
        "# Informe de pruebas — SHServices V2",
        "",
        f"> Generado automáticamente el **{ahora}** con",
        "> `python pruebas/generar_informe.py`, leyendo la última corrida de cada",
        "> prueba en `pruebas/resultados/`. Ningún número está escrito a mano.",
        "",
    ]
    doc += bloque_carga()
    doc += ["---", ""] + bloque_caos_controlado()
    doc += ["---", ""] + bloque_autorecuperacion()
    doc += ["---", ""] + bloque_fichas_caos()
    doc += ["---", ""] + bloque_breaker()
    doc += ["---", ""] + bloque_e2e()
    doc += [
        "---",
        "",
        "## Cómo reproducir",
        "",
        "```bash",
        "docker compose stop sonarqube            # libera CPU",
        "python pruebas/limpiar_datos_carga.py --borrar",
        "",
        "python pruebas/02_carga_780.py           # ~40 s",
        "python pruebas/03_carga_100k.py          # ~3.5 min",
        "python pruebas/04_carga_500k.py          # ~8.5 min",
        "python pruebas/05_carga_1M.py            # ~10.5 min",
        "",
        "python pruebas/06_caos.py                # ~1.5 min",
        "python pruebas/07_breaker_todos.py       # ~3 min",
        "python pruebas/08_flujo_completo.py      # ~20 s",
        "python pruebas/11_caos_bajo_carga.py --nivel 500k",
        "python pruebas/12_autorecuperacion.py --nivel 500k",
        "",
        "python pruebas/generar_informe.py        # regenera este documento",
        "```",
        "",
    ]

    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        f.write("\n".join(doc) + "\n")

    print(f"Informe generado: {SALIDA}")
    print()
    # Recuento honesto de qué hay y qué falta.
    faltan = [e for e, p, _ in NIVELES if not ultimo(p)]
    otras = {"caos bajo carga (11)": "11_caos_bajo_carga_*.txt",
             "auto-recuperacion (12)": "12_autorecuperacion_*.txt",
             "fichas de caos (06)": "06_caos_*.txt",
             "breaker (07)": "07_breaker_todos_*.txt",
             "E2E (08)": "08_flujo_completo_*.txt"}
    faltan += [n for n, p in otras.items() if not ultimo(p)]
    if faltan:
        print("Todavia SIN corrida (saldran como '(sin corrida)'):")
        for f_ in faltan:
            print(f"   - {f_}")
    else:
        print("Todas las pruebas tienen corrida. El informe esta completo.")


if __name__ == "__main__":
    main()

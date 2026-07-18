#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generador de carga por NODOS y BLOQUES (Fase 5, S34).

A diferencia de `carga.py` (un pool de hilos disparando sin parar), esto
simula varios "nodos" independientes (clientes/orígenes distintos) que
envían la carga en BLOQUES sucesivos, con una pausa entre bloque y bloque
— el patrón que describe la S34: no es "un hilo" ni "todo de golpe", son
varios nodos que van mandando tandas.

Acotado por TIEMPO, no por conteo: las corridas de 100k/500k/1M no
completan literalmente ese número de peticiones (a la tasa real medida,
tomaría entre 1.5 y 4 horas) — se ejecutan durante una ventana fija de
10-15 minutos y se reporta cuánto se alcanzó del objetivo, explicando el
primer cuello de botella si no se llega (regla explícita de la S34: "si el
sistema llega a su límite, el equipo debe explicar el primer cuello de
botella con métricas"). El número 100k/500k/1M es la ETIQUETA del nivel de
carga ofrecida (más nodos, bloques más grandes), no un conteo a cumplir.

Backoff entre bloques: escalonado 3s / 5s / 8s + jitter cuando un bloque
recibe 429/503 (se sube de nivel); un bloque limpio baja el nivel a 0. Sin
esto, todos los nodos reintentarían sincronizados y ahogarían al sistema
justo cuando ya está bajo presión.
"""
import argparse
import asyncio
import collections
import json
import os
import random
import sys
import time
from datetime import datetime

import httpx

AUTH_URL = "http://localhost:8000/api/v1/auth/login"   # via Gateway
BACKOFF_SEQ = [3.0, 5.0, 8.0]  # segundos, escalonado (S34)


def percentil(ordenadas, p):
    if not ordenadas:
        return 0.0
    i = min(len(ordenadas) - 1, max(0, round(p * (len(ordenadas) - 1))))
    return ordenadas[i]


async def login(usuario, password):
    async with httpx.AsyncClient() as c:
        r = await c.post(AUTH_URL, json={"usuario": usuario, "password": password}, timeout=10.0)
        return r.json()["access_token"]


async def golpe(client, url, headers):
    t0 = time.perf_counter()
    try:
        r = await client.get(url, headers=headers, timeout=10.0)
        return r.status_code, (time.perf_counter() - t0) * 1000
    except Exception:
        return "ERR", (time.perf_counter() - t0) * 1000


# ─────────────────────────────────────────────────────────────────────────
# MODO MIXTO (--mixto): lecturas Y ESCRITURAS tocando TODOS los servicios.
# Las escrituras son las que hacen que RabbitMQ se mueva (queue depth /
# consumer lag) y que auditoria + notificaciones trabajen de verdad.
# Todo lo que se crea va marcado con MARCA para poder limpiarlo despues
# (ver pruebas/limpiar_datos_carga.py).
# ─────────────────────────────────────────────────────────────────────────
MARCA = "CARGA"


def _suf():
    return f"{random.randint(100000, 999999)}"


async def _pedir(client, headers, metodo, ruta, cuerpo=None, base=""):
    """Una peticion; devuelve (codigo, ms). Nunca lanza."""
    t0 = time.perf_counter()
    try:
        url = f"{base}/{ruta.lstrip('/')}"
        if metodo == "GET":
            r = await client.get(url, headers=headers, timeout=10.0)
        else:
            r = await client.post(url, headers=headers, json=cuerpo or {}, timeout=10.0)
        return r.status_code, (time.perf_counter() - t0) * 1000, r
    except Exception:
        return "ERR", (time.perf_counter() - t0) * 1000, None


async def op_lectura(client, headers, base, ruta):
    c, ms, _ = await _pedir(client, headers, "GET", ruta, base=base)
    return [(c, ms)]


async def op_crear_ticket(client, headers, base):
    """POST ticket de VENTA: valido siempre y NO engorda la cola del tecnico
    (nace en VENTA_REGISTRADA). Emite evento -> auditoria + notificaciones."""
    cuerpo = {
        "datosCliente": f"{MARCA}-Cliente-{_suf()}",
        "documento_cliente": "70000000",
        "telefono_cliente": "987654321",
        "tipoOperacion": "VENTA",
        "prioridad": "BAJA",
    }
    c, ms, _ = await _pedir(client, headers, "POST", "api/v1/tickets/tickets/", cuerpo, base)
    return [(c, ms)]


async def op_crear_producto(client, headers, base):
    """POST producto en almacen. Emite producto.registrado."""
    cuerpo = {"nombre": f"{MARCA}-Prod-{_suf()}", "categoria": "REPUESTO",
              "sede": "PIURA", "stock_inicial": 5}
    c, ms, _ = await _pedir(client, headers, "POST", "api/v1/almacen/almacen/productos", cuerpo, base)
    return [(c, ms)]


async def op_marcar_leidas(client, headers, base):
    """Escritura segura en notificaciones (no genera basura)."""
    c, ms, _ = await _pedir(client, headers, "POST",
                            "api/v1/notificaciones/notificaciones/marcar-leidas", {}, base)
    return [(c, ms)]


async def op_flujo_negocio(client, headers, base):
    """CADENA de escritura con datos VALIDOS que toca diagnosticos y facturas:
    crear ticket SOPORTE -> tomarlo -> registrar diagnostico -> cobrar.
    Es la unica forma de ejercitar esos dos servicios con escrituras reales
    (necesitan un ticket en el estado correcto). Va con peso bajo.
    """
    res = []
    cuerpo_t = {
        "datosCliente": f"{MARCA}-Flujo-{_suf()}",
        "documento_cliente": "70000001",
        "telefono_cliente": "987654321",
        "tipoOperacion": "SOPORTE",
        "equipo": "PC de carga",
        "numero_serie": f"{MARCA}-SN-{_suf()}",
        "caracteristicas_falla": "prueba de carga",
        "prioridad": "BAJA",
    }
    c, ms, r = await _pedir(client, headers, "POST", "api/v1/tickets/tickets/", cuerpo_t, base)
    res.append((c, ms))
    id_ticket = None
    try:
        if r is not None and r.status_code < 400:
            id_ticket = r.json().get("idTicket")
    except Exception:
        id_ticket = None
    if not id_ticket:
        return res

    # 2. el tecnico lo toma (diagnostico-service, dueno de las asignaciones)
    c, ms, _ = await _pedir(client, headers, "POST", "api/v1/diagnosticos/asignaciones/tomar",
                            {"id_ticket": id_ticket, "equipo": "PC de carga"}, base)
    res.append((c, ms))

    # 3. registrar el diagnostico (sin repuestos: no toca stock)
    c, ms, _ = await _pedir(client, headers, "POST", "api/v1/diagnosticos/diagnosticos/",
                            {"idTicket": id_ticket, "fallaDetectada": "carga",
                             "mano_obra": 50, "precio_reparacion": 50, "repuestos": []}, base)
    res.append((c, ms))

    # 4. cobrar (facturacion-service) -> emite ticket.facturado
    c, ms, _ = await _pedir(client, headers, "POST", "api/v1/facturas/facturas/",
                            {"idTicket": id_ticket, "montoManoObra": 50,
                             "montoRepuestos": 0, "metodoPago": "EFECTIVO", "sede": "PIURA"}, base)
    res.append((c, ms))
    return res


# Mezcla ponderada: ~70% lecturas / ~30% escrituras. La cadena de negocio va
# con peso 1 (poco frecuente) porque son 4 peticiones y crea datos.
def construir_mezcla():
    lecturas = [
        ("api/v1/tickets/tickets/pendientes", 3),
        ("api/v1/almacen/almacen/productos", 3),
        ("api/v1/auditoria/auditoria/eventos", 3),
        ("api/v1/notificaciones/notificaciones/mis-alertas", 3),
        ("api/v1/diagnosticos/asignaciones/mias", 2),
    ]
    ops = []
    for ruta, peso in lecturas:
        ops += [("GET " + ruta, lambda cl, h, b, _r=ruta: op_lectura(cl, h, b, _r))] * peso
    ops += [("POST crear_ticket", op_crear_ticket)] * 3
    ops += [("POST crear_producto", op_crear_producto)] * 2
    ops += [("POST marcar_leidas", op_marcar_leidas)] * 2
    ops += [("CADENA negocio", op_flujo_negocio)] * 1
    return ops


async def nodo(indice, urls, headers, bloque, fin_ts, resultados, latencias, candado,
               bloques_enviados, mezcla=None, base="", total_objetivo=0):
    """Un nodo: manda bloques sucesivos (concurrentes DENTRO del bloque,
    secuenciales ENTRE bloques) hasta que se acaba el tiempo de la corrida.

    Con `total_objetivo` > 0 la corrida termina al alcanzar ESE NUMERO de
    peticiones, y la ventana de tiempo pasa a ser solo un tope de seguridad.
    Es el modo que usa la prueba de 100k REALES: ahi lo que importa es
    completar el conteo, no llenar un tiempo.

    Si hay `mezcla` (modo mixto), cada hueco del bloque ejecuta una operacion
    de la mezcla (lecturas Y escrituras, todos los servicios). Si no, rota por
    las URLs de solo lectura (modo clasico).
    """
    nivel_backoff = 0
    limits = httpx.Limits(max_connections=bloque + 5, max_keepalive_connections=bloque + 5)
    async with httpx.AsyncClient(limits=limits) as client:
        while time.monotonic() < fin_ts:
            if total_objetivo:
                async with candado:
                    if sum(resultados.values()) >= total_objetivo:
                        break
            if mezcla:
                tareas = [random.choice(mezcla)[1](client, headers, base) for _ in range(bloque)]
            else:
                tareas = [golpe(client, urls[j % len(urls)], headers) for j in range(bloque)]
            resp = await asyncio.gather(*tareas)

            # En modo mixto cada operacion devuelve una LISTA de resultados
            # (la cadena de negocio son 4 peticiones); se aplanan.
            if mezcla:
                planos = [par for sub in resp for par in sub]
            else:
                planos = list(resp)

            hubo_limite = False
            async with candado:
                for codigo, ms in planos:
                    resultados[codigo] += 1
                    latencias.append(ms)
                    if codigo in (429, 503, 504):
                        hubo_limite = True
                bloques_enviados[0] += 1

            if hubo_limite:
                espera = BACKOFF_SEQ[min(nivel_backoff, len(BACKOFF_SEQ) - 1)] + random.uniform(0, 1.0)
                nivel_backoff = min(nivel_backoff + 1, len(BACKOFF_SEQ) - 1)
            else:
                nivel_backoff = 0
                espera = 0.2 + random.uniform(0, 0.2)  # pausa corta entre bloques limpios

            restante = fin_ts - time.monotonic()
            if restante <= 0:
                break
            await asyncio.sleep(min(espera, restante))


async def progreso(resultados, candado, fin_ts, bloques_enviados, inicio, nodos, bloque,
                   total_objetivo=0):
    ultimo = 0
    while time.monotonic() < fin_ts:
        await asyncio.sleep(5)
        async with candado:
            total = sum(resultados.values())
            b = bloques_enviados[0]
        rps = (total - ultimo) / 5
        ultimo = total
        if total_objetivo:
            # Modo conteo: lo util es cuanto falta y a que hora acaba, no los
            # segundos de ventana. Una corrida de 100k dura ~37 min y hay que
            # poder dejarla sola sabiendo cuando volver.
            faltan = max(0, total_objetivo - total)
            eta = faltan / rps if rps > 0 else 0
            pct = total / total_objetivo * 100
            print(f"  … {total}/{total_objetivo} ({pct:.1f}%) ~{rps:.0f} rps  "
                  f"[{time.monotonic()-inicio:.0f}s, faltan {faltan} -> ~{eta/60:.1f} min]",
                  file=sys.stderr, flush=True)
            if total >= total_objetivo:
                return
        else:
            restante = max(0, fin_ts - time.monotonic())
            print(f"  … {total} enviadas, {b} bloques ({nodos} nodos x {bloque}/bloque) "
                  f"~{rps:.0f} rps  [{time.monotonic()-inicio:.0f}s, quedan ~{restante:.0f}s]",
                  file=sys.stderr, flush=True)


async def correr(args):
    token = ""
    if args.usuario:
        token = await login(args.usuario, args.password)
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    # `--rutas` (coma) tiene prioridad sobre `--ruta`: reparte la carga entre
    # varios servicios. MSYS convierte un "/" inicial en ruta de Windows, por
    # eso las rutas van sin barra inicial y se repone aqui.
    crudas = args.rutas.split(",") if args.rutas else [args.ruta]
    urls = [f"http://{args.host}:{args.puerto}/{r.strip().lstrip('/')}" for r in crudas if r.strip()]

    resultados = collections.Counter()
    latencias = []
    bloques_enviados = [0]
    candado = asyncio.Lock()

    inicio = time.monotonic()
    fin_ts = inicio + args.duracion_seg

    mezcla = construir_mezcla() if args.mixto else None
    base = f"http://{args.host}:{args.puerto}"
    if mezcla:
        destino = "TODOS los servicios (lecturas + escrituras)"
    else:
        destino = urls[0] if len(urls) == 1 else f"{len(urls)} servicios"
    print(f"== {args.nombre}: objetivo etiqueta '{args.objetivo}', "
          f"{args.nodos} nodos x bloques de {args.bloque}, ventana {args.duracion_seg}s -> {destino} ==",
          flush=True)

    tareas_nodos = [
        nodo(i, urls, headers, args.bloque, fin_ts, resultados, latencias, candado,
             bloques_enviados, mezcla, base, args.total)
        for i in range(args.nodos)
    ]
    await asyncio.gather(
        *tareas_nodos,
        progreso(resultados, candado, fin_ts, bloques_enviados, inicio, args.nodos,
                 args.bloque, args.total),
    )

    duracion = time.monotonic() - inicio
    ordenadas = sorted(latencias)
    total = sum(resultados.values())
    exitos = sum(v for k, v in resultados.items() if isinstance(k, int) and k < 400)

    reporte = {
        "prueba": args.nombre,
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "objetivo_etiqueta": args.objetivo,
        "total_objetivo": args.total or None,
        "modo_corte": "conteo" if args.total else "ventana de tiempo",
        "modo": "mixto (lecturas + escrituras, todos los servicios)" if mezcla else "solo lecturas",
        "nodos": args.nodos,
        "bloque": args.bloque,
        "bloques_enviados": bloques_enviados[0],
        "duracion_objetivo_seg": args.duracion_seg,
        "rutas": [u.split("/", 3)[-1] for u in urls],
        "duracion_real_seg": round(duracion, 1),
        "throughput_rps": round(total / duracion, 1) if duracion else 0,
        "enviadas": total,
        "exitosas": exitos,
        "tasa_exito": round(exitos / total, 4) if total else 0,
        "codigos": {str(k): v for k, v in sorted(resultados.items(), key=lambda x: str(x[0]))},
        "latencia_ms": {
            "p50": round(percentil(ordenadas, 0.50), 1),
            "p90": round(percentil(ordenadas, 0.90), 1),
            "p95": round(percentil(ordenadas, 0.95), 1),
            "p99": round(percentil(ordenadas, 0.99), 1),
            "max": round(ordenadas[-1], 1) if ordenadas else 0,
        },
    }

    os.makedirs(args.salida, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_json = os.path.join(args.salida, f"{args.nombre}_{marca}.json")
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(reporte, f, indent=2, ensure_ascii=False)

    lineas = [
        f"== Reporte: {args.nombre} ({reporte['fecha']}) ==",
        f"objetivo(etiqueta)={args.objetivo}  nodos={args.nodos}  bloque={args.bloque}  "
        f"bloques_enviados={bloques_enviados[0]}  ventana={args.duracion_seg}s",
        f"duracion_real={reporte['duracion_real_seg']}s  throughput={reporte['throughput_rps']} rps",
        f"exitosas={exitos}/{total} ({reporte['tasa_exito']*100:.1f}%)",
        "codigos: " + "  ".join(f"HTTP {k}: {v}" for k, v in reporte["codigos"].items()),
        (f"latencia ms: p50={reporte['latencia_ms']['p50']} p90={reporte['latencia_ms']['p90']} "
         f"p95={reporte['latencia_ms']['p95']} p99={reporte['latencia_ms']['p99']} "
         f"max={reporte['latencia_ms']['max']}"),
        f"reporte JSON: {ruta_json}",
    ]
    texto = "\n".join(lineas)
    with open(os.path.join(args.salida, f"{args.nombre}_{marca}.txt"), "w", encoding="utf-8") as f:
        f.write(texto + "\n")
    print(texto, flush=True)


def main():
    p = argparse.ArgumentParser(description="Generador de carga por nodos/bloques (S34)")
    p.add_argument("--host", default="localhost")
    p.add_argument("--puerto", type=int, default=8000)
    p.add_argument("--ruta", default="api/v1/tickets/tickets/")
    p.add_argument("--rutas", default="",
                   help="Rutas GET separadas por coma (reparte la carga entre varios servicios). "
                        "Sin barra inicial. Si se da, tiene prioridad sobre --ruta.")
    p.add_argument("--nodos", type=int, default=8, help="Nodos concurrentes independientes")
    p.add_argument("--bloque", type=int, default=50, help="Peticiones concurrentes por bloque, por nodo")
    p.add_argument("--duracion-seg", type=int, default=600, help="Ventana de tiempo total (segundos)")
    p.add_argument("--objetivo", default="100k", help="Etiqueta del nivel de carga (solo para el reporte)")
    p.add_argument("--usuario", default="admin")
    p.add_argument("--password", default="admin123")
    p.add_argument("--nombre", default="carga_nodos")
    p.add_argument("--salida", default="pruebas/resultados")
    p.add_argument("--total", type=int, default=0,
                   help="Peticiones a completar. Si se indica, la corrida acaba al "
                        "llegar a ese numero y --duracion-seg pasa a ser solo un tope.")
    p.add_argument("--mixto", type=int, default=0,
                   help="1 = mezcla lecturas Y ESCRITURAS tocando TODOS los servicios "
                        "(incluye una cadena crear->tomar->diagnosticar->cobrar).")
    args = p.parse_args()
    asyncio.run(correr(args))


if __name__ == "__main__":
    main()

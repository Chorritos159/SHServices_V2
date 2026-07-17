#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Utilidades comunes de la suite de pruebas (Fase 5, S34). Todo en Python:
ya no hay orquestación en Bash — cada prueba es un script .py que importa
esto y, si necesita generar carga, llama a `carga.py`/`carga_nodos.py`/
`rafaga_async.py` como subproceso (mismo intérprete, `sys.executable`).
"""
import os
import subprocess
import sys
import time

import httpx

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LIB = os.path.dirname(os.path.abspath(__file__))
RESULTADOS = os.path.join(RAIZ, "pruebas", "resultados")
os.makedirs(RESULTADOS, exist_ok=True)

GW = "http://localhost:8000"
AUTH = "http://localhost:8003/api/v1/auth"


def banner(mensaje: str):
    print(f"\n{'=' * 44}\n {mensaje}\n{'=' * 44}")


def login(usuario: str = "admin", password: str = "admin123") -> str:
    r = httpx.post(f"{AUTH}/login", json={"usuario": usuario, "password": password}, timeout=10.0)
    r.raise_for_status()
    return r.json()["access_token"]


def verificar_sistema():
    try:
        r = httpx.get(f"{GW}/health", timeout=5.0)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
    except Exception:
        print(f"❌ El gateway no responde en {GW}. Levanta el sistema: docker compose up -d")
        sys.exit(1)


def metrica_gateway(patron: str) -> str:
    """Lee una métrica puntual de /metrics (Prometheus). `patron` es el
    nombre exacto de la serie, con labels si aplica, p.ej.
    'gateway_circuit_state{service="tickets"}'.
    """
    try:
        texto = httpx.get(f"{GW}/metrics", timeout=10.0).text
    except Exception:
        return "N/D"
    ultimo = None
    for linea in texto.splitlines():
        if linea.startswith("#"):
            continue
        if patron in linea:
            ultimo = linea
    if ultimo is None:
        return "0"
    return ultimo.rsplit(" ", 1)[-1]


def docker(*args, env=None):
    """Ejecuta `docker <args>` desde la raíz del repo (p.ej. docker("compose", "up", "-d", "api-gateway"))."""
    cmd = ["docker", *[str(a) for a in args]]
    return subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True, env=env)


def ampliar_rate_limit(rps: int = 100000, burst: int = 100000, espera_seg: int = 6):
    """Amplía TEMPORALMENTE el rate limit del Gateway (mide el throughput
    real del backend, no el techo del limitador). Recuerda restaurar con
    `restaurar_rate_limit()` en un `finally`.
    """
    env = os.environ.copy()
    env["RATE_LIMIT_RPS"] = str(rps)
    env["RATE_LIMIT_BURST"] = str(burst)
    docker("compose", "up", "-d", "api-gateway", env=env)
    time.sleep(espera_seg)


def restaurar_rate_limit():
    banner("Restaurando límites normales del gateway (20 rps / 40 burst)")
    env = os.environ.copy()
    env.pop("RATE_LIMIT_RPS", None)
    env.pop("RATE_LIMIT_BURST", None)
    docker("compose", "up", "-d", "api-gateway", env=env)


def correr_runner(script: str, *args) -> int:
    """Invoca un runner de carga (carga.py / carga_nodos.py) como
    subproceso con el mismo intérprete, heredando stdout/stderr en vivo.
    """
    cmd = [sys.executable, os.path.join(LIB, script), *[str(a) for a in args]]
    return subprocess.run(cmd, cwd=RAIZ).returncode


def nivel_carga(nombre: str, objetivo: str, nodos: int, bloque: int, duracion_seg: int):
    """Corre un nivel de carga (100k/500k/1M) por nodos/bloques (S34,
    Fase 5): amplía el rate limit del gateway temporalmente, corre
    `carga_nodos.py` con los parámetros del nivel, restaura los límites
    (siempre, incluso si algo falla) e imprime las señales finales del
    gateway.
    """
    verificar_sistema()
    banner(f"{nombre.upper()} — nivel {objetivo}: {nodos} nodos x bloques de {bloque}, ventana {duracion_seg}s")
    print("Ampliando el rate limit del gateway para la prueba...")
    ampliar_rate_limit()
    try:
        correr_runner(
            "carga_nodos.py",
            "--nodos", nodos, "--bloque", bloque, "--duracion-seg", duracion_seg,
            "--ruta", "api/v1/tickets/tickets/", "--objetivo", objetivo,
            "--usuario", "admin", "--password", "admin123",
            "--nombre", nombre, "--salida", RESULTADOS,
        )
    finally:
        restaurar_rate_limit()

    circuit_tickets = metrica_gateway('gateway_circuit_state{service="tickets"}')
    bulkhead_tickets = metrica_gateway('gateway_bulkhead_rejects_total{razon="saturado",service="tickets"}')
    reintentos = metrica_gateway('gateway_retries_total{service="tickets"}')
    muestreados = metrica_gateway("gateway_logs_sampled_total")

    print()
    print("--- Señales del gateway al final ---")
    print(f"  circuit_state tickets: {circuit_tickets}  (0=CLOSED)")
    print(f"  bulkhead rechazos (saturado): {bulkhead_tickets}")
    print(f"  reintentos: {reintentos}")
    print(f"  logs muestreados: {muestreados}")

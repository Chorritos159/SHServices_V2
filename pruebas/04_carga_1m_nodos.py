"""
04_carga_1m_nodos.py — Prueba de carga masiva: 1,000,000 de peticiones desde 10 "nodos".

Versión extrema de 03_carga_500k_nodos.py con más nodos, bloques más grandes y
pausas más cortas, pensada para forzar el Circuit Breaker o el pool de la BD.

[!] Muy pesada: solo ejecutar con la máquina dedicada a la prueba (usa mucha CPU/RAM
y puede saturar el host, no solo los contenedores).
Uso: python pruebas/04_carga_1m_nodos.py
"""
import asyncio
import aiohttp
import multiprocessing
import time
import random

AUTH_URL = "http://localhost:8003"
GATEWAY_URL = "http://localhost:8000"
TOTAL_PETICIONES = 1_000_000
NODOS = 10
PETICIONES_POR_NODO = TOTAL_PETICIONES // NODOS
BLOQUE_SIZE = 10000


async def enviar_bloque(session, token, tamano_bloque, id_nodo):
    headers = {"Authorization": f"Bearer {token}"}
    tareas = []
    for i in range(tamano_bloque):
        ticket_data = {
            "datosCliente": f"MegaStress {id_nodo}-{i}",
            "documento_cliente": f"72{id_nodo:02d}{i % 999999:06d}",
            "telefono_cliente": "922222222",
            "tipoOperacion": "VENTA",
            "prioridad": "BAJA",
        }
        tareas.append(session.post(f"{GATEWAY_URL}/api/v1/tickets/tickets/", json=ticket_data, headers=headers))
    return await asyncio.gather(*tareas, return_exceptions=True)


async def nodo_worker(id_nodo):
    print(f"[MegaNodo {id_nodo}] Iniciando worker. Total a procesar: {PETICIONES_POR_NODO}")

    connector = aiohttp.TCPConnector(limit=10000)
    async with aiohttp.ClientSession(connector=connector) as session:
        login_data = {"usuario": "admin", "password": "admin123"}
        async with session.post(f"{AUTH_URL}/api/v1/auth/login", json=login_data) as resp:
            if resp.status != 200:
                print(f"[MegaNodo {id_nodo}] Error de login")
                return
            token = (await resp.json())["access_token"]

        enviados = 0
        while enviados < PETICIONES_POR_NODO:
            faltantes = PETICIONES_POR_NODO - enviados
            actual_bloque = min(BLOQUE_SIZE, faltantes)
            print(f"[MegaNodo {id_nodo}] Disparando bloque de {actual_bloque} peticiones... ({enviados}/{PETICIONES_POR_NODO})")
            await enviar_bloque(session, token, actual_bloque, id_nodo)
            enviados += actual_bloque
            await asyncio.sleep(random.uniform(0.1, 1.0))

    print(f"[MegaNodo {id_nodo}] Finalizó su carga.")


def iniciar_nodo(id_nodo):
    asyncio.run(nodo_worker(id_nodo))


if __name__ == "__main__":
    print(f"=== INICIANDO PRUEBA MASIVA: {TOTAL_PETICIONES} PETICIONES DESDE {NODOS} NODOS ===")
    print("Observa 'Tasa de error 5xx' y 'Cortes Circuit Breaker' en Grafana en tiempo real.")
    procesos = [multiprocessing.Process(target=iniciar_nodo, args=(i + 1,)) for i in range(NODOS)]

    start_time = time.time()
    for p in procesos:
        p.start()
    for p in procesos:
        p.join()

    print(f"=== PRUEBA MILLONARIA FINALIZADA EN {time.time() - start_time:.2f} SEGUNDOS ===")

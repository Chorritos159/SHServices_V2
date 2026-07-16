"""
03_carga_500k_nodos.py — Prueba de carga distribuida: 500,000 peticiones desde 5 "nodos".

Simula 5 procesos concurrentes (multiprocessing) golpeando el Gateway en bloques,
para observar saturación del pool de PostgreSQL, latencia y el Circuit Breaker en
el dashboard de Grafana bajo carga sostenida.

[!] Prueba pesada: puede tardar varios minutos y consumir CPU/RAM del host.
Uso: python pruebas/03_carga_500k_nodos.py
"""
import asyncio
import aiohttp
import multiprocessing
import time
import random

AUTH_URL = "http://localhost:8003"
GATEWAY_URL = "http://localhost:8000"
TOTAL_PETICIONES = 500_000
NODOS = 5
PETICIONES_POR_NODO = TOTAL_PETICIONES // NODOS
BLOQUE_SIZE = 5000


async def enviar_bloque(session, token, tamano_bloque, id_nodo):
    headers = {"Authorization": f"Bearer {token}"}
    tareas = []
    for i in range(tamano_bloque):
        ticket_data = {
            "datosCliente": f"Stress {id_nodo}-{i}",
            "documento_cliente": f"71{id_nodo:02d}{i % 999999:06d}",
            "telefono_cliente": "911111111",
            "tipoOperacion": "VENTA",
            "prioridad": "BAJA",
        }
        tareas.append(session.post(f"{GATEWAY_URL}/api/v1/tickets/tickets/", json=ticket_data, headers=headers))
    return await asyncio.gather(*tareas, return_exceptions=True)


async def nodo_worker(id_nodo):
    print(f"[Nodo {id_nodo}] Iniciando worker. Total a procesar: {PETICIONES_POR_NODO}")

    async with aiohttp.ClientSession() as session:
        login_data = {"usuario": "admin", "password": "admin123"}
        async with session.post(f"{AUTH_URL}/api/v1/auth/login", json=login_data) as resp:
            if resp.status != 200:
                print(f"[Nodo {id_nodo}] Error de login")
                return
            token = (await resp.json())["access_token"]

        enviados = 0
        while enviados < PETICIONES_POR_NODO:
            faltantes = PETICIONES_POR_NODO - enviados
            actual_bloque = min(BLOQUE_SIZE, faltantes)
            print(f"[Nodo {id_nodo}] Disparando bloque de {actual_bloque} peticiones... ({enviados}/{PETICIONES_POR_NODO})")
            await enviar_bloque(session, token, actual_bloque, id_nodo)
            enviados += actual_bloque
            await asyncio.sleep(random.uniform(0.5, 2.0))

    print(f"[Nodo {id_nodo}] Finalizó su carga.")


def iniciar_nodo(id_nodo):
    asyncio.run(nodo_worker(id_nodo))


if __name__ == "__main__":
    print(f"=== INICIANDO PRUEBA DE CARGA: {TOTAL_PETICIONES} PETICIONES DESDE {NODOS} NODOS ===")
    print("Sigue el panel 'Latencia p50/p95/p99' y 'Peticiones por status' en Grafana durante la corrida.")
    procesos = [multiprocessing.Process(target=iniciar_nodo, args=(i + 1,)) for i in range(NODOS)]

    start_time = time.time()
    for p in procesos:
        p.start()
    for p in procesos:
        p.join()

    print(f"=== PRUEBA FINALIZADA EN {time.time() - start_time:.2f} SEGUNDOS ===")

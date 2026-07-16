"""
02_carga_70_req.py — Carga concurrente moderada: 70 peticiones simultáneas.

Crea 70 tickets VENTA de golpe contra el Gateway para ver cómo responde bajo
concurrencia (útil para observar el panel de latencia p95/p99 en Grafana).

Uso: python pruebas/02_carga_70_req.py
"""
import asyncio
import aiohttp
import time

AUTH_URL = "http://localhost:8003"
GATEWAY_URL = "http://localhost:8000"
N_PETICIONES = 70


async def crear_ticket(session, idx, token):
    headers = {"Authorization": f"Bearer {token}"}
    ticket_data = {
        "datosCliente": f"Cliente {idx}",
        "documento_cliente": f"7000{idx:04d}",
        "telefono_cliente": "900000000",
        "tipoOperacion": "VENTA",
        "prioridad": "MEDIA",
    }
    try:
        async with session.post(f"{GATEWAY_URL}/api/v1/tickets/tickets/", json=ticket_data, headers=headers) as resp:
            return resp.status
    except Exception as e:
        return str(e)


async def main():
    print(f"Iniciando carga de {N_PETICIONES} peticiones simultáneas...")

    async with aiohttp.ClientSession() as session:
        login_data = {"usuario": "caja01", "password": "caja123"}
        async with session.post(f"{AUTH_URL}/api/v1/auth/login", json=login_data) as resp:
            if resp.status != 200:
                print("No se pudo obtener token:", resp.status, await resp.text())
                return
            token = (await resp.json())["access_token"]

        start_time = time.time()
        tareas = [crear_ticket(session, i, token) for i in range(N_PETICIONES)]
        resultados = await asyncio.gather(*tareas)
        elapsed = time.time() - start_time

        exitos = resultados.count(201)
        fallos = len(resultados) - exitos

        print(f"Prueba finalizada en {elapsed:.2f} segundos.")
        print(f"Éxitos (201): {exitos}")
        print(f"Fallos/otros: {fallos}  ->  {[r for r in resultados if r != 201][:10]}")


if __name__ == "__main__":
    asyncio.run(main())

"""
05_chaos_engineering.py — Chaos Monkey: mata y revive contenedores mientras
hay carga constante, para demostrar el Circuit Breaker del Gateway en vivo.

[!] Corrección importante respecto a la versión original: los nombres de los
contenedores usan GUION (docker-compose `container_name:`), no guion bajo.
`docker stop almacen_service` fallaba en silencio porque ese contenedor no
existe; el nombre real es `almacen-service`.

Mientras corre, abre el dashboard de Grafana ("SHServices · Resiliencia") y
mira el panel "Circuit Breaker por motivo" reaccionar a cada caída.

Uso: python pruebas/05_chaos_engineering.py
"""
import asyncio
import aiohttp
import subprocess
import time
import random
import multiprocessing

AUTH_URL = "http://localhost:8003"
GATEWAY_URL = "http://localhost:8000"
# Nombres REALES de contenedor (ver docker-compose.yml: container_name).
SERVICIOS_A_TIRAR = ["almacen-service", "ticket-service", "facturacion-service", "diagnostico-service"]


def matar_contenedor(servicio):
    print(f"\n[CHAOS] [!] Deteniendo contenedor: {servicio}...")
    r = subprocess.run(["docker", "stop", servicio], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[CHAOS] [FALLO] No se pudo detener {servicio}: {r.stderr.strip()}")
    else:
        print(f"[CHAOS] [STOP] {servicio} detenido.")


def revivir_contenedor(servicio):
    print(f"\n[CHAOS] [UP] Reiniciando contenedor: {servicio}...")
    r = subprocess.run(["docker", "start", servicio], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[CHAOS] [FALLO] No se pudo reiniciar {servicio}: {r.stderr.strip()}")
    else:
        print(f"[CHAOS] [OK] {servicio} operativo nuevamente.")


async def inyectar_carga_continua(token):
    headers = {"Authorization": f"Bearer {token}"}
    peticion_id = 0

    async with aiohttp.ClientSession() as session:
        while True:
            ticket_data = {
                "datosCliente": f"Chaos Client {peticion_id}",
                "documento_cliente": f"73{peticion_id % 999999:06d}",
                "telefono_cliente": "933333333",
                "tipoOperacion": "VENTA",
                "prioridad": "ALTA",
            }
            start = time.time()
            try:
                async with session.post(f"{GATEWAY_URL}/api/v1/tickets/tickets/", json=ticket_data, headers=headers) as resp:
                    status = resp.status
                    body = await resp.text()
            except Exception as e:
                status = str(e)
                body = ""

            latency = time.time() - start
            if status == 201:
                print(f"[Req {peticion_id}] [OK] Éxito ({latency:.2f}s)")
            else:
                print(f"[Req {peticion_id}] [FALLO] Fallo {status} ({latency:.2f}s): {body[:80]}")

            peticion_id += 1
            await asyncio.sleep(0.5)


def run_monkey(token):
    asyncio.run(inyectar_carga_continua(token))


if __name__ == "__main__":
    print("=== INICIANDO CHAOS ENGINEERING ===")
    print("Este script inyecta carga constante mientras apaga y enciende servicios al azar.")
    print("Abre http://localhost:3000 -> SHServices · Resiliencia para ver el efecto en vivo.\n")

    import requests
    login_data = {"usuario": "admin", "password": "admin123"}
    try:
        r = requests.post(f"{AUTH_URL}/api/v1/auth/login", json=login_data, timeout=10)
        token = r.json().get("access_token") if r.status_code == 200 else None
    except Exception:
        print("Fallo al contactar el auth-service para el token. ¿Está el stack arriba?")
        exit(1)

    if not token:
        print("No se pudo obtener el token inicial.")
        exit(1)

    p_carga = multiprocessing.Process(target=run_monkey, args=(token,))
    p_carga.start()

    try:
        for i in range(5):  # 5 ciclos de chaos
            time.sleep(5)
            victima = random.choice(SERVICIOS_A_TIRAR)

            matar_contenedor(victima)
            print("[CHAOS] Servicio caído por 10s -> observa el Circuit Breaker (503) en el dashboard.")
            time.sleep(10)

            revivir_contenedor(victima)
            print("[CHAOS] Esperando a que se estabilice (healthcheck)...")
            time.sleep(15)

    except KeyboardInterrupt:
        print("Cancelado por usuario.")

    finally:
        print("\n=== FINALIZANDO CHAOS ENGINEERING ===")
        p_carga.terminate()
        for s in SERVICIOS_A_TIRAR:
            subprocess.run(["docker", "start", s], capture_output=True, text=True)

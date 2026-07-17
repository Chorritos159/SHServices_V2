#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Ráfaga de concurrencia REAL (Fase 5, S34) para las fichas de caos que
necesitan saturar un bulkhead o un rate limit de verdad.

curl/xargs -P no sirve para esto: el overhead de arrancar N procesos
separados serializa la carga y nunca llega a solapar lo suficiente (lección
de la verificación de la Fase 2). httpx.AsyncClient con un pool compartido
sí genera peticiones genuinamente simultáneas.
"""
import asyncio
import collections
import sys
import httpx

GW = "http://localhost:8000"
AUTH_URL = "http://localhost:8003/api/v1/auth/login"


async def login(usuario="admin", password="admin123"):
    async with httpx.AsyncClient() as c:
        r = await c.post(AUTH_URL, json={"usuario": usuario, "password": password})
        return r.json()["access_token"]


async def hit(client, url, headers, resultados, metodo="GET", body=None):
    try:
        r = await client.request(metodo, url, headers=headers, json=body, timeout=10.0)
        resultados[r.status_code] += 1
    except Exception as e:
        resultados[f"error:{type(e).__name__}"] += 1


async def main():
    ruta = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    token = await login()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GW}/{ruta}"
    resultados = collections.Counter()
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=200)
    async with httpx.AsyncClient(limits=limits) as client:
        tareas = [hit(client, url, headers, resultados) for _ in range(n)]
        await asyncio.gather(*tareas)
    print(f"URL: {url}  N={n}")
    for codigo, cuenta in sorted(resultados.items(), key=lambda x: str(x[0])):
        print(f"  {codigo}: {cuenta}")


if __name__ == "__main__":
    asyncio.run(main())

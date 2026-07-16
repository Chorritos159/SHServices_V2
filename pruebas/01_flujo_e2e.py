"""
01_flujo_e2e.py — Prueba funcional del flujo COMPLETO del negocio.

CAJA crea ticket -> TECNICO diagnostica (reserva stock) -> transiciona a
DIAGNOSTICADO -> CAJA entrega (confirma stock + genera garantia) -> factura.

Requisitos: stack levantado (docker compose up -d).
Uso:        python pruebas/01_flujo_e2e.py
"""
import asyncio
import aiohttp

AUTH_URL = "http://localhost:8003"      # login va DIRECTO al auth-service (el Gateway bloquea /auth)
GATEWAY_URL = "http://localhost:8000"   # todo lo demas pasa por el Gateway


async def login(session, usuario, password):
    async with session.post(f"{AUTH_URL}/api/v1/auth/login", json={"usuario": usuario, "password": password}) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Login fallido para {usuario}: {resp.status} {await resp.text()}")
        return (await resp.json())["access_token"]


async def run_e2e():
    async with aiohttp.ClientSession() as session:
        print("1. Login (caja01, tecnico01, admin)...")
        tok_caja = await login(session, "caja01", "caja123")
        tok_tec = await login(session, "tecnico01", "tecnico123")
        tok_adm = await login(session, "admin", "admin123")
        print("   OK")

        H = lambda t: {"Authorization": f"Bearer {t}"}

        print("\n2. CAJA crea ticket SOPORTE (sede/usuario los inyecta el Gateway desde el JWT)...")
        ticket_data = {
            "datosCliente": "Juan Perez",
            "documento_cliente": "70111222",
            "telefono_cliente": "987654321",
            "tipoOperacion": "SOPORTE",
            "equipo": "Laptop Dell",
            "numero_serie": "SN-E2E-001",
            "caracteristicas_falla": "No enciende",
            "precio_estimado": 150.0,
            "prioridad": "ALTA",
        }
        async with session.post(f"{GATEWAY_URL}/api/v1/tickets/tickets/", json=ticket_data, headers=H(tok_caja)) as resp:
            ticket_res = await resp.json()
            print("   Ticket:", ticket_res)
            ticket_id = ticket_res["idTicket"]

        print("\n3. ADMIN ingresa stock en almacén (código autogenerado)...")
        stock_data = {"nombre": "Memoria RAM 8GB", "categoria": "REPUESTO", "sede": "PIURA", "stock_inicial": 100, "precio_unitario": 40.0}
        async with session.post(f"{GATEWAY_URL}/api/v1/almacen/almacen/productos", json=stock_data, headers=H(tok_adm)) as resp:
            producto = await resp.json()
            print("   Producto:", producto)
            codigo = producto["codigo"]

        print("\n4. TECNICO diagnostica (reserva el repuesto)...")
        diag_data = {
            "idTicket": ticket_id,
            "fallaDetectada": "Memoria dañada",
            "mano_obra": 50.0,
            "precio_reparacion": 90.0,
            "repuestos": [{"codigo_repuesto": codigo, "cantidad": 1, "precio_unitario": 40.0, "descripcion": "RAM 8GB"}],
        }
        async with session.post(f"{GATEWAY_URL}/api/v1/diagnosticos/diagnosticos/", json=diag_data, headers=H(tok_tec)) as resp:
            diag_res = await resp.json()
            print("   Diagnóstico:", diag_res)

        print("\n5. Transición de estado -> DIAGNOSTICADO (registra los repuestos en el ticket)...")
        async with session.post(
            f"{GATEWAY_URL}/api/v1/tickets/tickets/{ticket_id}/diagnosticar",
            json={"repuestos": [{"codigo_producto": codigo, "cantidad": 1}]},
            headers=H(tok_tec),
        ) as resp:
            print("   Estado:", (await resp.json()).get("estado"))

        print("\n6. CAJA entrega -> CONFIRMA stock + genera garantía de 90 días...")
        async with session.post(
            f"{GATEWAY_URL}/api/v1/tickets/tickets/{ticket_id}/entregar",
            json={"monto_total": 90.0},
            headers=H(tok_caja),
        ) as resp:
            entrega = await resp.json()
            print("   Entrega:", entrega)

        print("\n7. Emitiendo factura...")
        fact_data = {"idTicket": ticket_id, "montoManoObra": 50.0, "montoRepuestos": 40.0, "metodoPago": "TARJETA", "sede": "PIURA"}
        async with session.post(f"{GATEWAY_URL}/api/v1/facturas/facturas/", json=fact_data, headers=H(tok_caja)) as resp:
            fact_res = await resp.json()
            print("   Factura:", fact_res)

        print("\n[OK] Flujo E2E completado exitosamente.")


if __name__ == "__main__":
    asyncio.run(run_e2e())

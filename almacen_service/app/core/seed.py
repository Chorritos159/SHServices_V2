"""Seed de inventario base (idempotente).

Si la tabla `inventario` esta VACIA, siembra un catalogo inicial para que el
almacen no aparezca vacio en la demo (repuestos de reparacion + productos de
venta directa, en las dos sedes: PIURA y TALARA). Es idempotente: si ya hay
productos, no toca nada. Mismo patron que el seed de usuarios de auth.

Los codigos son secuenciales y globalmente unicos (REP-001, REP-002... para
repuestos; PRD-001... para productos de venta), porque la PK de la tabla es
solo `codigo`: el mismo producto en dos sedes lleva dos codigos distintos.
Asi `_siguiente_codigo()` del router continua la numeracion sin chocar.
"""
from app.core.database import SessionLocal
from app.core.logger import get_logger
from app.models.inventario import ProductoDB

logger = get_logger("almacen-service")

# (nombre, categoria, precio_venta, stock_por_sede)
_REPUESTOS = [
    ("Ventilador para laptop",   45.00, 20),
    ("Pantalla LCD 15.6 pulg",  280.00,  8),
    ("Teclado interno laptop",   60.00, 15),
    ("Bateria de laptop",       150.00, 12),
    ("Cargador universal 65W",   90.00, 25),
    ("Memoria RAM 8GB DDR4",    170.00, 18),
    ("Disco SSD 480GB",         210.00, 14),
    ("Pasta termica",            18.00, 40),
]
_PRODUCTOS_VENTA = [
    ("Mouse inalambrico",        55.00, 30),
    ("Teclado mecanico",        120.00, 20),
    ("Audifonos con microfono",  80.00, 25),
    ("Cable HDMI 2m",            25.00, 50),
]
_SEDES = ("PIURA", "TALARA")


def seed_inventario_base():
    db = SessionLocal()
    try:
        if db.query(ProductoDB).count() > 0:
            logger.evento("Seed de inventario omitido: ya existen productos.",
                          operation="seed_inventario", result="omitido")
            return

        productos = []
        rep_n = prd_n = 0
        for sede in _SEDES:
            for nombre, precio, stock in _REPUESTOS:
                rep_n += 1
                productos.append(ProductoDB(
                    codigo=f"REP-{rep_n:03d}", nombre=nombre, categoria="REPUESTO",
                    sede=sede, stock_disponible=stock, stock_reservado=0, precio_unitario=precio,
                ))
            for nombre, precio, stock in _PRODUCTOS_VENTA:
                prd_n += 1
                productos.append(ProductoDB(
                    codigo=f"PRD-{prd_n:03d}", nombre=nombre, categoria="PRODUCTO_VENTA",
                    sede=sede, stock_disponible=stock, stock_reservado=0, precio_unitario=precio,
                ))
        db.add_all(productos)
        db.commit()
        logger.evento(
            f"Seed de inventario aplicado: {len(productos)} productos "
            f"({len(_REPUESTOS) + len(_PRODUCTOS_VENTA)} por sede x {len(_SEDES)} sedes).",
            operation="seed_inventario", result="ok", totalProductos=len(productos),
        )
    finally:
        db.close()

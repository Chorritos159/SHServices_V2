from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from app.models.schemas import (
    ProductoCreate, ProductoResponse, ReservaRequest, ProductoInventario, VentaRequest,
)
from app.models.inventario import ProductoDB
from app.core.database import get_db
from app.core.logger import get_logger, NO_ENCONTRADO, RECHAZADO
from app.core.rabbitmq import publicar_evento

router = APIRouter()
logger = get_logger("almacen-service")


def _trazar(request: Request) -> str:
    """Toma el correlationId que inyecta el Gateway y lo fija en el logger."""
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    return correlation_id


@router.get("/productos", response_model=list[ProductoInventario], tags=["Inventario"])
async def listar_productos(request: Request, db: Annotated[Session, Depends(get_db)]):
    """Devuelve TODO el inventario (para que el Admin no este 'a ciegas')."""
    _trazar(request)
    with logger.operacion("listar_inventario") as op:
        productos = db.query(ProductoDB).order_by(ProductoDB.sede, ProductoDB.codigo).all()
        op.campos["totalProductos"] = len(productos)
        op.mensaje = f"Listado de inventario entregado: {len(productos)} producto(s)."
        return productos


@router.get("/productos/venta", response_model=list[ProductoInventario], tags=["Inventario"])
async def listar_productos_venta(request: Request, db: Annotated[Session, Depends(get_db)]):
    """Catálogo vendible para el POS de Caja: lo que ESTA sede puede vender hoy.

    Se diferencia de `GET /productos` (que devuelve todo el inventario, para el
    Admin) en tres cosas, y las tres son a propósito:

    - **La sede sale del token**, no de un parámetro. Si viniera por query, una
      cajera de PIURA podría pedir el catálogo de TALARA cambiando la URL y
      vender stock que no tiene delante. Es el mismo criterio que ya usa
      diagnostico-service al reservar repuestos.
    - Solo `PRODUCTO_VENTA`: los `REPUESTO` se consumen dentro de una
      reparación (van por reserva), no se venden sueltos en mostrador.
    - Solo con stock: no tiene sentido ofrecer lo que no se puede entregar.
    """
    _trazar(request)
    sede = request.headers.get("x-user-sede", "").upper()
    if not sede:
        raise HTTPException(
            status_code=401,
            detail="Tu token no trae la sede. Vuelve a iniciar sesion.",
        )

    with logger.operacion("listar_productos_venta", sede=sede) as op:
        productos = (
            db.query(ProductoDB)
            .filter(ProductoDB.sede == sede)
            .filter(ProductoDB.categoria == "PRODUCTO_VENTA")
            .filter(ProductoDB.stock_disponible > 0)
            .order_by(ProductoDB.nombre)
            .all()
        )
        op.campos["totalProductos"] = len(productos)
        op.mensaje = f"Catalogo de venta de {sede}: {len(productos)} producto(s) con stock."
        return productos


def _siguiente_codigo(db: Session, categoria: str) -> str:
    """Siguiente codigo secuencial, con el prefijo que corresponde a la categoria.

    `REP-` para repuestos y `PRD-` para productos de venta, cada uno con su
    propia secuencia. Antes todo nacia como `REP-`, asi que un artículo de
    mostrador terminaba llamandose `REP-321` y en el catalogo de venta parecia
    un repuesto: el codigo dejaba de decir la verdad sobre lo que es.
    """
    prefijo = "PRD" if categoria.upper() == "PRODUCTO_VENTA" else "REP"
    codigos = db.query(ProductoDB.codigo).filter(ProductoDB.codigo.like(f"{prefijo}-%")).all()
    numeros = []
    for (c,) in codigos:
        sufijo = c.split("-")[-1]
        if sufijo.isdigit():
            numeros.append(int(sufijo))
    siguiente = (max(numeros) + 1) if numeros else 1
    return f"{prefijo}-{siguiente:03d}"


@router.post("/productos", response_model=ProductoResponse, status_code=201, tags=["Inventario"])
async def crear_producto(
    producto: ProductoCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
):
    """Ingresa un producto nuevo al almacen. El codigo se autogenera (REP-001, REP-002...)."""
    correlation_id = _trazar(request)

    with logger.operacion("crear_producto", event="ProductoRegistrado.v1") as op:
        codigo = _siguiente_codigo(db, producto.categoria)
        nuevo_producto = ProductoDB(
            codigo=codigo,
            nombre=producto.nombre,
            categoria=producto.categoria.upper(),
            sede=producto.sede.upper(),
            stock_disponible=producto.stock_inicial,
            stock_reservado=0,
            precio_unitario=producto.precio_unitario,
        )
        db.add(nuevo_producto)
        db.commit()
        db.refresh(nuevo_producto)

        op.campos.update({
            "codigo": codigo,
            "sede": nuevo_producto.sede,
            "stockInicial": nuevo_producto.stock_disponible,
        })
        op.mensaje = f"Producto {codigo} ({producto.nombre}) ingresado en {nuevo_producto.sede}."

        # Emite ProductoRegistrado -> el servicio de notificaciones alerta al ADMIN.
        evento_payload = {
            "evento": "ProductoRegistrado.v1",
            "trace_id": correlation_id,
            "datos": {"codigo": codigo, "nombre": nuevo_producto.nombre, "sede": nuevo_producto.sede},
        }
        background_tasks.add_task(
            publicar_evento, exchange_name="tickets.eventos",
            routing_key="producto.registrado", mensaje=evento_payload,
        )
        return nuevo_producto


@router.post("/reservar", tags=["Operaciones Tecnicas"])
async def reservar_stock(reserva: ReservaRequest, request: Request, db: Annotated[Session, Depends(get_db)]):
    """Reserva un repuesto para una Orden de Servicio en una sede especifica."""
    _trazar(request)

    with logger.operacion(
        "reservar_stock",
        codigo=reserva.codigo_producto, sede=reserva.sede.upper(), cantidad=reserva.cantidad,
    ) as op:
        # Bloqueo pesimista: serializa reservas concurrentes (evita oversell).
        item = db.query(ProductoDB).filter(
            ProductoDB.codigo == reserva.codigo_producto,
            ProductoDB.sede == reserva.sede.upper(),
        ).with_for_update().first()

        if not item:
            op.result = NO_ENCONTRADO
            op.mensaje = f"Reserva rechazada: {reserva.codigo_producto} no existe en {reserva.sede.upper()}."
            raise HTTPException(
                status_code=404,
                detail=f"El repuesto '{reserva.codigo_producto}' no existe en la sede {reserva.sede.upper()}.",
            )

        if item.stock_disponible < reserva.cantidad:
            op.result = RECHAZADO
            op.campos["stockDisponible"] = item.stock_disponible
            op.mensaje = (f"Reserva rechazada por stock insuficiente de {item.codigo}: "
                          f"pedidas {reserva.cantidad}, disponibles {item.stock_disponible}.")
            raise HTTPException(
                status_code=409,
                detail=(f"Stock insuficiente de '{item.nombre}' en {item.sede}: "
                        f"se pidieron {reserva.cantidad} y hay {item.stock_disponible} disponible(s)."),
            )

        # Patron de reserva: mueve del disponible al reservado.
        item.stock_disponible -= reserva.cantidad
        item.stock_reservado += reserva.cantidad
        db.commit()

        op.campos["stockDisponible"] = item.stock_disponible
        op.mensaje = (f"Reservadas {reserva.cantidad}x {item.codigo} ({item.nombre}); "
                      f"quedan {item.stock_disponible} disponible(s).")
        return _estado_stock("RESERVA_CONFIRMADA", item)


def _buscar_bloqueado(db: Session, codigo: str, sede: str) -> ProductoDB:
    """Busca un producto con bloqueo pesimista (serializa movimientos concurrentes)."""
    item = db.query(ProductoDB).filter(
        ProductoDB.codigo == codigo,
        ProductoDB.sede == sede.upper(),
    ).with_for_update().first()
    if not item:
        raise HTTPException(
            status_code=404,
            detail=f"El repuesto '{codigo}' no existe en la sede {sede.upper()}.",
        )
    return item


def _estado_stock(status: str, item: ProductoDB) -> dict:
    return {
        "status": status,
        "producto": item.nombre,
        "sede": item.sede,
        "stock_disponible": item.stock_disponible,
        "stock_reservado": item.stock_reservado,
    }


@router.post("/confirmar", tags=["Operaciones de Stock"])
async def confirmar_stock(mov: ReservaRequest, request: Request, db: Annotated[Session, Depends(get_db)]):
    """FASE 2 del stock: CONSUME lo reservado (el repuesto sale fisicamente al entregar).

    Resta definitivamente de `stock_reservado`. No vuelve a `disponible`.
    """
    _trazar(request)
    with logger.operacion(
        "confirmar_stock", codigo=mov.codigo_producto, sede=mov.sede.upper(), cantidad=mov.cantidad,
    ) as op:
        item = _buscar_bloqueado(db, mov.codigo_producto, mov.sede)

        if item.stock_reservado < mov.cantidad:
            op.result = RECHAZADO
            op.campos["stockReservado"] = item.stock_reservado
            op.mensaje = (f"Confirmacion rechazada de {item.codigo}: se pidieron {mov.cantidad} "
                          f"y solo hay {item.stock_reservado} reservada(s).")
            raise HTTPException(
                status_code=409,
                detail=(f"No hay suficiente stock reservado de '{item.nombre}' para confirmar: "
                        f"se pidieron {mov.cantidad} y hay {item.stock_reservado} reservada(s)."),
            )

        item.stock_reservado -= mov.cantidad
        db.commit()
        op.campos["stockReservado"] = item.stock_reservado
        op.mensaje = (f"Consumidas {mov.cantidad}x {item.codigo} al entregar; "
                      f"quedan {item.stock_reservado} reservada(s).")
        return _estado_stock("STOCK_CONFIRMADO", item)


@router.post("/liberar", tags=["Operaciones de Stock"])
async def liberar_stock(mov: ReservaRequest, request: Request, db: Annotated[Session, Depends(get_db)]):
    """Devuelve lo reservado a disponible (el cliente RECHAZO el presupuesto).

    Mueve `reservado -> disponible`.
    """
    _trazar(request)
    with logger.operacion(
        "liberar_stock", codigo=mov.codigo_producto, sede=mov.sede.upper(), cantidad=mov.cantidad,
    ) as op:
        item = _buscar_bloqueado(db, mov.codigo_producto, mov.sede)

        if item.stock_reservado < mov.cantidad:
            op.result = RECHAZADO
            op.campos["stockReservado"] = item.stock_reservado
            op.mensaje = (f"Liberacion rechazada de {item.codigo}: se pidieron {mov.cantidad} "
                          f"y solo hay {item.stock_reservado} reservada(s).")
            raise HTTPException(
                status_code=409,
                detail=(f"No hay suficiente stock reservado de '{item.nombre}' para liberar: "
                        f"se pidieron {mov.cantidad} y hay {item.stock_reservado} reservada(s)."),
            )

        item.stock_reservado -= mov.cantidad
        item.stock_disponible += mov.cantidad
        db.commit()
        op.campos["stockDisponible"] = item.stock_disponible
        op.mensaje = (f"Liberadas {mov.cantidad}x {item.codigo} al rechazar el presupuesto; "
                      f"disponibles: {item.stock_disponible}.")
        return _estado_stock("STOCK_LIBERADO", item)


@router.post("/descontar", tags=["Operaciones de Stock"])
async def descontar_stock(mov: ReservaRequest, request: Request, db: Annotated[Session, Depends(get_db)]):
    """VENTA DIRECTA de UNA línea: descuenta de golpe de `disponible`.

    No pasa por reserva. Para una venta de mostrador con varias líneas usa
    `POST /venta`, que las descuenta todas en una sola transacción.
    """
    _trazar(request)
    with logger.operacion(
        "descontar_stock", codigo=mov.codigo_producto, sede=mov.sede.upper(), cantidad=mov.cantidad,
    ) as op:
        item = _buscar_bloqueado(db, mov.codigo_producto, mov.sede)

        if item.stock_disponible < mov.cantidad:
            op.result = RECHAZADO
            op.campos["stockDisponible"] = item.stock_disponible
            op.mensaje = (f"Venta rechazada por stock insuficiente de {item.codigo}: "
                          f"pedidas {mov.cantidad}, disponibles {item.stock_disponible}.")
            raise HTTPException(
                status_code=409,
                detail=(f"Stock insuficiente de '{item.nombre}' para la venta: "
                        f"se pidieron {mov.cantidad} y hay {item.stock_disponible} disponible(s)."),
            )

        item.stock_disponible -= mov.cantidad
        db.commit()
        op.campos["stockDisponible"] = item.stock_disponible
        op.mensaje = (f"Venta directa: descontadas {mov.cantidad}x {item.codigo}; "
                      f"disponibles: {item.stock_disponible}.")
        return _estado_stock("STOCK_DESCONTADO", item)


@router.post("/venta", tags=["Operaciones de Stock"])
async def descontar_venta(venta: VentaRequest, request: Request, db: Annotated[Session, Depends(get_db)]):
    """VENTA DE MOSTRADOR: descuenta TODAS las líneas del carrito, o ninguna.

    Es el endpoint que usa el POS de Caja. Frente a llamar N veces a
    `/descontar`, aquí el descuento es **atómico**: se bloquean las N filas,
    se valida el stock de todas y solo entonces se hace UN commit. Si la
    tercera línea no tiene stock, las dos primeras no llegaron a salir del
    inventario y no hay nada que compensar desde fuera.

    La `sede` sale del token (`X-User-Sede`), nunca del cuerpo: quien vende
    solo puede mover el stock que tiene físicamente delante.
    """
    _trazar(request)
    sede = request.headers.get("x-user-sede", "").upper()
    if not sede:
        raise HTTPException(
            status_code=401,
            detail="Tu token no trae la sede. Vuelve a iniciar sesion.",
        )

    with logger.operacion(
        "descontar_venta", sede=sede, lineas=len(venta.lineas),
    ) as op:
        # 1. Bloquear y validar TODAS antes de tocar nada. Se ordenan por código
        #    para que dos ventas concurrentes tomen los locks en el mismo orden
        #    y no se abracen (deadlock).
        items: list[tuple[ProductoDB, int]] = []
        for linea in sorted(venta.lineas, key=lambda x: x.codigo_producto):
            item = _buscar_bloqueado(db, linea.codigo_producto, sede)
            if item.categoria != "PRODUCTO_VENTA":
                op.result = RECHAZADO
                op.mensaje = f"Venta rechazada: {item.codigo} es {item.categoria}, no es vendible en mostrador."
                raise HTTPException(
                    status_code=409,
                    detail=(f"'{item.nombre}' es un {item.categoria.lower()} y no se vende "
                            "suelto en mostrador; se consume dentro de una reparacion."),
                )
            if item.stock_disponible < linea.cantidad:
                op.result = RECHAZADO
                op.campos["stockDisponible"] = item.stock_disponible
                op.mensaje = (f"Venta rechazada por stock insuficiente de {item.codigo}: "
                              f"pedidas {linea.cantidad}, disponibles {item.stock_disponible}.")
                raise HTTPException(
                    status_code=409,
                    detail=(f"Stock insuficiente de '{item.nombre}' en {sede}: se pidieron "
                            f"{linea.cantidad} y hay {item.stock_disponible} disponible(s)."),
                )
            items.append((item, linea.cantidad))

        # 2. Ninguna falló: ahora sí se descuentan todas y se confirma una vez.
        for item, cantidad in items:
            item.stock_disponible -= cantidad
        db.commit()

        detalle = [
            {"codigo": item.codigo, "producto": item.nombre, "vendidas": cantidad,
             "stock_disponible": item.stock_disponible}
            for item, cantidad in items
        ]
        unidades = sum(c for _, c in items)
        op.campos.update({"unidades": unidades, "productos": len(items)})
        op.mensaje = (f"Venta de mostrador en {sede}: {unidades} unidad(es) de "
                      f"{len(items)} producto(s) descontadas del inventario.")
        return {"status": "STOCK_DESCONTADO", "sede": sede, "lineas": detalle}

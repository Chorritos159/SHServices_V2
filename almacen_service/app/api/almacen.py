from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.models.schemas import ProductoCreate, ProductoResponse, ReservaRequest, ProductoInventario
from app.models.inventario import ProductoDB
from app.core.database import get_db
from app.core.logger import get_logger

router = APIRouter()
logger = get_logger("almacen-service")

@router.get("/productos", response_model=list[ProductoInventario], tags=["Inventario"])
async def listar_productos(request: Request, db: Session = Depends(get_db)):
    """Devuelve TODO el inventario (para que el Admin no esté 'a ciegas')."""
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id

    productos = (
        db.query(ProductoDB)
        .order_by(ProductoDB.sede, ProductoDB.codigo)
        .all()
    )
    logger.info(f"📋 Listado de inventario solicitado: {len(productos)} productos.")
    return productos


def _siguiente_codigo(db: Session) -> str:
    """Genera el siguiente código secuencial REP-NNN mirando el máximo existente."""
    codigos = db.query(ProductoDB.codigo).filter(ProductoDB.codigo.like("REP-%")).all()
    numeros = []
    for (c,) in codigos:
        sufijo = c.split("-")[-1]
        if sufijo.isdigit():
            numeros.append(int(sufijo))
    siguiente = (max(numeros) + 1) if numeros else 1
    return f"REP-{siguiente:03d}"


@router.post("/productos", response_model=ProductoResponse, status_code=201, tags=["Inventario"])
async def crear_producto(producto: ProductoCreate, request: Request, db: Session = Depends(get_db)):
    """Ingresa un producto nuevo al almacén. El código se autogenera (REP-001, REP-002…)."""
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id

    codigo = _siguiente_codigo(db)
    nuevo_producto = ProductoDB(
        codigo=codigo,
        nombre=producto.nombre,
        categoria=producto.categoria.upper(),
        sede=producto.sede.upper(),
        stock_disponible=producto.stock_inicial,
        stock_reservado=0,
    )
    db.add(nuevo_producto)
    db.commit()
    db.refresh(nuevo_producto)
    logger.info(f"📦 Producto {codigo} ({producto.nombre}) creado en {nuevo_producto.sede}.")
    return nuevo_producto


@router.post("/reservar", tags=["Operaciones Técnicas"])
async def reservar_stock(reserva: ReservaRequest, request: Request, db: Session = Depends(get_db)):
    """Reserva un repuesto para una Orden de Servicio en una sede específica."""
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    
    logger.info(f"Solicitud de reserva: {reserva.cantidad} unidades de {reserva.codigo_producto} en {reserva.sede}")

    # Buscar el repuesto en la sede solicitada
    item = db.query(ProductoDB).filter(
        ProductoDB.codigo == reserva.codigo_producto,
        ProductoDB.sede == reserva.sede.upper()
    ).with_for_update().first()   # bloqueo pesimista: serializa reservas concurrentes (evita oversell)

    if not item:
        logger.error(f"❌ Reserva fallida: El producto {reserva.codigo_producto} no existe en {reserva.sede}")
        raise HTTPException(status_code=404, detail="Producto No Encontrado en esta sede.")

    # Verificar si hay suficiente stock disponible
    if item.stock_disponible < reserva.cantidad:
        logger.error(f"❌ Stock insuficiente de {item.codigo} en {reserva.sede}. Requerido: {reserva.cantidad}, Disponible: {item.stock_disponible}")
        raise HTTPException(status_code=400, detail="Stock Insuficiente para realizar la reserva.")

    # Aplicar patrón de reserva: Movemos del disponible al reservado
    item.stock_disponible -= reserva.cantidad
    item.stock_reservado += reserva.cantidad
    db.commit()
    
    logger.info(f"🔒 Reserva exitosa de {reserva.cantidad} {item.nombre}. Quedan {item.stock_disponible} disponibles.")
    return {
        "status": "RESERVA_CONFIRMADA",
        "producto": item.nombre,
        "sede": item.sede,
        "stock_disponible_restante": item.stock_disponible,
        "stock_bloqueado_reserva": item.stock_reservado
    }
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.models.schemas import ProductoCreate, ProductoResponse, ReservaRequest
from app.models.inventario import ProductoDB
from app.core.database import get_db
from app.core.logger import get_logger

router = APIRouter()
logger = get_logger("almacen-service")

@router.post("/productos", response_model=ProductoResponse, status_code=201, tags=["Inventario"])
async def crear_o_actualizar_producto(producto: ProductoCreate, request: Request, db: Session = Depends(get_db)):
    """Ingresa un nuevo lote de repuestos o productos al almacén de una sede."""
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    
    logger.info(f"Registrando inventario: {producto.nombre} en la sede {producto.sede}")

    # Verificar si el producto ya existe en esa sede
    producto_existente = db.query(ProductoDB).filter(
        ProductoDB.codigo == producto.codigo, 
        ProductoDB.sede == producto.sede
    ).first()

    if producto_existente:
        # Si existe, sumamos al stock disponible
        producto_existente.stock_disponible += producto.stock_inicial
        db.commit()
        db.refresh(producto_existente)
        logger.info(f"🔄 Stock actualizado para {producto.codigo}. Nuevo disponible: {producto_existente.stock_disponible}")
        return producto_existente

    # Si no existe, lo creamos desde cero
    nuevo_producto = ProductoDB(
        codigo=producto.codigo,
        nombre=producto.nombre,
        categoria=producto.categoria.upper(),
        sede=producto.sede.upper(),
        stock_disponible=producto.stock_inicial,
        stock_reservado=0
    )
    db.add(nuevo_producto)
    db.commit()
    db.refresh(nuevo_producto)
    logger.info(f"📦 Nuevo producto {producto.codigo} guardado en el inventario de {producto.sede}.")
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
    ).first()

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
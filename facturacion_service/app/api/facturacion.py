from fastapi import APIRouter, Depends, Request, BackgroundTasks
from sqlalchemy.orm import Session
import uuid
import json
from app.models.schemas import FacturaCreate, FacturaResponse
from app.models.factura import FacturaDB
from app.core.database import get_db
from app.core.logger import get_logger
from app.core.rabbitmq import publicar_evento

router = APIRouter()
logger = get_logger("facturacion-service")

@router.post("/", response_model=FacturaResponse, status_code=201, tags=["Facturación"])
async def emitir_comprobante(
    factura: FacturaCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id

    logger.info(f"Procesando cobro para el ticket {factura.idTicket} en la sede {factura.sede}")

    # 1. Detalle de líneas (POS): calcula subtotales y su total.
    lineas_out = []
    monto_lineas = 0.0
    for linea in factura.lineas:
        subtotal = round(linea.cantidad * linea.precio_unitario, 2)
        monto_lineas += subtotal
        lineas_out.append({**linea.model_dump(), "subtotal": subtotal})

    # 2. Total = mano de obra (SOPORTE) + repuestos (SOPORTE) + líneas (VENTA directa).
    total_calculado = round(factura.montoManoObra + factura.montoRepuestos + monto_lineas, 2)

    # 3. Generar el número de comprobante único.
    id_factura = f"FAC-{factura.sede[:3].upper()}-{str(uuid.uuid4())[:4].upper()}"

    # 4. Guardar en PostgreSQL (con el detalle serializado).
    nueva_factura = FacturaDB(
        id=id_factura,
        id_ticket=factura.idTicket,
        monto_mano_obra=factura.montoManoObra,
        monto_repuestos=factura.montoRepuestos,
        monto_total=total_calculado,
        metodo_pago=factura.metodoPago.upper(),
        detalle_json=json.dumps(lineas_out, ensure_ascii=False),
    )
    db.add(nueva_factura)
    db.commit()
    db.refresh(nueva_factura)
    logger.info(f"💾 Comprobante {id_factura} guardado por S/.{total_calculado} ({len(lineas_out)} línea(s)).")

    # 5. Coreografía asíncrona: avisar que se cobró con éxito.
    evento_payload = {
        "evento": "FacturaGenerada.v1",
        "trace_id": correlation_id,
        "datos": {
            "idFactura": id_factura,
            "idTicket": factura.idTicket,
            "montoTotal": total_calculado,
            "sede": factura.sede,
        },
    }
    background_tasks.add_task(
        publicar_evento,
        exchange_name="tickets.eventos",
        routing_key="ticket.facturado",
        mensaje=evento_payload,
    )

    return FacturaResponse(
        idFactura=id_factura,
        idTicket=factura.idTicket,
        montoManoObra=factura.montoManoObra,
        montoRepuestos=factura.montoRepuestos,
        montoLineas=round(monto_lineas, 2),
        montoTotal=total_calculado,
        lineas=lineas_out,
        fechaEmision=nueva_factura.fecha_emision.isoformat() + "Z",
        estadoPago="PAGADO",
    )

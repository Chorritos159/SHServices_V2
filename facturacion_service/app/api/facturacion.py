from fastapi import APIRouter, Depends, Request, BackgroundTasks
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import time
import uuid
import json
from app.models.schemas import FacturaCreate, FacturaResponse
from app.models.factura import FacturaDB
from app.core.database import get_db
from app.core.logger import get_logger
from app.core.rabbitmq import publicar_evento

router = APIRouter()
logger = get_logger("facturacion-service")


def _respuesta_desde_db(f: FacturaDB) -> FacturaResponse:
    return FacturaResponse(
        idFactura=f.id,
        idTicket=f.id_ticket,
        montoManoObra=f.monto_mano_obra,
        montoRepuestos=f.monto_repuestos,
        montoLineas=round(sum(l.get("subtotal", 0) for l in json.loads(f.detalle_json or "[]")), 2),
        montoTotal=f.monto_total,
        lineas=json.loads(f.detalle_json or "[]"),
        fechaEmision=f.fecha_emision.isoformat() + "Z",
        estadoPago="PAGADO",
    )


@router.post("/", response_model=FacturaResponse, status_code=201, tags=["Facturación"])
async def emitir_comprobante(
    factura: FacturaCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    inicio = time.monotonic()

    logger.info(f"Procesando cobro para el ticket {factura.idTicket} en la sede {factura.sede}")

    # Idempotencia (S34, clave natural): un ticket tiene, a lo sumo, UNA
    # factura. Si ya existe (reintento del cliente, retry del gateway,
    # doble clic), se devuelve la MISMA respuesta en vez de duplicar el
    # cobro — la unicidad de id_ticket en la tabla es la garantía dura;
    # esta consulta previa solo evita el ruido de una excepción de BD en
    # el camino esperado.
    existente = db.query(FacturaDB).filter(FacturaDB.id_ticket == factura.idTicket).first()
    if existente:
        logger.info(
            f"Factura ya existía para el ticket {factura.idTicket} ({existente.id}); "
            "se devuelve la existente (idempotencia).",
            extra={"campos": {"operation": "emitir_comprobante", "event": "FacturaGenerada.v1",
                               "result": "duplicado", "durationMs": round((time.monotonic() - inicio) * 1000, 1),
                               "idTicket": factura.idTicket, "idFactura": existente.id}},
        )
        return _respuesta_desde_db(existente)

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
    try:
        db.commit()
    except IntegrityError:
        # Carrera: dos requests concurrentes para el mismo ticket pasaron el
        # chequeo previo antes de que cualquiera hiciera commit. La unicidad
        # de la BD es la garantía real; se resuelve igual que el camino normal.
        db.rollback()
        existente = db.query(FacturaDB).filter(FacturaDB.id_ticket == factura.idTicket).first()
        logger.warning(
            f"Carrera de idempotencia resuelta para el ticket {factura.idTicket}; se devuelve {existente.id}.",
            extra={"campos": {"operation": "emitir_comprobante", "event": "FacturaGenerada.v1",
                               "result": "duplicado_carrera", "durationMs": round((time.monotonic() - inicio) * 1000, 1),
                               "idTicket": factura.idTicket}},
        )
        return _respuesta_desde_db(existente)
    db.refresh(nueva_factura)
    duracion_ms = round((time.monotonic() - inicio) * 1000, 1)
    logger.info(
        f"Comprobante {id_factura} guardado por S/.{total_calculado} ({len(lineas_out)} línea(s)).",
        extra={"campos": {"operation": "emitir_comprobante", "event": "FacturaGenerada.v1",
                           "result": "ok", "durationMs": duracion_ms,
                           "idTicket": factura.idTicket, "idFactura": id_factura}},
    )

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

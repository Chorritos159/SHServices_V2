from fastapi import APIRouter, Depends, Request, BackgroundTasks
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import uuid
import json
from app.models.schemas import FacturaCreate, FacturaResponse
from app.models.factura import FacturaDB
from app.core.database import get_db
from app.core.logger import get_logger, DUPLICADO
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

    with logger.operacion(
        "emitir_comprobante", event="FacturaGenerada.v1",
        idTicket=factura.idTicket, sede=factura.sede,
    ) as op:
        # Idempotencia (S34, clave natural): un ticket tiene, a lo sumo, UNA
        # factura. Si ya existe (reintento del cliente, retry del gateway,
        # doble clic), se devuelve la MISMA respuesta en vez de duplicar el
        # cobro. La unicidad de id_ticket en la tabla es la garantia dura;
        # esta consulta previa solo evita el ruido de una excepcion de BD en
        # el camino esperado.
        existente = db.query(FacturaDB).filter(FacturaDB.id_ticket == factura.idTicket).first()
        if existente:
            op.result = DUPLICADO
            op.campos["idFactura"] = existente.id
            op.mensaje = (f"Factura ya existia para el ticket {factura.idTicket} ({existente.id}); "
                          "se devuelve la existente (idempotencia).")
            return _respuesta_desde_db(existente)

        # 1. Detalle de lineas (POS): calcula subtotales y su total.
        lineas_out = []
        monto_lineas = 0.0
        for linea in factura.lineas:
            subtotal = round(linea.cantidad * linea.precio_unitario, 2)
            monto_lineas += subtotal
            lineas_out.append({**linea.model_dump(), "subtotal": subtotal})

        # 2. Total = mano de obra (SOPORTE) + repuestos (SOPORTE) + lineas (VENTA directa).
        total_calculado = round(factura.montoManoObra + factura.montoRepuestos + monto_lineas, 2)

        # 3. Generar el numero de comprobante unico.
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
            # Carrera: dos requests concurrentes para el mismo ticket pasaron
            # el chequeo previo antes de que cualquiera hiciera commit. La
            # unicidad de la BD es la garantia real; se resuelve igual.
            db.rollback()
            existente = db.query(FacturaDB).filter(FacturaDB.id_ticket == factura.idTicket).first()
            op.result = DUPLICADO
            op.campos["idFactura"] = existente.id
            op.mensaje = (f"Carrera de idempotencia resuelta para el ticket {factura.idTicket}; "
                          f"se devuelve {existente.id}.")
            return _respuesta_desde_db(existente)

        db.refresh(nueva_factura)
        op.campos.update({"idFactura": id_factura, "montoTotal": total_calculado,
                          "lineas": len(lineas_out), "metodoPago": factura.metodoPago.upper()})
        op.mensaje = (f"Comprobante {id_factura} emitido por S/.{total_calculado} "
                      f"({len(lineas_out)} linea(s), {factura.metodoPago.upper()}).")

        # 5. Coreografia asincrona: avisar que se cobro con exito.
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

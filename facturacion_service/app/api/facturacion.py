from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
import uuid
import json
from app.models.schemas import FacturaCreate, FacturaResponse
from app.models.factura import FacturaDB
from app.models.garantia import GarantiaDB
from app.core.database import get_db
from app.core.logger import get_logger, DUPLICADO, ERROR
from app.core.rabbitmq import publicar_evento

router = APIRouter()
logger = get_logger("facturacion-service")

DIAS_GARANTIA = 90


def _crear_garantia(db: Session, factura: FacturaCreate, monto_total: float):
    """Emite la GARANTÍA de 90 días junto con el cobro (solo SOPORTE).

    Vive aquí (y no en ticket-service) porque la garantía respalda lo COBRADO.
    Idempotente: si el ticket ya tenía garantía, no crea otra.
    """
    if (factura.tipoOperacion or "").upper() != "SOPORTE":
        return None
    ya = db.query(GarantiaDB).filter(GarantiaDB.id_ticket == factura.idTicket).first()
    if ya:
        return ya
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    garantia = GarantiaDB(
        id=f"GAR-{factura.sede[:3].upper()}-{uuid.uuid4().hex[:12].upper()}",
        id_ticket=factura.idTicket,
        documento_cliente=factura.documentoCliente,
        equipo=factura.equipo,
        numero_serie=factura.numeroSerie,
        descripcion=factura.descripcion,
        fecha_entrega=ahora,
        fecha_vencimiento=ahora + timedelta(days=DIAS_GARANTIA),
        dias=DIAS_GARANTIA,
        monto_total=monto_total,
    )
    db.add(garantia)
    return garantia


def _respuesta_desde_db(f: FacturaDB, db: Session = None) -> FacturaResponse:
    garantia = None
    if db is not None:
        garantia = db.query(GarantiaDB).filter(GarantiaDB.id_ticket == f.id_ticket).first()
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
        idGarantia=garantia.id if garantia else None,
        garantiaVence=garantia.fecha_vencimiento.isoformat() + "Z" if garantia else None,
    )


@router.get("/", tags=["Facturación"])
async def listar_facturas(db: Annotated[Session, Depends(get_db)], limite: int = 200):
    """Listado de comprobantes, el mas reciente primero.

    Existe para la vista "Consulta de Garantias y Facturas": las VENTAS de
    mostrador no emiten garantia (solo el SOPORTE la lleva), asi que sin este
    listado una venta hecha con ticket-service caido —cuya factura referencia
    un id VENTA-XXX propio— no aparecia en ninguna consulta del panel.
    """
    limite = max(1, min(limite, 500))
    filas = (db.query(FacturaDB).order_by(FacturaDB.fecha_emision.desc())
             .limit(limite).all())
    return [{
        "idFactura": f.id, "idTicket": f.id_ticket,
        "montoTotal": f.monto_total, "metodoPago": f.metodo_pago,
        "fechaEmision": f.fecha_emision.isoformat() if f.fecha_emision else None,
        "esVenta": (f.id_ticket or "").startswith("VENTA-"),
    } for f in filas]


@router.post("/", response_model=FacturaResponse, status_code=201, tags=["Facturación"])
async def emitir_comprobante(
    factura: FacturaCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)]
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
            resp = _respuesta_desde_db(existente, db)
            db.close()
            return resp

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
        id_factura = f"FAC-{factura.sede[:3].upper()}-{uuid.uuid4().hex[:12].upper()}"

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
        except IntegrityError as exc:
            # Carrera: dos requests concurrentes para el mismo ticket pasaron
            # el chequeo previo antes de que cualquiera hiciera commit. La
            # unicidad de la BD es la garantia real; se resuelve igual.
            db.rollback()
            existente = db.query(FacturaDB).filter(FacturaDB.id_ticket == factura.idTicket).first()

            # `existente` PUEDE ser None y hay que decirlo, no darlo por hecho:
            # este bloque solo sabe manejar el choque contra la unicidad de
            # id_ticket, pero un IntegrityError tambien lo lanza cualquier otra
            # restriccion (un NOT NULL, una FK). En esos casos no hay factura
            # previa que devolver y el `existente.id` reventaba con
            # "'NoneType' object has no attribute 'id'" -> 500 opaco.
            # Aparecio 1 vez en la corrida de auto-recuperacion bajo carga.
            if existente is None:
                op.result = ERROR
                op.mensaje_error = (f"IntegrityError al cobrar el ticket {factura.idTicket} "
                                    f"que NO es una carrera de idempotencia: {exc.orig}")
                raise HTTPException(
                    status_code=409,
                    detail=("No se pudo registrar el cobro por un conflicto de datos. "
                            "Revisa que el ticket y los importes sean correctos."),
                )

            op.result = DUPLICADO
            op.campos["idFactura"] = existente.id
            op.mensaje = (f"Carrera de idempotencia resuelta para el ticket {factura.idTicket}; "
                          f"se devuelve {existente.id}.")
            resp = _respuesta_desde_db(existente, db)
            db.close()
            return resp

        db.refresh(nueva_factura)

        # Garantia de 90 dias emitida junto con el cobro (solo SOPORTE).
        garantia = _crear_garantia(db, factura, total_calculado)
        if garantia is not None:
            db.commit()
            db.refresh(garantia)

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

        resp = FacturaResponse(
            idFactura=id_factura,
            idTicket=factura.idTicket,
            montoManoObra=factura.montoManoObra,
            montoRepuestos=factura.montoRepuestos,
            montoLineas=round(monto_lineas, 2),
            montoTotal=total_calculado,
            lineas=lineas_out,
            fechaEmision=nueva_factura.fecha_emision.isoformat() + "Z",
            estadoPago="PAGADO",
            idGarantia=garantia.id if garantia is not None else None,
            garantiaVence=(garantia.fecha_vencimiento.isoformat() + "Z") if garantia is not None else None,
        )
        db.close()
        return resp

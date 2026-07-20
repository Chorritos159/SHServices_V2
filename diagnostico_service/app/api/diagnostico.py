from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import httpx
import json
import uuid
import datetime
from app.models.schemas import DiagnosticoCreate, DiagnosticoResponse, DiagnosticoDetalle, RepuestoDetalle
from app.models.diagnostico import DiagnosticoDB
from app.models.idempotencia import IdempotenciaDB
from app.models.asignacion import AsignacionDB
from app.core.database import get_db
from app.core.logger import get_logger, NO_ENCONTRADO, RECHAZADO, DUPLICADO
from app.core.rabbitmq import publicar_evento

router = APIRouter()
logger = get_logger("diagnostico-service")

# URL interna del servicio de almacén (red Docker).
ALMACEN_SERVICE_URL = "http://almacen-service:80/api/v1/almacen"


@router.post("/", response_model=DiagnosticoResponse, status_code=201, tags=["Diagnóstico Técnico"])
async def registrar_diagnostico(
    diagnostico: DiagnosticoCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
):
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id

    # La SEDE sale del token del técnico (inyectada por el Gateway), no del body.
    sede = request.headers.get("x-user-sede", "").upper()
    if not sede:
        raise HTTPException(
            status_code=401,
            detail="Tu token no trae la sede. Vuelve a iniciar sesion.",
        )

    # Idempotencia (S34): registrar un diagnóstico RESERVA stock, por lo que un
    # reintento (p. ej. del outbox del Gateway tras una caída) NO debe volver a
    # reservar ni crear otro diagnóstico. Con la misma Idempotency-Key se
    # devuelve la MISMA respuesta sin repetir el efecto.
    clave_idem = request.headers.get("idempotency-key")
    if clave_idem:
        previo = db.query(IdempotenciaDB).filter(IdempotenciaDB.clave == clave_idem).first()
        if previo:
            logger.info(
                f"Idempotency-Key '{clave_idem}' ya procesada; se devuelve el diagnostico original.",
                extra={"campos": {"operation": "registrar_diagnostico",
                                  "event": "DiagnosticoRegistrado.v1", "result": DUPLICADO}},
            )
            return JSONResponse(status_code=previo.status_code, content=json.loads(previo.respuesta_json))

    with logger.operacion(
        "registrar_diagnostico", event="DiagnosticoRegistrado.v1",
        idTicket=diagnostico.idTicket, sede=sede, repuestos=len(diagnostico.repuestos),
    ) as op:
        # 0. ¿El ticket YA tiene un diagnóstico? (id_ticket es UNIQUE). Se
        # comprueba ANTES de reservar stock para no dejar reservas huérfanas y,
        # sobre todo, para devolver un 409 legible en vez de un 500 opaco
        # ("error inesperado") por la violación de la restricción única.
        ya_existe = db.query(DiagnosticoDB).filter(
            DiagnosticoDB.id_ticket == diagnostico.idTicket
        ).first()
        if ya_existe:
            op.result = RECHAZADO
            op.mensaje = f"El ticket {diagnostico.idTicket} ya tiene un diagnostico registrado ({ya_existe.id})."
            raise HTTPException(
                status_code=409,
                detail=(f"El ticket '{diagnostico.idTicket}' ya tiene un diagnostico registrado. "
                        "No se puede registrar otro."),
            )

        # 1. Reservar stock en almacén por CADA repuesto de la lista.
        estado_reserva = "SIN_REPUESTOS" if not diagnostico.repuestos else "RESERVA_CONFIRMADA"
        async with httpx.AsyncClient() as client:
            for item in diagnostico.repuestos:
                payload_reserva = {
                    "codigo_producto": item.codigo_repuesto,
                    "cantidad": item.cantidad,
                    "sede": sede,
                }
                try:
                    response = await client.post(
                        f"{ALMACEN_SERVICE_URL}/reservar",
                        json=payload_reserva,
                        headers={
                            "x-correlation-id": correlation_id,
                            # Clave DERIVADA del diagnostico y la linea, no
                            # aleatoria: si este diagnostico se reintenta (doble
                            # clic del tecnico, o reenvio del outbox), la clave
                            # es la MISMA y el almacen no vuelve a reservar.
                            "Idempotency-Key":
                                f"diag-{diagnostico.idTicket}-{item.codigo_repuesto}",
                        },
                        timeout=5.0,
                    )
                except httpx.RequestError as exc:
                    # Dependencia caida: 503 honesto, con el motivo real en el log.
                    op.campos["dependency"] = "almacen-service"
                    op.mensaje_error = f"El almacen no respondio al reservar {item.codigo_repuesto}: {exc}"
                    raise HTTPException(
                        status_code=503,
                        detail=("El servicio de Almacen no esta disponible en este momento. "
                                "El diagnostico no se guardo; intentalo de nuevo en unos segundos."),
                    )

                if response.status_code != 200:
                    detalle = response.json().get("detail", "el almacen no explico el motivo")
                    op.result = RECHAZADO
                    op.campos.update({"dependency": "almacen-service",
                                      "repuestoRechazado": item.codigo_repuesto})
                    op.mensaje = f"Diagnostico rechazado: el almacen no reservo {item.codigo_repuesto}. {detalle}"
                    raise HTTPException(
                        status_code=409,
                        detail=f"No se pudo reservar el repuesto '{item.codigo_repuesto}': {detalle}",
                    )

        # 2. Guardar el diagnóstico (repuestos serializados como JSON).
        id_diag = f"DIAG-{uuid.uuid4().hex[:12].upper()}"
        nuevo_diag = DiagnosticoDB(
            id=id_diag,
            id_ticket=diagnostico.idTicket,
            falla_detectada=diagnostico.fallaDetectada,
            mano_obra=diagnostico.mano_obra,
            precio_reparacion=diagnostico.precio_reparacion,
            repuestos_json=json.dumps([r.model_dump() for r in diagnostico.repuestos]),
            estado="DIAGNOSTICADO",
        )
        db.add(nuevo_diag)
        try:
            db.commit()
        except IntegrityError:
            # Carrera: otro request registró el diagnóstico de este ticket entre
            # la comprobación y el commit. Se responde 409 legible, no 500.
            db.rollback()
            op.result = RECHAZADO
            op.mensaje = f"Carrera: el ticket {diagnostico.idTicket} ya tenia diagnostico al confirmar."
            raise HTTPException(
                status_code=409,
                detail=f"El ticket '{diagnostico.idTicket}' ya tiene un diagnostico registrado.",
            )

        # Si el ticket estaba asignado a un técnico, refleja el avance en su
        # bandeja "Mis Tickets" (TOMADO -> DIAGNOSTICADO). No es crítico: si no
        # hay asignación, simplemente no se toca.
        asignacion = db.query(AsignacionDB).filter(
            AsignacionDB.id_ticket == diagnostico.idTicket
        ).first()
        if asignacion:
            asignacion.estado = "DIAGNOSTICADO"
            db.commit()

        op.campos.update({
            "idDiagnostico": id_diag,
            "estadoReserva": estado_reserva,
            "precioReparacion": diagnostico.precio_reparacion,
        })
        op.mensaje = (f"Diagnostico {id_diag} registrado para {diagnostico.idTicket} en {sede} "
                      f"(S/.{diagnostico.precio_reparacion}, {len(diagnostico.repuestos)} repuesto(s)).")

        # 3. Emitir evento para la coreografía / auditoría.
        evento_payload = {
            "evento": "DiagnosticoRegistrado.v1",
            "trace_id": correlation_id,
            "datos": {
                "idDiagnostico": id_diag,
                "idTicket": diagnostico.idTicket,
                "sede": sede,
                "estadoReserva": estado_reserva,
                "precioReparacion": diagnostico.precio_reparacion,
                # Los repuestos VIAJAN en el evento. Sin ellos, ticket-service
                # no sabe que confirmar al entregar y el stock se queda
                # reservado para siempre (reservado pero nunca descontado).
                "repuestos": [
                    {"codigo_producto": r.codigo_repuesto, "cantidad": r.cantidad}
                    for r in diagnostico.repuestos
                ],
            },
        }
        background_tasks.add_task(
            publicar_evento,
            exchange_name="tickets.eventos",
            routing_key="ticket.diagnosticado",
            mensaje=evento_payload,
        )

        respuesta = DiagnosticoResponse(
            idDiagnostico=id_diag,
            idTicket=diagnostico.idTicket,
            estadoReserva=estado_reserva,
            manoObra=diagnostico.mano_obra,
            precioReparacion=diagnostico.precio_reparacion,
            repuestosDescontados=len(diagnostico.repuestos),
            fecha=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z",
        )

        # Registro de idempotencia DESPUÉS de confirmar (para no bloquear el
        # diagnóstico si esta escritura fallara). Un reintento con la misma
        # clave ya no reservará stock ni creará otro diagnóstico.
        if clave_idem:
            db.add(IdempotenciaDB(
                clave=clave_idem, operacion="registrar_diagnostico",
                status_code=201, respuesta_json=respuesta.model_dump_json(),
            ))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # carrera: la misma clave llegó en paralelo

        return respuesta


@router.get("/por-ticket/{id_ticket}", response_model=DiagnosticoDetalle, tags=["Diagnóstico Técnico"])
async def diagnostico_por_ticket(id_ticket: str, request: Request, db: Annotated[Session, Depends(get_db)]):
    """Devuelve el desglose del diagnóstico de un ticket (para que Caja vea qué cobra)."""
    logger.extra["correlation_id"] = request.headers.get("x-correlation-id", "N/A")

    with logger.operacion("consultar_diagnostico", idTicket=id_ticket) as op:
        diag = db.query(DiagnosticoDB).filter(DiagnosticoDB.id_ticket == id_ticket).first()
        if not diag:
            op.result = NO_ENCONTRADO
            op.mensaje = f"No hay diagnostico registrado para el ticket {id_ticket}."
            raise HTTPException(
                status_code=404,
                detail=f"El ticket '{id_ticket}' todavia no tiene un diagnostico registrado.",
            )

        repuestos = []
        total_repuestos = 0.0
        for r in json.loads(diag.repuestos_json or "[]"):
            subtotal = round(r.get("cantidad", 0) * r.get("precio_unitario", 0.0), 2)
            total_repuestos += subtotal
            repuestos.append(RepuestoDetalle(
                codigo_repuesto=r.get("codigo_repuesto", ""),
                descripcion=r.get("descripcion", ""),
                cantidad=r.get("cantidad", 0),
                precio_unitario=r.get("precio_unitario", 0.0),
                subtotal=subtotal,
            ))

        op.campos.update({"idDiagnostico": diag.id, "totalRepuestos": round(total_repuestos, 2)})
        op.mensaje = f"Desglose del diagnostico {diag.id} entregado para el ticket {id_ticket}."
        return DiagnosticoDetalle(
            idDiagnostico=diag.id,
            idTicket=diag.id_ticket,
            fallaDetectada=diag.falla_detectada,
            manoObra=diag.mano_obra or 0.0,
            totalRepuestos=round(total_repuestos, 2),
            precioReparacion=diag.precio_reparacion or 0.0,
            repuestos=repuestos,
        )

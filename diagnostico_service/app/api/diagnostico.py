from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
import httpx
import json
import uuid
import datetime
from app.models.schemas import DiagnosticoCreate, DiagnosticoResponse
from app.models.diagnostico import DiagnosticoDB
from app.core.database import get_db
from app.core.logger import get_logger
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
    db: Session = Depends(get_db),
):
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id

    # La SEDE sale del token del técnico (inyectada por el Gateway), no del body.
    sede = request.headers.get("x-user-sede", "").upper()
    if not sede:
        raise HTTPException(status_code=401, detail="Falta la sede en el token (cabecera X-User-Sede).")

    logger.info(f"Diagnóstico para ticket {diagnostico.idTicket} en sede {sede} · {len(diagnostico.repuestos)} repuesto(s)")

    # 1. Descontar stock en almacén por CADA repuesto de la lista.
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
                    headers={"x-correlation-id": correlation_id},
                    timeout=5.0,
                )
            except httpx.RequestError:
                logger.error("No se pudo conectar con el Servicio de Almacén.")
                raise HTTPException(status_code=503, detail="El Servicio de Almacén no está disponible.")

            if response.status_code != 200:
                detalle = response.json().get("detail", "Error desconocido")
                logger.error(f"El almacén rechazó {item.codigo_repuesto}: {detalle}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Fallo al descontar '{item.codigo_repuesto}': {detalle}",
                )
            logger.info(f"🔒 Descontadas {item.cantidad}x {item.codigo_repuesto} en {sede}.")

    # 2. Guardar el diagnóstico (repuestos serializados como JSON).
    id_diag = f"DIAG-{str(uuid.uuid4())[:8].upper()}"
    nuevo_diag = DiagnosticoDB(
        id=id_diag,
        id_ticket=diagnostico.idTicket,
        falla_detectada=diagnostico.fallaDetectada,
        precio_reparacion=diagnostico.precio_reparacion,
        repuestos_json=json.dumps([r.model_dump() for r in diagnostico.repuestos]),
        estado="DIAGNOSTICADO",
    )
    db.add(nuevo_diag)
    db.commit()
    logger.info(f"💾 Diagnóstico {id_diag} guardado en PostgreSQL (precio S/.{diagnostico.precio_reparacion}).")

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
        },
    }
    background_tasks.add_task(
        publicar_evento,
        exchange_name="tickets.eventos",
        routing_key="ticket.diagnosticado",
        mensaje=evento_payload,
    )

    return DiagnosticoResponse(
        idDiagnostico=id_diag,
        idTicket=diagnostico.idTicket,
        estadoReserva=estado_reserva,
        precioReparacion=diagnostico.precio_reparacion,
        repuestosDescontados=len(diagnostico.repuestos),
        fecha=datetime.datetime.utcnow().isoformat() + "Z",
    )

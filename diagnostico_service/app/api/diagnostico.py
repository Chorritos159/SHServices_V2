from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
import httpx
import uuid
import datetime
from app.models.schemas import DiagnosticoCreate, DiagnosticoResponse
from app.models.diagnostico import DiagnosticoDB
from app.core.database import get_db
from app.core.logger import get_logger
from app.core.rabbitmq import publicar_evento

router = APIRouter()
logger = get_logger("diagnostico-service")

# URL del servicio de almacén (Usamos localhost porque corre fuera de Docker temporalmente)
ALMACEN_SERVICE_URL = "http://almacen-service:80/api/v1/almacen"

@router.post("/", response_model=DiagnosticoResponse, status_code=201, tags=["Diagnóstico Técnico"])
async def registrar_diagnostico(
    diagnostico: DiagnosticoCreate, 
    request: Request, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    correlation_id = request.headers.get("x-correlation-id", "N/A")
    logger.extra["correlation_id"] = correlation_id
    
    logger.info(f"Iniciando diagnóstico para el ticket {diagnostico.idTicket}")
    estado_reserva = "SIN_REPUESTOS_NECESARIOS"

    # 1. Si requiere repuestos, hacemos la llamada HTTP interna al Almacén
    if diagnostico.repuestoNecesario and diagnostico.cantidad > 0:
        logger.info(f"Solicitando {diagnostico.cantidad}x {diagnostico.repuestoNecesario} al Almacén de {diagnostico.sede}...")
        
        payload_reserva = {
            "codigo_producto": diagnostico.repuestoNecesario,
            "cantidad": diagnostico.cantidad,
            "sede": diagnostico.sede
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{ALMACEN_SERVICE_URL}/reservar",
                    json=payload_reserva,
                    headers={"x-correlation-id": correlation_id},
                    timeout=5.0
                )
                if response.status_code == 200:
                    estado_reserva = "RESERVA_CONFIRMADA"
                    logger.info("Reserva en Almacén exitosa.")
                else:
                    error_msg = response.json().get("detail", "Error desconocido")
                    logger.error(f"El almacén rechazó la reserva: {error_msg}")
                    raise HTTPException(status_code=400, detail=f"Fallo en Almacén: {error_msg}")
            
            except httpx.RequestError:
                logger.error("No se pudo conectar con el Servicio de Almacén.")
                raise HTTPException(status_code=503, detail="El Servicio de Almacén no está disponible.")

    # 2. Guardar en Base de Datos
    id_diag = f"DIAG-{str(uuid.uuid4())[:8].upper()}"
    nuevo_diag = DiagnosticoDB(
        id=id_diag,
        id_ticket=diagnostico.idTicket,
        falla_detectada=diagnostico.fallaDetectada,
        repuesto_solicitado=diagnostico.repuestoNecesario,
        cantidad_repuesto=str(diagnostico.cantidad),
        estado="DIAGNOSTICADO"
    )
    db.add(nuevo_diag)
    db.commit()
    logger.info(f"💾 Diagnóstico {id_diag} guardado en PostgreSQL.")

    # 3. Emitir Evento
    evento_payload = {
        "evento": "DiagnosticoRegistrado.v1",
        "trace_id": correlation_id,
        "datos": {"idDiagnostico": id_diag, "idTicket": diagnostico.idTicket, "estadoReserva": estado_reserva}
    }
    background_tasks.add_task(
        publicar_evento, exchange_name="tickets.eventos", routing_key="ticket.diagnosticado", mensaje=evento_payload
    )

    return DiagnosticoResponse(
        idDiagnostico=id_diag,
        idTicket=diagnostico.idTicket,
        estadoReserva=estado_reserva,
        fecha=datetime.datetime.utcnow().isoformat() + "Z"
    )
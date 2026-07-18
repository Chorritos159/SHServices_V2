"""Consulta de garantías — la sirve facturacion-service.

Antes vivía en ticket-service; se movió aquí porque la garantía nace del COBRO
(es parte del ciclo económico) y porque así la consulta sigue disponible aunque
el ticket-service esté caído.

Se monta en `/api/v1/garantias` (sin doblar "facturas") para que el Gateway lo
exponga como `/api/v1/facturas/garantias`.
"""
from typing import Annotated
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logger import get_logger, NO_ENCONTRADO
from app.models.garantia import GarantiaDB
from app.models.factura import FacturaDB
from app.models.schemas import GarantiaOut
from app.api.facturacion import _respuesta_desde_db

router = APIRouter()
logger = get_logger("facturacion-service")


def _garantia_out(g: GarantiaDB) -> dict:
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    restantes = (g.fecha_vencimiento - ahora).days
    return {
        "id": g.id, "id_ticket": g.id_ticket, "documento_cliente": g.documento_cliente,
        "equipo": g.equipo, "numero_serie": g.numero_serie, "descripcion": g.descripcion,
        "fecha_entrega": g.fecha_entrega, "fecha_vencimiento": g.fecha_vencimiento, "dias": g.dias,
        "monto_total": g.monto_total,
        "vigente": g.fecha_vencimiento >= ahora, "dias_restantes": max(restantes, 0),
    }


@router.get("/", response_model=list[GarantiaOut], tags=["Garantías"])
async def listar_garantias(request: Request, db: Annotated[Session, Depends(get_db)]):
    """Todas las garantías con su vigencia (Recepción y Admin)."""
    logger.extra["correlation_id"] = request.headers.get("x-correlation-id", "N/A")
    garantias = db.query(GarantiaDB).order_by(GarantiaDB.fecha_entrega.desc()).all()
    return [_garantia_out(g) for g in garantias]


@router.get("/por-documento/{documento}", response_model=list[GarantiaOut], tags=["Garantías"])
async def garantias_por_documento(documento: str, request: Request, db: Annotated[Session, Depends(get_db)]):
    """Garantías por DNI/RUC (para verificar si un equipo vuelve en garantía)."""
    logger.extra["correlation_id"] = request.headers.get("x-correlation-id", "N/A")
    garantias = (
        db.query(GarantiaDB)
        .filter(GarantiaDB.documento_cliente == documento)
        .order_by(GarantiaDB.fecha_entrega.desc())
        .all()
    )
    return [_garantia_out(g) for g in garantias]


@router.get("/factura-de/{id_ticket}", tags=["Garantías"])
async def factura_de_garantia(id_ticket: str, request: Request, db: Annotated[Session, Depends(get_db)]):
    """Comprobante asociado a un ticket: al hacer clic en una garantía, la UI
    muestra la factura que la respalda. Todo dentro de facturacion-service."""
    logger.extra["correlation_id"] = request.headers.get("x-correlation-id", "N/A")

    with logger.operacion("consultar_factura_por_ticket", idTicket=id_ticket) as op:
        factura = db.query(FacturaDB).filter(FacturaDB.id_ticket == id_ticket).first()
        if not factura:
            op.result = NO_ENCONTRADO
            op.mensaje = f"No hay comprobante emitido para el ticket {id_ticket}."
            raise HTTPException(
                status_code=404,
                detail=f"El ticket '{id_ticket}' todavia no tiene comprobante emitido.",
            )
        garantia = db.query(GarantiaDB).filter(GarantiaDB.id_ticket == id_ticket).first()
        op.mensaje = f"Comprobante {factura.id} entregado para el ticket {id_ticket}."
        return {
            **_respuesta_desde_db(factura).model_dump(),
            "metodoPago": factura.metodo_pago,
            "garantiaVence": garantia.fecha_vencimiento.isoformat() + "Z" if garantia else None,
        }

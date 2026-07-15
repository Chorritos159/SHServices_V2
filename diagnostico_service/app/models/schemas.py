from pydantic import BaseModel, Field
from typing import List


class RepuestoItem(BaseModel):
    codigo_repuesto: str = Field(..., description="Código del repuesto en almacén, ej. REP-001")
    cantidad: int = Field(..., gt=0, description="Unidades a descontar del stock")


class DiagnosticoCreate(BaseModel):
    idTicket: str = Field(..., description="ID del ticket en estado EN_COLA")
    fallaDetectada: str = Field(..., description="Descripción técnica del problema")
    precio_reparacion: float = Field(0.0, ge=0, description="Costo de la mano de obra / reparación")
    repuestos: List[RepuestoItem] = Field(default_factory=list, description="Repuestos a descontar")
    # La `sede` ya NO viene aquí: se toma del token del técnico (cabecera X-User-Sede).


class DiagnosticoResponse(BaseModel):
    idDiagnostico: str
    idTicket: str
    estadoReserva: str
    precioReparacion: float
    repuestosDescontados: int
    fecha: str

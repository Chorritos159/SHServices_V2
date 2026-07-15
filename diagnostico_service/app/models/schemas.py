from pydantic import BaseModel, Field
from typing import List


class RepuestoItem(BaseModel):
    codigo_repuesto: str = Field(..., description="Código del repuesto en almacén, ej. REP-001")
    cantidad: int = Field(..., gt=0, description="Unidades a descontar del stock")
    precio_unitario: float = Field(0.0, ge=0, description="Precio unitario al momento del diagnóstico")
    descripcion: str = Field("", description="Nombre/descripción del repuesto")


class DiagnosticoCreate(BaseModel):
    idTicket: str = Field(..., description="ID del ticket en estado EN_COLA")
    fallaDetectada: str = Field(..., description="Descripción técnica del problema")
    mano_obra: float = Field(0.0, ge=0, description="Costo de la mano de obra fijado por el técnico")
    precio_reparacion: float = Field(0.0, ge=0, description="Total = repuestos + mano de obra")
    repuestos: List[RepuestoItem] = Field(default_factory=list, description="Repuestos a descontar")
    # La `sede` ya NO viene aquí: se toma del token del técnico (cabecera X-User-Sede).


class DiagnosticoResponse(BaseModel):
    idDiagnostico: str
    idTicket: str
    estadoReserva: str
    manoObra: float
    precioReparacion: float
    repuestosDescontados: int
    fecha: str


class RepuestoDetalle(BaseModel):
    codigo_repuesto: str
    descripcion: str = ""
    cantidad: int
    precio_unitario: float = 0.0
    subtotal: float = 0.0


class DiagnosticoDetalle(BaseModel):
    """Desglose del diagnóstico para que Caja vea qué está cobrando."""
    idDiagnostico: str
    idTicket: str
    fallaDetectada: str
    manoObra: float
    totalRepuestos: float
    precioReparacion: float
    repuestos: List[RepuestoDetalle] = []

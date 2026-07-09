from pydantic import BaseModel, Field
from typing import Optional

class DiagnosticoCreate(BaseModel):
    idTicket: str = Field(..., description="ID del ticket en estado EN_COLA")
    fallaDetectada: str = Field(..., description="Descripción técnica del problema")
    repuestoNecesario: Optional[str] = Field(None, description="Código del repuesto (ej. REP-VENT-01)")
    cantidad: int = Field(0, description="Cantidad de repuestos necesarios")
    sede: str = Field(..., description="Sede donde se realiza el diagnóstico")

class DiagnosticoResponse(BaseModel):
    idDiagnostico: str
    idTicket: str
    estadoReserva: str
    fecha: str
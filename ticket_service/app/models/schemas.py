from pydantic import BaseModel, Field, field_validator
from typing import Optional

class TicketCreate(BaseModel):
    """Contrato de entrada para la creación de un Ticket o Venta."""
    datosCliente: str = Field(..., description="DNI, RUC o Nombre del cliente")
    tipoOperacion: str = Field(..., description="Debe ser 'SOPORTE' o 'VENTA'")
    datosEquipo: Optional[str] = Field(None, description="Obligatorio si la operación es SOPORTE")
    sede: str = Field(..., description="Código de la sede, ej: PIURA")
    usuarioRegistro: str = Field(..., description="ID del usuario (Cajero/Recepcionista)")
    prioridad: str = Field("NORMAL", description="Nivel de prioridad: ALTA, MEDIA, NORMAL")

    @field_validator('tipoOperacion')
    def validar_operacion(cls, v):
        if v.upper() not in ["SOPORTE", "VENTA"]:
            raise ValueError("El tipo de operación debe ser SOPORTE o VENTA")
        return v.upper()

class TicketResponse(BaseModel):
    """Contrato de salida exitosa (201 Created)."""
    idTicket: str
    estadoInicial: str
    fechaRegistro: str
    tipoOperacionRegistrada: str
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional
from datetime import datetime

class TicketCreate(BaseModel):
    """
    Contrato de entrada para la creación de un Ticket o Venta.
    OJO: `sede` y `usuarioRegistro` ya NO se piden aquí; el Gateway los inyecta
    desde el JWT vía las cabeceras X-User-Sede / X-User-Sub.
    """
    datosCliente: str = Field(..., description="DNI, RUC o Nombre del cliente")
    tipoOperacion: str = Field(..., description="Debe ser 'SOPORTE' o 'VENTA'")
    datosEquipo: Optional[str] = Field(None, description="Obligatorio si la operación es SOPORTE")
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


class TicketPendiente(BaseModel):
    """Contrato de salida para el listado de tickets (ej. los EN_COLA del técnico)."""
    model_config = ConfigDict(from_attributes=True)   # serializa el objeto ORM directamente
    id: str
    datos_cliente: str
    tipo_operacion: str
    datos_equipo: Optional[str] = None
    sede: str
    prioridad: str
    estado: str
    fecha_registro: datetime


class EstadoUpdate(BaseModel):
    """Cambio de estado del ticket (ej. EN_COLA → DIAGNOSTICADO)."""
    estado: str = Field(..., description="Nuevo estado del ticket")
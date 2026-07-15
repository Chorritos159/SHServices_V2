from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional
from datetime import datetime

class TicketCreate(BaseModel):
    """
    Contrato de entrada para la creación de un Ticket o Venta.
    OJO: `sede` y `usuarioRegistro` los inyecta el Gateway desde el JWT
    (cabeceras X-User-Sede / X-User-Sub).
    """
    datosCliente: str = Field(..., description="Nombre del cliente")
    documento_cliente: str = Field(..., min_length=6, description="DNI o RUC (obligatorio)")
    telefono_cliente: str = Field(..., min_length=6, description="Teléfono de contacto (obligatorio)")
    tipoOperacion: str = Field(..., description="Debe ser 'SOPORTE' o 'VENTA'")
    equipo: Optional[str] = Field(None, description="Marca/modelo del equipo (obligatorio en SOPORTE)")
    caracteristicas_falla: Optional[str] = Field(None, description="Descripción de la falla (obligatorio en SOPORTE)")
    precio_estimado: Optional[float] = Field(None, ge=0, description="Presupuesto estimado (opcional)")
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
    """Contrato de salida para el listado/filtrado de tickets."""
    model_config = ConfigDict(from_attributes=True)   # serializa el objeto ORM directamente
    id: str
    datos_cliente: str
    documento_cliente: Optional[str] = None
    telefono_cliente: Optional[str] = None
    tipo_operacion: str
    datos_equipo: Optional[str] = None
    equipo: Optional[str] = None
    caracteristicas_falla: Optional[str] = None
    precio_estimado: Optional[float] = None
    sede: str
    prioridad: str
    estado: str
    fecha_registro: datetime


class EstadoUpdate(BaseModel):
    """Cambio de estado del ticket (ej. EN_COLA → DIAGNOSTICADO)."""
    estado: str = Field(..., description="Nuevo estado del ticket")

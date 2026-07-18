from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, List
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
    numero_serie: Optional[str] = Field(None, description="Número de serie del equipo (opcional)")
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
    numero_serie: Optional[str] = None
    caracteristicas_falla: Optional[str] = None
    precio_estimado: Optional[float] = None
    sede: str
    prioridad: str
    estado: str
    fecha_registro: datetime


class EstadoUpdate(BaseModel):
    """Cambio de estado libre (bajo nivel; la vía gobernada son las transiciones)."""
    estado: str = Field(..., description="Nuevo estado del ticket")


class RepuestoRef(BaseModel):
    codigo_producto: str
    cantidad: int = Field(..., gt=0)


class DiagnosticarRequest(BaseModel):
    """Repuestos reservados en el diagnóstico (se registran en el ticket para
    confirmar/liberar su stock más adelante)."""
    repuestos: List[RepuestoRef] = Field(default_factory=list)


class EntregarRequest(BaseModel):
    """Datos del cobro al entregar (el BFF pasa el monto ya facturado)."""
    monto_total: float = Field(0.0, ge=0)

# GarantiaOut se movio a facturacion-service (models/schemas.py): la garantia
# la emite y consulta facturacion, no tickets.

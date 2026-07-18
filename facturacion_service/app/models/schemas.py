from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional


class LineaDetalle(BaseModel):
    """Línea de detalle del comprobante (POS)."""
    codigo_producto: str = Field(..., description="Código del producto vendido (ej. REP-001)")
    descripcion: str = Field(..., description="Nombre/descripción del producto")
    cantidad: int = Field(..., gt=0)
    precio_unitario: float = Field(..., ge=0)


class LineaDetalleOut(LineaDetalle):
    subtotal: float


class FacturaCreate(BaseModel):
    idTicket: str = Field(..., description="ID del ticket que se va a cobrar")
    montoManoObra: float = Field(0.0, ge=0, description="Costo del servicio técnico (SOPORTE)")
    montoRepuestos: float = Field(0.0, ge=0, description="Costo acumulado de repuestos (SOPORTE)")
    lineas: List[LineaDetalle] = Field(default_factory=list, description="Líneas de detalle (VENTA directa)")
    metodoPago: str = Field("EFECTIVO", description="EFECTIVO, TARJETA o YAPE")
    sede: str = Field(..., description="Sede donde se realiza el cobro")

    # Datos del equipo para emitir la GARANTÍA junto con el cobro. Los manda
    # quien cobra (ya los tiene en pantalla), así facturacion-service NO
    # depende del ticket-service para generarla.
    tipoOperacion: str = Field("SOPORTE", description="SOPORTE genera garantía; VENTA no")
    documentoCliente: Optional[str] = Field(None, description="DNI/RUC del cliente")
    equipo: Optional[str] = Field(None, description="Equipo reparado")
    numeroSerie: Optional[str] = Field(None, description="N° de serie del equipo")
    descripcion: Optional[str] = Field(None, description="Qué reparación cubre la garantía")


class GarantiaOut(BaseModel):
    id: str
    id_ticket: str
    documento_cliente: Optional[str] = None
    equipo: Optional[str] = None
    numero_serie: Optional[str] = None
    descripcion: Optional[str] = None
    fecha_entrega: datetime
    fecha_vencimiento: datetime
    dias: int
    monto_total: Optional[float] = None
    vigente: bool
    dias_restantes: int


class FacturaResponse(BaseModel):
    idFactura: str
    idTicket: str
    montoManoObra: float
    montoRepuestos: float
    montoLineas: float
    montoTotal: float
    lineas: List[LineaDetalleOut] = []
    fechaEmision: str
    estadoPago: str
    # Garantía emitida junto con el cobro (solo SOPORTE). La UI la imprime
    # en el comprobante sin tener que consultar al ticket-service.
    idGarantia: Optional[str] = None
    garantiaVence: Optional[str] = None

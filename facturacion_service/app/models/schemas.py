from pydantic import BaseModel, Field
from typing import List


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

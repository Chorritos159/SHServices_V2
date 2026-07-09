from pydantic import BaseModel, Field

class FacturaCreate(BaseModel):
    idTicket: str = Field(..., description="ID del ticket que se va a cobrar")
    montoManoObra: float = Field(..., ge=0, description="Costo del servicio técnico")
    montoRepuestos: float = Field(0.0, ge=0, description="Costo acumulado de repuestos usados")
    metodoPago: str = Field("EFECTIVO", description="EFECTIVO, TARJETA o YAPE")
    sede: str = Field(..., description="Sede donde se realiza el cobro")

class FacturaResponse(BaseModel):
    idFactura: str
    idTicket: str
    montoTotal: float
    fechaEmision: str
    estadoPago: str
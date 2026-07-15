from pydantic import BaseModel, ConfigDict, Field

class ProductoCreate(BaseModel):
    # `codigo` ya NO se pide: el almacén lo autogenera secuencialmente (REP-001, REP-002…).
    nombre: str = Field(..., description="Nombre del repuesto o producto")
    categoria: str = Field(..., description="REPUESTO o PRODUCTO_VENTA")
    sede: str = Field(..., description="Sede donde está físicamente")
    stock_inicial: int = Field(..., ge=0, description="Cantidad física real")

class ProductoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)   # permite serializar el objeto ORM
    codigo: str
    nombre: str
    stock_disponible: int
    sede: str

class ProductoInventario(BaseModel):
    """Contrato de salida para el listado completo de inventario (GET)."""
    model_config = ConfigDict(from_attributes=True)   # serializa el objeto ORM directamente
    codigo: str
    nombre: str
    categoria: str
    sede: str
    stock_disponible: int
    stock_reservado: int

class ReservaRequest(BaseModel):
    codigo_producto: str
    cantidad: int = Field(..., gt=0)
    sede: str
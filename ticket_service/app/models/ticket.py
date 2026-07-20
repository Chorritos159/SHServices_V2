from sqlalchemy import Column, String, DateTime, Float, Text, Index
from app.core.database import Base
import datetime

class TicketDB(Base):
    """Modelo de base de datos para la tabla 'tickets'"""
    __tablename__ = "tickets"

    id = Column(String, primary_key=True, index=True)
    datos_cliente = Column(String, nullable=False)          # Nombre del cliente
    tipo_operacion = Column(String, nullable=False)
    datos_equipo = Column(String, nullable=True)            # legado (se mantiene = equipo)
    sede = Column(String, nullable=False)
    usuario_registro = Column(String, nullable=False)
    prioridad = Column(String, nullable=False)
    estado = Column(String, nullable=False, default="EN_COLA", index=True)
    fecha_registro = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    # --- Campos enriquecidos (Help Desk / POS) ---
    documento_cliente = Column(String, nullable=True)       # DNI / RUC
    telefono_cliente = Column(String, nullable=True)
    equipo = Column(String, nullable=True)                  # Marca/modelo del equipo
    numero_serie = Column(String, nullable=True, index=True)  # serie (opcional) para garantías fiables
    caracteristicas_falla = Column(Text, nullable=True)     # Descripción larga de la falla

    __table_args__ = (
        # Las dos consultas mas usadas filtran por estado y ORDENAN por fecha
        # (cola del tecnico, listados por estado). Con dos indices sueltos
        # PostgreSQL filtra por uno y ordena en memoria; el compuesto resuelve
        # filtro y orden de una pasada.
        Index("ix_tickets_estado_fecha", "estado", "fecha_registro"),
        # Busqueda por cliente desde recepcion y para garantias.
        Index("ix_tickets_documento", "documento_cliente"),
    )

    precio_estimado = Column(Float, nullable=True)          # Presupuesto estimado (opcional)

    # Repuestos reservados en el diagnóstico (JSON). Los usa la máquina de estados
    # para CONFIRMAR (al entregar) o LIBERAR (al rechazar) el stock en almacén.
    repuestos_reservados = Column(Text, nullable=True)

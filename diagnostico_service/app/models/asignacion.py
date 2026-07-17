import datetime
from sqlalchemy import Column, String, DateTime, Text
from app.core.database import Base


class AsignacionDB(Base):
    """Asignación de un ticket a un técnico (¿quién atiende qué?).

    La gestiona el diagnostico-service como DUEÑO AUTORITATIVO, NO el
    ticket-service. Motivo (resiliencia): la bandeja "Mis Tickets" del técnico
    se sirve desde aquí, así que sigue funcionando aunque el ticket-service esté
    caído — si dependiera de ticket-service, su caída pararía todo el trabajo.

    La clave primaria es `id_ticket`: garantiza que un ticket pertenece a UN
    solo técnico (exclusividad). Otro técnico de la misma sede que intente
    tomarlo recibe un 409.
    """
    __tablename__ = "asignaciones"

    id_ticket = Column(String, primary_key=True, index=True)
    tecnico = Column(String, nullable=False, index=True)     # x-user-sub del técnico dueño
    sede = Column(String, nullable=False, index=True)
    estado = Column(String, nullable=False, default="TOMADO")  # TOMADO -> DIAGNOSTICADO

    # Datos del ticket cacheados en el momento de tomarlo, para poder pintar
    # "Mis Tickets" SIN llamar al ticket-service (independencia = resiliencia).
    datos_cliente = Column(String, nullable=True)
    documento_cliente = Column(String, nullable=True)
    telefono_cliente = Column(String, nullable=True)
    tipo_operacion = Column(String, nullable=True)
    equipo = Column(String, nullable=True)
    numero_serie = Column(String, nullable=True)
    caracteristicas_falla = Column(Text, nullable=True)
    prioridad = Column(String, nullable=True)

    fecha_tomado = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

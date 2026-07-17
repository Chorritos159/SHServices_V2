from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.core.database import Base
import datetime


class WebhookSuscripcionDB(Base):
    """Un sistema externo que quiere recibir eventos del negocio por HTTP.

    Es el registro de "a quien hay que avisar": una URL + que evento le
    interesa (o '*' para todos). Cuando llega ese evento por RabbitMQ, el
    servicio le hace POST firmado a esta URL.
    """
    __tablename__ = "webhook_suscripciones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String, nullable=False)
    # Evento al que se suscribe: "ticket.creado", "producto.registrado", o
    # "*" para todos. El nombre es el routing_key del evento, no el .v1.
    evento = Column(String, nullable=False, default="*")
    descripcion = Column(String, nullable=True)
    activo = Column(Boolean, default=True, nullable=False)
    creado_en = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class EntregaWebhookDB(Base):
    """Bitacora de cada intento de entrega de un webhook (auditoria).

    Deja constancia de a que URL se entrego que evento, con que resultado y
    cuantos intentos hizo falta. Sin esto, un webhook que falla en silencio
    seria invisible.
    """
    __tablename__ = "webhook_entregas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String, nullable=False)
    evento = Column(String, nullable=False)
    referencia = Column(String, nullable=True)     # idTicket / codigo de producto
    estado = Column(String, nullable=False)        # ENTREGADO | FALLIDO
    intentos = Column(Integer, nullable=False)
    status_code = Column(Integer, nullable=True)   # ultimo codigo HTTP recibido
    trace_id = Column(String, nullable=True, index=True)
    entregado_en = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

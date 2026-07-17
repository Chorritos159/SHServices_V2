import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime
from app.core.database import Base


# Estados del ciclo de vida de una escritura encolada.
PENDIENTE = "PENDIENTE"    # aún no entregada; el worker la reintenta
ENTREGADO = "ENTREGADO"    # el microservicio la aceptó (2xx)
DESCARTADO = "DESCARTADO"  # el microservicio la rechazó por negocio (4xx): reintentar no ayuda


class OutboxDB(Base):
    """Outbox transaccional del Gateway (patrón store-and-forward).

    Cuando una ESCRITURA del cliente (POST/PUT/PATCH) no puede entregarse
    porque el microservicio destino está caído (circuito abierto, inaccesible
    o timeout), en vez de perderse se guarda aquí y un worker la reintenta
    hasta que el servicio vuelve. La `idempotency_key` viaja en cada reintento
    para que el destino NO cree duplicados (nada se pierde ni se duplica).

    La identidad ya validada por el Gateway (sede/usuario/rol) se guarda en
    cabeceras para poder reejecutar la petición aunque el JWT original ya haya
    expirado: los microservicios internos confían en las cabeceras X-User-*.
    """
    __tablename__ = "gateway_outbox"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Clave anti-duplicados: única. Si el mismo intento se encola dos veces,
    # la restricción UNIQUE lo impide en el origen.
    idempotency_key = Column(String, unique=True, nullable=False, index=True)

    # Cómo reejecutar la petición contra el microservicio interno.
    servicio = Column(String, nullable=False)      # p.ej. "tickets"
    metodo = Column(String, nullable=False)         # POST / PUT / PATCH
    path = Column(String, nullable=False)           # p.ej. "tickets/tickets/"
    body = Column(Text, nullable=False, default="") # cuerpo original (texto/JSON)
    # Cabeceras de identidad + correlación necesarias para el reintento (JSON).
    headers_json = Column(Text, nullable=False, default="{}")

    # Descripción legible para la UI ("crear ticket", "registrar diagnóstico"...).
    operacion = Column(String, nullable=False, default="escritura")

    estado = Column(String, nullable=False, default=PENDIENTE, index=True)
    intentos = Column(Integer, nullable=False, default=0)
    proximo_reintento_en = Column(DateTime, nullable=True)  # backoff: no reintentar antes de esto
    ultimo_error = Column(Text, nullable=True)

    # Resultado final cuando se entrega (para poder mostrárselo luego al usuario).
    status_respuesta = Column(Integer, nullable=True)
    respuesta_json = Column(Text, nullable=True)

    creado_en = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    actualizado_en = Column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False
    )

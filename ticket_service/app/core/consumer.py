"""Consumidor de eventos del ticket-service.

POR QUE EXISTE
El técnico registra el diagnóstico en `diagnostico-service`, que publica
`ticket.diagnosticado`. Hasta ahora NADIE consumía ese evento en tickets: el
ticket se quedaba en EN_DIAGNOSTICO para siempre. Se notaba sobre todo tras una
caída provocada por caos, porque el síntoma parecía "no se recupera", cuando en
realidad el consumidor nunca había existido.

POR QUE POR COLA Y NO POR HTTP
Si `diagnostico-service` llamara a `ticket-service` por HTTP y tickets estuviera
caído, el cambio de estado se perdería (o habría que sostener el diagnóstico
entero esperando a una dependencia que no es imprescindible para diagnosticar).
Con la cola, el evento se queda en RabbitMQ y se procesa cuando tickets vuelve:
eso es lo que hace que el backlog se drene solo.

DURABILIDAD (lo que hace que el backlog sobreviva)
  - exchange `tickets.eventos` durable: sobrevive a un reinicio del broker.
  - cola `tickets_estado_queue` durable: los mensajes encolados mientras el
    servicio está caído siguen ahí cuando vuelve.
  - `connect_robust`: aio_pika reconecta solo cuando el broker vuelve, sin que
    nadie reinicie el contenedor.
  - `message.process()`: el ACK se manda solo si el handler terminó bien. Si
    revienta a mitad, el mensaje vuelve a la cola y se reintenta.
"""
import asyncio
import json
import os

import aio_pika

from app.core.database import SessionLocal
from app.core.logger import get_logger
from app.models.ticket import TicketDB

logger = get_logger("ticket-consumer")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")

# Estado al que pasa un ticket ya diagnosticado: listo para que Caja cobre y
# entregue. Es el que la bandeja de CAJA espera para mostrar el aviso.
ESTADO_LISTO = "DIAGNOSTICADO"


def _marcar_diagnosticado(datos: dict) -> None:
    """Mueve el ticket a DIAGNOSTICADO. Idempotente a proposito.

    El mismo evento puede llegar dos veces (reintento del publicador, o un
    reproceso del backlog tras una caida): si el ticket ya esta en ese estado o
    mas avanzado, no se toca y no se considera un error.
    """
    id_ticket = datos.get("idTicket")
    if not id_ticket:
        logger.warning("Evento de diagnostico sin idTicket; se descarta.")
        return

    db = SessionLocal()
    try:
        ticket = db.query(TicketDB).filter(TicketDB.id == id_ticket).first()
        if ticket is None:
            logger.warning(f"Evento para el ticket '{id_ticket}', que no existe aqui.")
            return

        # ENTREGADO y RECHAZADO son finales: un evento tardio del backlog no
        # puede hacer retroceder un ticket que ya se cerro.
        if ticket.estado in (ESTADO_LISTO, "ENTREGADO", "RECHAZADO"):
            logger.info(
                f"El ticket {id_ticket} ya estaba en {ticket.estado}; no se toca.",
                extra={"campos": {"operation": "consumir_diagnostico",
                                  "event": "DiagnosticoRegistrado.v1", "result": "duplicado"}},
            )
            return

        anterior = ticket.estado
        ticket.estado = ESTADO_LISTO
        db.commit()
        logger.info(
            f"Ticket {id_ticket}: {anterior} -> {ESTADO_LISTO} por el diagnostico del tecnico.",
            extra={"campos": {"operation": "consumir_diagnostico",
                              "event": "DiagnosticoRegistrado.v1", "result": "exito",
                              "idTicket": id_ticket}},
        )
    except Exception as exc:
        db.rollback()
        # Se relanza a proposito: sin ACK, el mensaje vuelve a la cola.
        logger.error(f"No se pudo actualizar el ticket '{id_ticket}': {exc}")
        raise
    finally:
        db.close()


async def iniciar_consumidor():
    """Escucha los eventos que cambian el estado del ticket. Reintenta si se cae."""
    while True:
        try:
            connection = await aio_pika.connect_robust(RABBITMQ_URL)
            async with connection:
                channel = await connection.channel()
                # Un mensaje a la vez: si el servicio se cae a mitad del
                # backlog, solo se reprocesa ese, no un lote entero.
                await channel.set_qos(prefetch_count=1)

                exchange = await channel.declare_exchange(
                    "tickets.eventos", aio_pika.ExchangeType.TOPIC, durable=True
                )
                queue = await channel.declare_queue("tickets_estado_queue", durable=True)
                await queue.bind(exchange, routing_key="ticket.diagnosticado")

                logger.info("Consumidor de tickets conectado; escuchando 'ticket.diagnosticado'.")

                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        async with message.process():
                            payload = json.loads(message.body.decode())
                            logger.extra["correlation_id"] = (
                                payload.get("trace_id") or message.correlation_id or "N/A"
                            )
                            _marcar_diagnosticado(payload.get("datos", {}))

        except Exception as exc:
            logger.error(f"Consumidor de tickets caido, reintentando en 5s: {exc}")
            await asyncio.sleep(5)

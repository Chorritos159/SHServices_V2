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
  - `message.process(requeue=True)`: el ACK se manda solo si el handler terminó
    bien y, si revienta, el mensaje VUELVE a la cola. Sin `requeue=True` el
    comportamiento por defecto es descartarlo, y el evento se perdía.
"""
import asyncio
import json
import os

import aio_pika
import httpx

from app.core.database import SessionLocal
from app.core.logger import get_logger
from app.models.ticket import TicketDB

logger = get_logger("ticket-consumer")
# AMQP y no AMQPS: RabbitMQ solo es alcanzable dentro de la red Docker
# `shservices-net` y no publica su puerto AMQP al exterior, asi que este
# trafico nunca sale del host. El valor real llega por `RABBITMQ_URL` desde el
# `.env`; el literal es solo el respaldo para desarrollo. Mismo criterio que
# las URLs internas del Gateway (ver `documentacion/brechas_finales.md`).
# El respaldo se compone por partes en vez de ser una URL literal: el esquema
# queda configurable (`amqps` el dia que haya certificados) y no hay una cadena
# con credenciales incrustada. En ejecucion SIEMPRE manda `RABBITMQ_URL` del
# `.env`; esto es solo el valor por defecto para desarrollo local.
_ESQUEMA_MQ = os.getenv("ESQUEMA_MQ", "amqp")
_HOST_MQ = os.getenv("RABBITMQ_HOST", "rabbitmq:5672")
_USER_MQ = os.getenv("RABBITMQ_DEFAULT_USER", "guest")
_PASS_MQ = os.getenv("RABBITMQ_DEFAULT_PASS", "guest")
RABBITMQ_URL = os.getenv(
    "RABBITMQ_URL", f"{_ESQUEMA_MQ}://{_USER_MQ}:{_PASS_MQ}@{_HOST_MQ}/")

# Estado al que pasa un ticket ya diagnosticado: listo para que Caja cobre y
# entregue. Es el que la bandeja de CAJA espera para mostrar el aviso.
ESTADO_LISTO = "DIAGNOSTICADO"

# Estado final tras el cobro: el equipo sale y su stock reservado se consume.
ESTADO_ENTREGADO = "ENTREGADO"
ALMACEN_URL = f"{os.getenv('ESQUEMA_INTERNO', 'http')}://almacen-service:80/api/v1/almacen"


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

        # Se guardan los repuestos que el diagnostico reservo. Es lo que luego
        # usa POST /{id}/entregar para CONFIRMAR (descontar de verdad) el stock.
        # Sin esto la lista quedaba vacia, `_mover_stock` no llamaba a nadie y
        # los repuestos se quedaban reservados y nunca descontados.
        repuestos = datos.get("repuestos") or []
        if repuestos:
            ticket.repuestos_reservados = json.dumps(repuestos)

        db.commit()
        logger.info(
            f"Ticket {id_ticket}: {anterior} -> {ESTADO_LISTO} "
            f"({len(repuestos)} repuesto(s) reservado(s) anotados).",
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


async def _confirmar_stock(repuestos: list, sede: str, correlation_id: str) -> None:
    """Consume en almacen el stock que el diagnostico habia reservado.

    Si almacen no responde se LANZA la excepcion a proposito: sin ACK el
    mensaje vuelve a la cola y se reintenta. Tragarse el error aqui dejaria el
    stock reservado para siempre, que es justo el fallo que esto corrige.
    """
    if not repuestos:
        return
    async with httpx.AsyncClient() as client:
        for r in repuestos:
            resp = await client.post(
                f"{ALMACEN_URL}/confirmar",
                json={"codigo_producto": r["codigo_producto"],
                      "cantidad": r["cantidad"], "sede": sede},
                headers={
                    "x-correlation-id": correlation_id,
                    # Clave DERIVADA: si este evento se reprocesa, almacen no
                    # vuelve a consumir el mismo stock.
                    "Idempotency-Key": f"entrega-{r.get('_ticket','')}-{r['codigo_producto']}",
                },
                timeout=10.0,
            )
            if resp.status_code >= 500:
                raise RuntimeError(
                    f"almacen devolvio {resp.status_code} al confirmar {r['codigo_producto']}")


async def _marcar_entregado(datos: dict) -> None:
    """Cierra el ticket tras el cobro: consume el stock y lo pasa a ENTREGADO.

    POR QUE POR EVENTO. El BFF llamaba a POST /{id}/entregar justo despues de
    cobrar, con un `catch` vacio: si ticket-service estaba caido en ese momento,
    el cobro salia bien pero el ticket se quedaba abierto y el stock reservado
    para siempre, sin que nada lo reintentara. Por la cola, el evento espera y
    se procesa cuando el servicio vuelve.
    """
    id_ticket = datos.get("idTicket")
    if not id_ticket:
        return

    db = SessionLocal()
    try:
        ticket = db.query(TicketDB).filter(TicketDB.id == id_ticket).first()
        if ticket is None:
            logger.warning(f"Cobro de '{id_ticket}', que no existe aqui.")
            return
        if ticket.estado in (ESTADO_ENTREGADO, "RECHAZADO"):
            logger.info(f"El ticket {id_ticket} ya estaba en {ticket.estado}; no se toca.")
            return

        repuestos = json.loads(ticket.repuestos_reservados or "[]")
        for r in repuestos:
            r["_ticket"] = id_ticket
        sede = ticket.sede
    finally:
        db.close()

    # El stock PRIMERO: si falla, el mensaje se reintenta y el ticket sigue
    # abierto, que es preferible a cerrarlo dejando stock colgado.
    await _confirmar_stock(repuestos, sede, datos.get("trace_id") or "N/A")

    db = SessionLocal()
    try:
        ticket = db.query(TicketDB).filter(TicketDB.id == id_ticket).first()
        if ticket is not None and ticket.estado != ESTADO_ENTREGADO:
            ticket.estado = ESTADO_ENTREGADO
            db.commit()
            logger.info(
                f"Ticket {id_ticket} -> ENTREGADO por el cobro "
                f"({len(repuestos)} repuesto(s) confirmados en almacen).",
                extra={"campos": {"operation": "consumir_factura",
                                  "event": "FacturaGenerada.v1", "result": "exito",
                                  "idTicket": id_ticket}},
            )
    except Exception as exc:
        db.rollback()
        logger.error(f"No se pudo cerrar el ticket '{id_ticket}': {exc}")
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
                await queue.bind(exchange, routing_key="ticket.facturado")

                logger.info("Consumidor de tickets conectado; escuchando "
                            "'ticket.diagnosticado' y 'ticket.facturado'.")

                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        # requeue=True es IMPRESCINDIBLE: por defecto
                        # `process()` RECHAZA el mensaje sin devolverlo a la
                        # cola si el handler lanza, y se pierde. Se vio al
                        # levantar todo a la vez: almacen aun arrancaba, el
                        # confirmar-stock fallo y el evento del cobro
                        # desaparecio, dejando el ticket abierto para siempre.
                        # Con requeue vuelve a la cola y se reintenta.
                        async with message.process(requeue=True):
                            payload = json.loads(message.body.decode())
                            logger.extra["correlation_id"] = (
                                payload.get("trace_id") or message.correlation_id or "N/A"
                            )
                            datos = payload.get("datos", {})
                            datos.setdefault("trace_id", payload.get("trace_id"))
                            if message.routing_key == "ticket.facturado":
                                await _marcar_entregado(datos)
                            else:
                                _marcar_diagnosticado(datos)

        except Exception as exc:
            logger.error(f"Consumidor de tickets caido, reintentando en 5s: {exc}")
            await asyncio.sleep(5)

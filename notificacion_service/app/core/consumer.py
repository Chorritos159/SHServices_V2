import aio_pika
import json
import os
import asyncio
import time
from sqlalchemy.exc import IntegrityError
from app.core.logger import get_logger
from app.core.database import SessionLocal
from app.models.notificacion import NotificacionDB

logger = get_logger("notificacion-service")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")


def _guardar(rol_destino: str, mensaje: str, referencia: str, evento: str, trace_id: str | None):
    """Idempotencia (S34): un redelivery de RabbitMQ del mismo evento no debe
    generar una segunda alerta duplicada para el mismo rol — el índice único
    (trace_id, evento, rol_destino) rechaza el INSERT repetido.
    """
    inicio = time.monotonic()
    db = SessionLocal()
    try:
        db.add(NotificacionDB(
            rol_destino=rol_destino, mensaje=mensaje, referencia=referencia,
            evento=evento, trace_id=trace_id,
        ))
        db.commit()
        logger.info(
            f"🔔 Notificación para {rol_destino}: {mensaje}",
            extra={"campos": {"operation": "guardar_notificacion", "event": evento, "result": "ok",
                               "durationMs": round((time.monotonic() - inicio) * 1000, 1)}},
        )
    except IntegrityError:
        db.rollback()
        logger.warning(
            f"♻️ Notificación duplicada (redelivery de RabbitMQ) descartada: {evento} → {rol_destino}.",
            extra={"campos": {"operation": "guardar_notificacion", "event": evento, "result": "duplicado",
                               "durationMs": round((time.monotonic() - inicio) * 1000, 1)}},
        )
    finally:
        db.close()


def _enrutar(routing_key: str, payload: dict):
    """
    Reglas de enrutamiento por evento → rol:
      · ProductoRegistrado (producto.registrado) → ADMIN
      · TicketCreado en EN_COLA (ticket.creado)  → TECNICO
      · TicketListo / DIAGNOSTICADO (ticket.listo) → CAJA
    """
    evento = payload.get("evento", "")
    datos = payload.get("datos") or {}
    trace_id = payload.get("trace_id")

    if routing_key == "producto.registrado":
        codigo = datos.get("codigo", "?")
        nombre = datos.get("nombre", "")
        _guardar("ADMIN", f"Nuevo producto registrado: {codigo} {nombre}".strip(), codigo, evento, trace_id)

    elif routing_key == "ticket.creado":
        # Solo los tickets EN_COLA (SOPORTE) requieren a un técnico.
        if datos.get("estado") == "EN_COLA":
            id_ticket = datos.get("idTicket", "?")
            _guardar("TECNICO", f"Nuevo equipo en cola: {id_ticket}", id_ticket, evento, trace_id)

    elif routing_key == "ticket.listo":
        # El equipo ya fue diagnosticado: Recepción puede cobrar y entregar.
        id_ticket = datos.get("idTicket", "?")
        _guardar("CAJA", f"Equipo listo para cobro y entrega: {id_ticket}", id_ticket, evento, trace_id)


async def iniciar_consumidor():
    """Escucha eventos de RabbitMQ y genera notificaciones. Reintenta si se cae."""
    while True:
        try:
            connection = await aio_pika.connect_robust(RABBITMQ_URL)
            async with connection:
                channel = await connection.channel()
                exchange = await channel.declare_exchange(
                    "tickets.eventos", aio_pika.ExchangeType.TOPIC, durable=True
                )
                queue = await channel.declare_queue("notificaciones_queue", durable=True)
                # Escucha los eventos de interés.
                await queue.bind(exchange, routing_key="ticket.creado")
                await queue.bind(exchange, routing_key="ticket.listo")
                await queue.bind(exchange, routing_key="producto.registrado")

                logger.info("🎧 Servicio de Notificaciones conectado y escuchando eventos...")

                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        async with message.process():
                            payload = json.loads(message.body.decode())
                            logger.extra["correlation_id"] = message.correlation_id or "N/A"
                            _enrutar(message.routing_key, payload)

        except Exception as e:
            logger.error(f"🚨 Consumidor de Notificaciones caído, reintentando en 5s: {e}")
            await asyncio.sleep(5)

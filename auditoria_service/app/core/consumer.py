import aio_pika
import json
import os
import asyncio
from app.core.logger import get_logger
from app.core.store import registrar_evento

# Usamos el nombre del servicio para identificar los logs
logger = get_logger("auditoria-service")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")


async def iniciar_consumidor():
    """
    Se conecta a RabbitMQ y escucha los eventos de tickets permanentemente.

    BUG CORREGIDO: antes, si la PRIMERA conexión fallaba (RabbitMQ aún no acepta
    AMQP al arrancar — su healthcheck 'ping' da 'healthy' antes de abrir el 5672),
    el `except` mataba la corrutina y el consumidor NUNCA reintentaba → 0 consumers
    y los eventos quedaban atascados en la cola.

    Ahora envolvemos todo en un bucle infinito con reintento: si falla el arranque
    o se cae la conexión, espera 5s y vuelve a intentar. (`connect_robust` solo
    reconecta tras una PRIMERA conexión exitosa; el bucle cubre justamente ese hueco.)
    """
    while True:
        try:
            # 1. Conexión a RabbitMQ
            connection = await aio_pika.connect_robust(RABBITMQ_URL)
            async with connection:
                channel = await connection.channel()

                # 2. Conectarse al mismo "Megáfono" (Exchange) que usa Tickets
                exchange = await channel.declare_exchange(
                    "tickets.eventos", aio_pika.ExchangeType.TOPIC, durable=True
                )

                # 3. Crear una cola exclusiva para Auditoría
                queue = await channel.declare_queue("auditoria_tickets_queue", durable=True)

                # 4. Vincular la cola al megáfono (cualquier evento "ticket.*")
                await queue.bind(exchange, routing_key="ticket.*")

                logger.info("🎧 Servicio de Auditoría conectado y escuchando eventos en RabbitMQ...")

                # 5. Bucle escuchando mensajes
                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        async with message.process():
                            payload = json.loads(message.body.decode())

                            # ¡TRAZABILIDAD! Extraemos el ID original
                            trace_id = message.correlation_id
                            logger.extra["correlation_id"] = trace_id or "N/A"

                            evento_nombre = payload.get("evento")
                            datos = payload.get("datos") or {}
                            logger.info(
                                f"📝 EXPEDIENTE AUDITADO | Evento: {evento_nombre} "
                                f"| Sede: {datos.get('sede')} | ID: {datos.get('idTicket')}"
                            )

                            # Guardar en el store en memoria para que el GET lo exponga.
                            registrar_evento(evento=evento_nombre, datos=datos, trace_id=trace_id)

        except Exception as e:
            # No matamos la tarea: esperamos y reintentamos (arranque o reconexión).
            logger.error(f"🚨 Consumidor RabbitMQ caído, reintentando en 5s: {e}")
            await asyncio.sleep(5)

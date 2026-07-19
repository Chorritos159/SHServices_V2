import aio_pika
import json
import os
import asyncio
from app.core.logger import get_logger

logger = get_logger("rabbitmq-publisher")

# Default apunta al contenedor 'rabbitmq' (Compose inyecta RABBITMQ_URL).
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")

_connection = None
_lock = asyncio.Lock()


async def get_connection() -> aio_pika.RobustConnection:
    global _connection
    if _connection is None or _connection.is_closed:
        async with _lock:
            if _connection is None or _connection.is_closed:
                _connection = await asyncio.wait_for(
                    aio_pika.connect_robust(RABBITMQ_URL),
                    timeout=5.0
                )
    return _connection


async def publicar_evento(exchange_name: str, routing_key: str, mensaje: dict):
    """Publica un evento asincrono en RabbitMQ para no bloquear el flujo.

    Se llama desde un BackgroundTask: la operacion de negocio YA respondio al
    cliente. Por eso un fallo aqui NO se propaga (no hay a quien devolverle un
    error) pero SI se loguea con result=error: el evento se perdio y eso tiene
    que quedar visible en la traza, no desaparecer en silencio.
    """
    trace_id = mensaje.get("trace_id", "N/A")
    logger.extra["correlation_id"] = trace_id
    evento = mensaje.get("evento", routing_key)

    try:
        with logger.operacion("publicar_evento", event=evento, routingKey=routing_key) as op:
            connection = await get_connection()
            async with connection.channel() as channel:
                # Topic exchange durable: los eventos sobreviven a un reinicio
                # del broker y esperan a que el consumidor vuelva.
                exchange = await channel.declare_exchange(
                    exchange_name,
                    aio_pika.ExchangeType.TOPIC,
                    durable=True,
                )
                cuerpo_mensaje = aio_pika.Message(
                    body=json.dumps(mensaje).encode(),
                    content_type="application/json",
                    correlation_id=trace_id,
                )
                await exchange.publish(cuerpo_mensaje, routing_key=routing_key)
                op.mensaje = f"Evento '{evento}' publicado en '{exchange_name}' (routing key: {routing_key})."
    except Exception:
        # Ya quedo logueado con result=error, errorType y errorMessage por el
        # context manager. Se corta aqui no tumbar el BackgroundTask.
        pass

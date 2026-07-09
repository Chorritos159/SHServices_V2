import aio_pika
import json
import os
from app.core.logger import get_logger

logger = get_logger("rabbitmq-publisher")

# Usamos localhost para desarrollo local fuera de Docker
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")

async def publicar_evento(exchange_name: str, routing_key: str, mensaje: dict):
    """Publica un evento asíncrono en RabbitMQ para no bloquear el flujo."""
    try:
        connection = await aio_pika.connect_robust(RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            # Declaramos el Topic Exchange (El megáfono)
            exchange = await channel.declare_exchange(
                exchange_name, 
                aio_pika.ExchangeType.TOPIC, 
                durable=True
            )
            
            cuerpo_mensaje = aio_pika.Message(
                body=json.dumps(mensaje).encode(),
                content_type="application/json",
                correlation_id=mensaje.get("trace_id", "N/A")
            )
            
            await exchange.publish(cuerpo_mensaje, routing_key=routing_key)
            logger.info(f"✅ Evento '{routing_key}' publicado con éxito en RabbitMQ.")
            
    except Exception as e:
        logger.error(f"🚨 Error de conexión con RabbitMQ: {e}")
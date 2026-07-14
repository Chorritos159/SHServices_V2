import aio_pika
import json
import os
import asyncio
from app.core.logger import get_logger

# Usamos el nombre del servicio para identificar los logs
logger = get_logger("auditoria-service")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")

async def iniciar_consumidor():
    """Se conecta a RabbitMQ y escucha todos los eventos de tickets permanentemente."""
    try:
        # 1. Conexión a RabbitMQ
        connection = await aio_pika.connect_robust(RABBITMQ_URL)
        channel = await connection.channel()

        # 2. Conectarse al mismo "Megáfono" (Exchange) que usa Tickets
        exchange = await channel.declare_exchange("tickets.eventos", aio_pika.ExchangeType.TOPIC, durable=True)
        
        # 3. Crear una cola exclusiva para Auditoría
        queue = await channel.declare_queue("auditoria_tickets_queue", durable=True)
        
        # 4. Vincular la cola al megáfono (Escucha cualquier evento que empiece con "ticket.")
        await queue.bind(exchange, routing_key="ticket.*")

        logger.info("🎧 Servicio de Auditoría conectado y escuchando eventos en RabbitMQ...")

        # 5. Bucle infinito escuchando mensajes
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    # Extraer el contenido
                    payload = json.loads(message.body.decode())
                    
                    # ¡TRAZABILIDAD! Extraemos el ID original
                    trace_id = message.correlation_id
                    logger.extra["correlation_id"] = trace_id or "N/A"
                    
                    # Imprimir en consola simulando guardado en Base de Datos
                    evento_nombre = payload.get("evento")
                    datos = payload.get("datos")
                    logger.info(f"📝 EXPEDIENTE AUDITADO | Evento: {evento_nombre} | Sede: {datos.get('sede')} | ID: {datos.get('idTicket')}")
                    
    except Exception as e:
        logger.error(f"🚨 Error crítico en consumidor de RabbitMQ: {e}")
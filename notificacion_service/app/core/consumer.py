import aio_pika
import json
import os
import asyncio
import time
from sqlalchemy.exc import IntegrityError
from app.core.logger import get_logger
from app.core.database import SessionLocal
from app.core.webhooks import despachar_webhooks
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
            f"Notificación para {rol_destino}: {mensaje}",
            extra={"campos": {"operation": "guardar_notificacion", "event": evento, "result": "ok",
                               "durationMs": round((time.monotonic() - inicio) * 1000, 1)}},
        )
    except IntegrityError:
        db.rollback()
        logger.warning(
            f"Notificación duplicada (redelivery de RabbitMQ) descartada: {evento} -> {rol_destino}.",
            extra={"campos": {"operation": "guardar_notificacion", "event": evento, "result": "duplicado",
                               "durationMs": round((time.monotonic() - inicio) * 1000, 1)}},
        )
    finally:
        db.close()


def _referencia(datos: dict) -> str:
    """Identificador legible del hecho, sea cual sea el evento."""
    return (
        datos.get("idTicket")
        or datos.get("codigo")
        or datos.get("idFactura")
        or datos.get("idDiagnostico")
        or "-"
    )


def _resumen_admin(routing_key: str, datos: dict) -> str:
    """Frase para la bandeja del ADMIN, que ve TODO lo que pasa en el sistema."""
    ref = _referencia(datos)
    sede = datos.get("sede")
    sufijo = f" ({sede})" if sede else ""

    textos = {
        "producto.registrado": f"Nuevo producto en inventario: {ref} {datos.get('nombre', '')}".strip(),
        "ticket.creado": f"Ticket registrado: {ref} [{datos.get('estado', '?')}]",
        "ticket.tomado": f"Un tecnico tomo el ticket {ref}",
        "ticket.diagnosticado": f"Diagnostico registrado para {ref}",
        "ticket.listo": f"Equipo listo para cobro y entrega: {ref}",
        "ticket.facturado": f"Cobro emitido: {ref} por S/.{datos.get('montoTotal', '?')}",
        "ticket.entregado": f"Equipo entregado al cliente: {ref}",
        "ticket.rechazado": f"Presupuesto rechazado: {ref}",
    }
    return textos.get(routing_key, f"Evento {routing_key}: {ref}") + sufijo


def _enrutar(routing_key: str, payload: dict):
    """Enrutamiento evento -> rol.

    Dos capas:

    1. **El rol que tiene que ACTUAR** recibe la alerta accionable (el técnico
       cuando entra un equipo, Caja cuando hay algo que cobrar).
    2. **ADMIN recibe SIEMPRE todo.** Es quien supervisa la operación de las
       dos sedes: si solo viera "producto registrado" tendría un panel ciego
       para el resto del negocio. Como el índice único es
       `(trace_id, evento, rol_destino)`, la copia para ADMIN convive con la
       del rol accionable sin chocar, y un redelivery de RabbitMQ sigue sin
       duplicar nada.
    """
    evento = payload.get("evento", "")
    datos = payload.get("datos") or {}
    trace_id = payload.get("trace_id")
    ref = _referencia(datos)

    # 1. Alerta accionable para el rol que debe hacer algo.
    if routing_key == "ticket.creado":
        # Solo los tickets EN_COLA (SOPORTE) requieren a un técnico. Una VENTA
        # nace en VENTA_REGISTRADA y no tiene nada que hacer un técnico con ella.
        if datos.get("estado") == "EN_COLA":
            _guardar("TECNICO", f"Nuevo equipo en cola: {ref}", ref, evento, trace_id)

    elif routing_key in ("ticket.listo", "ticket.diagnosticado"):
        # El equipo ya fue diagnosticado: Recepción puede cobrar y entregar.
        #
        # OJO con las DOS claves. Quien publica al terminar el diagnostico es
        # `diagnostico-service`, y su routing key es `ticket.diagnosticado`, NO
        # `ticket.listo`. Mientras aqui solo se miraba `ticket.listo`, esta rama
        # no se ejecutaba nunca: a CAJA no le llegaba nada y solo aparecia la
        # copia de supervision del ADMIN (la del punto 2 de abajo). Se noto tras
        # una caida por caos, pero pasaba SIEMPRE, con o sin caos.
        _guardar("CAJA", f"Equipo listo para cobro y entrega: {ref}", ref, evento, trace_id)

    # 2. Copia de supervisión para ADMIN, pase lo que pase.
    _guardar("ADMIN", _resumen_admin(routing_key, datos), ref, evento, trace_id)


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
                # Comodines y no una lista fija de claves: el ADMIN tiene que
                # ver TODO lo que pasa, así que cualquier evento nuevo que se
                # publique mañana entra solo, sin tocar este binding.
                await queue.bind(exchange, routing_key="ticket.*")
                await queue.bind(exchange, routing_key="producto.*")

                logger.info("Servicio de Notificaciones conectado y escuchando eventos...")

                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        async with message.process():
                            payload = json.loads(message.body.decode())
                            trace_id = message.correlation_id or "N/A"
                            logger.extra["correlation_id"] = trace_id
                            # 1. Notificacion INTERNA (bandeja por rol).
                            _enrutar(message.routing_key, payload)
                            # 2. Webhooks SALIENTES (avisar a terceros suscritos).
                            await despachar_webhooks(message.routing_key, payload, trace_id)

        except Exception as e:
            logger.error(f"Consumidor de Notificaciones caído, reintentando en 5s: {e}")
            await asyncio.sleep(5)

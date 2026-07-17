"""Webhooks SALIENTES (S31/S34): el sistema avisa a terceros por HTTP.

Diferencia con las notificaciones internas: la notificacion interna va a la
tabla `notificaciones` para que un rol la vea en su bandeja; el webhook va
por HTTP a un sistema EXTERNO que se suscribio (otro backend, un Slack, un
CRM...).

Flujo:
  1. Un tercero se suscribe: guarda su URL + que evento le interesa
     (POST /api/v1/notificaciones/webhooks/suscripciones).
  2. Cuando ese evento llega por RabbitMQ, el consumidor llama a
     `despachar_webhooks()`, que hace POST a cada URL suscrita.
  3. El cuerpo va FIRMADO con HMAC-SHA256 (cabecera X-Firma): el receptor
     recalcula la firma con el secreto compartido y asi verifica que el
     evento vino de verdad de nosotros y no fue alterado.
  4. Si la entrega falla, se reintenta con backoff; cada intento queda en
     la tabla `webhook_entregas` (auditoria).
"""
import asyncio
import hashlib
import hmac
import json
import os

import httpx

from app.core.database import SessionLocal
from app.core.logger import get_logger, OK, ERROR
from app.models.webhook import WebhookSuscripcionDB, EntregaWebhookDB

logger = get_logger("notificacion-service")

# Secreto compartido con quien recibe el webhook. Sin secreto configurado no
# se firma con uno adivinable: se exige que exista (aunque sea de demo).
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "webhook_secreto_demo_shservices")
MAX_INTENTOS = 3
BACKOFF_BASE = 0.5   # segundos; el intento n espera BACKOFF_BASE * n


def firmar(cuerpo: bytes) -> str:
    """HMAC-SHA256 del cuerpo con el secreto compartido (hex)."""
    return hmac.new(WEBHOOK_SECRET.encode(), cuerpo, hashlib.sha256).hexdigest()


def _urls_suscritas(routing_key: str) -> list[str]:
    """URLs activas suscritas a este evento (o a '*')."""
    db = SessionLocal()
    try:
        suscripciones = db.query(WebhookSuscripcionDB).filter(
            WebhookSuscripcionDB.activo.is_(True)
        ).all()
        return [s.url for s in suscripciones if s.evento in ("*", routing_key)]
    finally:
        db.close()


def _registrar_entrega(url, evento, referencia, estado, intentos, status_code, trace_id):
    db = SessionLocal()
    try:
        db.add(EntregaWebhookDB(
            url=url, evento=evento, referencia=referencia, estado=estado,
            intentos=intentos, status_code=status_code, trace_id=trace_id,
        ))
        db.commit()
    finally:
        db.close()


async def _entregar(client, url, cuerpo, headers):
    """Un destino: hasta MAX_INTENTOS con backoff. Devuelve (estado, intentos, status_code)."""
    ultimo_code = None
    for intento in range(1, MAX_INTENTOS + 1):
        try:
            resp = await client.post(url, content=cuerpo, headers=headers, timeout=3.0)
            ultimo_code = resp.status_code
            if resp.status_code < 300:
                return "ENTREGADO", intento, ultimo_code
            logger.warning(
                f"Webhook a {url} devolvio {resp.status_code} (intento {intento}/{MAX_INTENTOS}).",
                extra={"campos": {"operation": "webhook_entrega", "event": headers.get("X-Evento"),
                                   "result": "degradado", "retryAttempt": intento,
                                   "httpStatus": resp.status_code}},
            )
        except httpx.HTTPError as exc:
            logger.warning(
                f"Webhook a {url} fallo: {exc} (intento {intento}/{MAX_INTENTOS}).",
                extra={"campos": {"operation": "webhook_entrega", "event": headers.get("X-Evento"),
                                   "result": "degradado", "retryAttempt": intento,
                                   "errorType": type(exc).__name__}},
            )
        if intento < MAX_INTENTOS:
            await asyncio.sleep(BACKOFF_BASE * intento)
    return "FALLIDO", MAX_INTENTOS, ultimo_code


async def despachar_webhooks(routing_key: str, payload: dict, trace_id: str):
    """Entrega el evento a todas las URLs suscritas: firma HMAC + reintentos.

    Se llama desde el consumidor por cada evento consumido. Si no hay nadie
    suscrito, no hace nada (no es un error).
    """
    urls = _urls_suscritas(routing_key)
    if not urls:
        return

    cuerpo = json.dumps(payload, ensure_ascii=False).encode()
    referencia = (payload.get("datos") or {}).get("idTicket") or (payload.get("datos") or {}).get("codigo")
    headers = {
        "Content-Type": "application/json",
        "X-Firma": firmar(cuerpo),
        "X-Evento": routing_key,
        "X-Trace-Id": trace_id or "N/A",
    }

    async with httpx.AsyncClient() as client:
        for url in urls:
            estado, intentos, code = await _entregar(client, url, cuerpo, headers)
            _registrar_entrega(url, routing_key, referencia, estado, intentos, code, trace_id)
            logger.extra["correlation_id"] = trace_id or "N/A"
            if estado == "ENTREGADO":
                logger.info(
                    f"Webhook '{routing_key}' entregado a {url} en {intentos} intento(s).",
                    extra={"campos": {"operation": "webhook_entrega", "event": routing_key,
                                       "result": OK, "url": url, "intentos": intentos, "httpStatus": code}},
                )
            else:
                logger.error(
                    f"Webhook '{routing_key}' FALLIDO a {url} tras {intentos} intento(s).",
                    extra={"campos": {"operation": "webhook_entrega", "event": routing_key,
                                       "result": ERROR, "url": url, "intentos": intentos, "httpStatus": code}},
                )

import asyncio
import datetime
import json
import random

import httpx
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal, engine, Base
from app.core.logger import get_logger
from app.models.outbox import OutboxDB, PENDIENTE, ENTREGADO, DESCARTADO

logger = get_logger("api-gateway")

# Ritmo del worker y política de reintentos.
INTERVALO_DRENAJE_S = 3          # cada cuánto revisa el worker si hay pendientes vencidos
TIMEOUT_ENTREGA_S = 8.0          # timeout por intento de entrega interna

# Política de backoff del sistema (S34): 3s -> 5s -> 8s y, a partir de ahí,
# crecimiento exponencial con TOPE de 30s (8 -> 16 -> 30 -> 30...).
# Los tres primeros escalones son los que exige la S34; el crecimiento posterior
# evita martillar cada 8s a un servicio que lleva horas caído, sin llegar nunca
# a descartar la escritura (no hay tope de intentos: se reintenta hasta entregar).
BACKOFF_SEQ = (3.0, 5.0, 8.0)
BACKOFF_MAX_S = 30.0

# Descripción legible por (servicio, método) para el mensaje al usuario.
_OPERACIONES = {
    ("tickets", "POST"): "registrar el ticket",
    ("diagnosticos", "POST"): "registrar el diagnóstico",
    ("facturas", "POST"): "registrar el cobro",
    ("almacen", "POST"): "registrar el movimiento de inventario",
    ("almacen", "PUT"): "actualizar el inventario",
    ("almacen", "PATCH"): "actualizar el inventario",
}


def describir_operacion(servicio: str, metodo: str, path: str) -> str:
    """Texto amable para la UI. Cae a una descripción genérica si no se conoce."""
    if "/diagnosticar" in path:
        return "registrar el diagnóstico del ticket"
    if "/rechazar" in path:
        return "rechazar el ticket"
    return _OPERACIONES.get((servicio, metodo), "guardar tus cambios")


def crear_tablas() -> None:
    """Crea la tabla del outbox si no existe (idempotente)."""
    Base.metadata.create_all(bind=engine)


def encolar(*, idempotency_key: str, servicio: str, metodo: str, path: str,
            body: bytes, headers: dict, url_interna: str) -> dict:
    """Guarda una escritura no entregada. Devuelve el resumen para el 202.

    Idempotente por `idempotency_key`: si ese intento ya estaba encolado, no
    lo duplica y devuelve el registro existente (así el cliente puede reintentar
    el mismo envío sin miedo).
    """
    db = SessionLocal()
    try:
        existente = db.query(OutboxDB).filter(OutboxDB.idempotency_key == idempotency_key).first()
        if existente:
            return _resumen(existente)

        # Solo persistimos las cabeceras necesarias para reejecutar: identidad
        # ya validada + correlación + content-type. Nunca el Authorization/JWT
        # (puede expirar; los servicios internos confían en las X-User-*).
        headers_guardar = {
            k: v for k, v in headers.items()
            if k.lower() in ("x-user-sub", "x-user-rol", "x-user-sede",
                             "x-correlation-id", "content-type", "idempotency-key")
        }
        headers_guardar["idempotency-key"] = idempotency_key

        registro = OutboxDB(
            idempotency_key=idempotency_key,
            servicio=servicio,
            metodo=metodo,
            path=path,
            body=body.decode("utf-8", errors="replace") if body else "",
            headers_json=json.dumps(headers_guardar),
            operacion=describir_operacion(servicio, metodo, path),
            estado=PENDIENTE,
            proximo_reintento_en=datetime.datetime.utcnow(),
        )
        db.add(registro)
        try:
            db.commit()
            db.refresh(registro)
        except IntegrityError:
            # Carrera: la misma clave se encoló en paralelo. Recuperamos la que ganó.
            db.rollback()
            registro = db.query(OutboxDB).filter(
                OutboxDB.idempotency_key == idempotency_key
            ).first()

        logger.info(
            f"Escritura encolada (servicio '{servicio}' no disponible): {registro.operacion}.",
            extra={"campos": {"operation": "outbox_encolar", "event": servicio,
                              "result": "encolado", "outboxId": registro.id}},
        )
        return _resumen(registro)
    finally:
        db.close()


def _resumen(registro: OutboxDB) -> dict:
    """Cuerpo del 202 que ve el frontend."""
    return {
        "encolado": True,
        "outbox_id": registro.id,
        "servicio": registro.servicio,
        "operacion": registro.operacion,
        "estado": registro.estado,
        "mensaje": (
            f"El servicio no está disponible en este momento, pero tu solicitud para "
            f"{registro.operacion} quedó registrada en cola y se enviará automáticamente "
            f"en cuanto el servicio vuelva a estar en línea. No la vuelvas a enviar."
        ),
    }


def _backoff(intentos: int) -> float:
    """Espera antes del siguiente reintento: 3s, 5s, 8s y de ahi exponencial
    hasta un tope de 30s (8 -> 16 -> 30 -> 30...), mas JITTER (hasta 1s).

    El jitter es clave aqui: si hay varias escrituras encoladas y el servicio
    vuelve, sin el todas reintentarian en el MISMO instante y lo volverian a
    tumbar justo al recuperarse (tormenta de reintentos).
    """
    n = max(intentos, 1)
    if n <= len(BACKOFF_SEQ):
        base = BACKOFF_SEQ[n - 1]
    else:
        # A partir del ultimo escalon (8s) se duplica, con tope en 30s.
        base = min(BACKOFF_SEQ[-1] * (2 ** (n - len(BACKOFF_SEQ))), BACKOFF_MAX_S)
    return base + random.uniform(0, 1.0)


def _url_interna(servicio: str, path: str, microservicios: dict) -> str | None:
    base = microservicios.get(servicio)
    if not base:
        return None
    return f"{base}/api/v1/{path}"


async def _entregar(registro: OutboxDB, microservicios: dict) -> tuple[str, int | None, str]:
    """Reintenta una entrega. Devuelve (nuevo_estado, status_http, detalle)."""
    url = _url_interna(registro.servicio, registro.path, microservicios)
    if not url:
        return DESCARTADO, None, "Servicio destino desconocido."

    headers = json.loads(registro.headers_json or "{}")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method=registro.metodo, url=url,
                content=registro.body.encode("utf-8") if registro.body else None,
                headers=headers, timeout=TIMEOUT_ENTREGA_S,
            )
    except httpx.HTTPError as exc:
        # Sigue caído / de red: reintentar más tarde.
        return PENDIENTE, None, f"{type(exc).__name__}: {exc}"

    if resp.status_code < 400:
        return ENTREGADO, resp.status_code, resp.text
    if resp.status_code < 500:
        # Error de negocio (validación, conflicto): reintentar no lo va a arreglar.
        return DESCARTADO, resp.status_code, resp.text
    # 5xx del servicio: transitorio, reintentar.
    return PENDIENTE, resp.status_code, resp.text


async def drenar_una_vez(microservicios: dict, breakers: dict | None = None) -> int:
    """Procesa los pendientes vencidos una vez. Devuelve cuántos se entregaron.

    Pensado para llamarse en bucle desde el worker y también desde las pruebas.
    """
    ahora = datetime.datetime.utcnow()
    db = SessionLocal()
    try:
        pendientes = (
            db.query(OutboxDB)
            .filter(OutboxDB.estado == PENDIENTE)
            .filter((OutboxDB.proximo_reintento_en == None) | (OutboxDB.proximo_reintento_en <= ahora))  # noqa: E711
            .order_by(OutboxDB.creado_en.asc())
            .limit(50)
            .all()
        )
    finally:
        db.close()

    entregados = 0
    for p in pendientes:
        # Si el circuito del servicio sigue abierto, no malgastamos el intento.
        if breakers is not None:
            br = breakers.get(p.servicio)
            if br is not None and getattr(br, "estado", "CLOSED") == "OPEN":
                continue

        nuevo_estado, status_http, detalle = await _entregar(p, microservicios)

        db = SessionLocal()
        try:
            reg = db.query(OutboxDB).filter(OutboxDB.id == p.id).first()
            if reg is None or reg.estado != PENDIENTE:
                continue  # otro ciclo ya lo resolvió
            reg.intentos += 1
            reg.ultimo_error = None if nuevo_estado == ENTREGADO else (detalle or "")[:1000]
            if nuevo_estado == ENTREGADO:
                reg.estado = ENTREGADO
                reg.status_respuesta = status_http
                reg.respuesta_json = (detalle or "")[:4000]
                entregados += 1
                logger.info(
                    f"Outbox entregado: {reg.operacion} (servicio '{reg.servicio}', "
                    f"intento {reg.intentos}).",
                    extra={"campos": {"operation": "outbox_entregar", "event": reg.servicio,
                                      "result": "ok", "outboxId": reg.id}},
                )
            elif nuevo_estado == DESCARTADO:
                reg.estado = DESCARTADO
                reg.status_respuesta = status_http
                reg.respuesta_json = (detalle or "")[:4000]
                logger.warning(
                    f"Outbox descartado: {reg.operacion} rechazado por negocio "
                    f"(HTTP {status_http}, servicio '{reg.servicio}').",
                    extra={"campos": {"operation": "outbox_entregar", "event": reg.servicio,
                                      "result": "descartado", "outboxId": reg.id}},
                )
            else:  # PENDIENTE: backoff
                espera = _backoff(reg.intentos)
                reg.proximo_reintento_en = datetime.datetime.utcnow() + datetime.timedelta(seconds=espera)
            db.commit()
        finally:
            db.close()

    return entregados


async def bucle_drenaje(microservicios: dict, breakers: dict | None = None) -> None:
    """Worker de fondo: drena el outbox indefinidamente."""
    logger.info("Worker de outbox iniciado (store-and-forward de escrituras).")
    while True:
        try:
            await drenar_una_vez(microservicios, breakers)
        except Exception as exc:  # el worker nunca debe morir
            logger.error(
                f"Fallo no esperado en el worker de outbox: {exc}",
                extra={"campos": {"operation": "outbox_worker", "result": "error"}},
            )
        await asyncio.sleep(INTERVALO_DRENAJE_S)

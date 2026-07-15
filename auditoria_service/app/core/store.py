"""
Capa de acceso a la traza de auditoría (Fase 4: ahora en PostgreSQL).

Antes era un deque en memoria (se perdía al reiniciar). Ahora persiste en la
tabla `auditoria_eventos`. La firma de las funciones NO cambió, así que ni el
consumidor ni el endpoint GET necesitaron tocarse.
"""
import json
from datetime import timezone
from typing import Any

from app.core.database import SessionLocal
from app.models.evento import EventoAuditoriaDB


def registrar_evento(evento: str, datos: dict[str, Any], trace_id: str | None) -> None:
    """Persiste un evento recibido desde RabbitMQ, siempre con su correlationId."""
    db = SessionLocal()
    try:
        registro = EventoAuditoriaDB(
            evento=evento,
            trace_id=trace_id,                 # correlationId (FF-DEP-05)
            sede=datos.get("sede"),
            id_ticket=datos.get("idTicket"),
            datos_json=json.dumps(datos, ensure_ascii=False),
        )
        db.add(registro)
        db.commit()
    finally:
        db.close()


def obtener_eventos(limite: int = 100) -> list[dict[str, Any]]:
    """Devuelve los eventos más recientes primero (para pintar la tabla del Admin)."""
    db = SessionLocal()
    try:
        filas = (
            db.query(EventoAuditoriaDB)
            .order_by(EventoAuditoriaDB.id.desc())
            .limit(limite)
            .all()
        )
        return [
            {
                "evento": f.evento,
                "trace_id": f.trace_id,
                "sede": f.sede,
                "idTicket": f.id_ticket,
                "recibido_en": f.recibido_en.replace(tzinfo=timezone.utc).isoformat(),
                "datos": json.loads(f.datos_json) if f.datos_json else {},
            }
            for f in filas
        ]
    finally:
        db.close()

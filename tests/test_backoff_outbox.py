"""Política de backoff del sistema (S34) y utilidades del outbox.

El requisito explícito de la sesión es un backoff **escalonado 3s / 5s / 8s**.
Se prueba sobre el código real del worker del outbox, no sobre una copia.
"""
from app.core.outbox import BACKOFF_MAX_S, BACKOFF_SEQ, _backoff, describir_operacion

JITTER_MAX = 1.0   # el backoff añade U(0, 1s) para desincronizar reintentos


def test_la_secuencia_exigida_es_3_5_8():
    assert BACKOFF_SEQ == (3.0, 5.0, 8.0)


def test_los_tres_primeros_reintentos_esperan_3_5_y_8_segundos():
    for intento, esperado in ((1, 3.0), (2, 5.0), (3, 8.0)):
        espera = _backoff(intento)
        assert esperado <= espera <= esperado + JITTER_MAX, (
            f"el intento {intento} deberia esperar ~{esperado}s (+jitter), fue {espera:.2f}s"
        )


def test_despues_del_tercero_sigue_creciendo_pero_con_tope_de_30s():
    # 8 -> 16 -> 30 y ahi se queda: no conviene martillar cada 8s a un
    # servicio que lleva horas caido, pero tampoco esperar indefinidamente.
    assert 16.0 <= _backoff(4) <= 16.0 + JITTER_MAX
    for intento in (5, 6, 10, 50):
        assert _backoff(intento) <= BACKOFF_MAX_S + JITTER_MAX


def test_el_backoff_es_monotono_no_decrece():
    esperas = [_backoff(i) for i in range(1, 8)]
    # Se compara la base (sin jitter) permitiendo el margen del propio jitter.
    for previo, siguiente in zip(esperas, esperas[1:]):
        assert siguiente >= previo - JITTER_MAX


def test_hay_jitter_para_evitar_la_tormenta_de_reintentos():
    """Sin jitter, todas las escrituras encoladas reintentarian a la vez."""
    muestras = {_backoff(1) for _ in range(40)}
    assert len(muestras) > 1, "el backoff deberia variar entre llamadas (jitter)"
    assert all(3.0 <= m <= 4.0 for m in muestras)


def test_intento_cero_o_negativo_no_rompe():
    assert _backoff(0) >= 3.0
    assert _backoff(-5) >= 3.0


# ── Mensaje que ve el usuario cuando algo se encola ──────────────────────
def test_describe_la_operacion_encolada_en_lenguaje_de_negocio():
    assert describir_operacion("tickets", "POST", "tickets/") == "registrar el ticket"
    assert describir_operacion("facturas", "POST", "facturas/") == "registrar el cobro"
    assert "diagnóstico" in describir_operacion("tickets", "POST", "tickets/X/diagnosticar")
    assert "rechazar" in describir_operacion("tickets", "POST", "tickets/X/rechazar")


def test_una_operacion_desconocida_no_deja_al_usuario_sin_mensaje():
    assert describir_operacion("servicio-raro", "PUT", "loquesea") == "guardar tus cambios"

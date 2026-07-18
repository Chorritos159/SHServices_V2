"""Circuit breaker: transiciones CLOSED -> OPEN -> HALF_OPEN -> CLOSED.

Es el mecanismo de resiliencia central del Gateway, así que se prueba su
máquina de estados de forma aislada (sin red ni dependencias).
"""
from app.core.resilience import CircuitBreaker


def _breaker(**kw):
    # Cooldown corto para no dormir en los tests.
    return CircuitBreaker("prueba", cooldown_seg=0.05, **kw)


def test_arranca_cerrado_y_deja_pasar():
    br = _breaker()
    assert br.estado == "CLOSED"
    assert br.permite() is True


def test_abre_tras_los_fallos_consecutivos_configurados():
    br = _breaker(umbral_consecutivos=3)
    for _ in range(2):
        br.registrar(False)
    assert br.estado == "CLOSED", "no debe abrir antes de llegar al umbral"

    br.registrar(False)                      # tercer fallo seguido
    assert br.estado == "OPEN"
    assert br.permite() is False, "con el circuito abierto debe hacer fail-fast"


def test_un_exito_reinicia_la_racha_de_fallos():
    """Aisla la via de 'fallos consecutivos'.

    `min_muestras` alto desactiva la OTRA via de apertura (tasa de error en
    ventana); si no, esta secuencia abriria por 4 fallos sobre 5 muestras (80%)
    y no estariamos probando lo que dice el nombre del test.
    """
    br = _breaker(umbral_consecutivos=3, min_muestras=99)
    br.registrar(False)
    br.registrar(False)
    br.registrar(True)                       # corta la racha
    br.registrar(False)
    br.registrar(False)
    assert br.estado == "CLOSED", "dos fallos tras un exito no deben abrirlo"


def test_abre_por_tasa_de_error_aunque_no_sean_consecutivos():
    # 4 muestras minimo, 50% de error: alterna exito/fallo.
    br = _breaker(umbral_consecutivos=99, min_muestras=4, umbral_error_rate=0.5)
    br.registrar(True)
    br.registrar(False)
    br.registrar(True)
    br.registrar(False)                      # 2/4 = 50%
    assert br.estado == "OPEN"


def test_pasa_a_half_open_al_vencer_el_cooldown_y_cierra_si_la_sonda_va_bien():
    import time
    br = _breaker(umbral_consecutivos=1)
    br.registrar(False)
    assert br.estado == "OPEN"

    time.sleep(0.06)                         # vence el cooldown
    assert br.permite() is True              # deja pasar UNA sonda
    assert br.estado == "HALF_OPEN"

    br.registrar(True)                       # la sonda respondio bien
    assert br.estado == "CLOSED"


def test_en_half_open_solo_deja_pasar_una_sonda():
    import time
    br = _breaker(umbral_consecutivos=1)
    br.registrar(False)
    time.sleep(0.06)

    assert br.permite() is True              # la sonda
    assert br.permite() is False, "una segunda llamada no debe colarse con la sonda en vuelo"


def test_si_la_sonda_falla_vuelve_a_abrir():
    import time
    br = _breaker(umbral_consecutivos=1)
    br.registrar(False)
    time.sleep(0.06)
    br.permite()                             # HALF_OPEN
    br.registrar(False)                      # la sonda fallo
    assert br.estado == "OPEN"
    assert br.permite() is False


def test_cuenta_las_aperturas_para_la_metrica():
    import time
    br = _breaker(umbral_consecutivos=1)
    assert br.aperturas == 0
    br.registrar(False)
    time.sleep(0.06)
    br.permite()
    br.registrar(False)                      # reabre
    assert br.aperturas == 2


def test_estado_numerico_para_prometheus():
    import time
    br = _breaker(umbral_consecutivos=1)
    assert br.estado_numerico() == 0         # CLOSED
    br.registrar(False)
    assert br.estado_numerico() == 2         # OPEN
    time.sleep(0.06)
    br.permite()
    assert br.estado_numerico() == 1         # HALF_OPEN

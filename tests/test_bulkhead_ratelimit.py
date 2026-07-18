"""Bulkhead (aislamiento de recursos) y rate limit (backpressure)."""
import time

from app.core.bulkhead import Bulkhead
from app.core.ratelimit import TokenBucket


# ── Bulkhead ─────────────────────────────────────────────────────────────
def test_bulkhead_deja_entrar_hasta_el_limite_y_rechaza_el_siguiente():
    b = Bulkhead("tickets", limite=2)
    assert b.intentar_entrar() is True
    assert b.intentar_entrar() is True
    assert b.intentar_entrar() is False, "al llegar al cupo debe rechazar de inmediato"
    assert b.en_vuelo == 2


def test_bulkhead_libera_cupo_al_salir():
    b = Bulkhead("tickets", limite=1)
    b.intentar_entrar()
    assert b.intentar_entrar() is False
    b.salir()
    assert b.intentar_entrar() is True, "tras salir debe haber cupo de nuevo"


def test_bulkhead_no_baja_de_cero_aunque_se_llame_salir_de_mas():
    b = Bulkhead("tickets", limite=1)
    b.salir()
    b.salir()
    assert b.en_vuelo == 0


def test_bulkhead_ocupacion_para_decidir_el_shedding():
    b = Bulkhead("tickets", limite=10)
    for _ in range(7):
        b.intentar_entrar()
    # El Gateway descarta trafico de baja prioridad a partir del 70%.
    assert b.ocupacion() == 0.7


def test_bulkhead_aisla_servicios_entre_si():
    """Saturar un servicio NO debe consumir el cupo de otro (el objetivo del patron)."""
    tickets = Bulkhead("tickets", limite=1)
    almacen = Bulkhead("almacen", limite=1)
    tickets.intentar_entrar()
    assert tickets.intentar_entrar() is False   # tickets saturado
    assert almacen.intentar_entrar() is True    # almacen sigue sano


# ── Rate limit (token bucket) ────────────────────────────────────────────
def test_rate_limit_permite_la_rafaga_y_luego_rechaza():
    tb = TokenBucket(capacidad=3, tasa_por_seg=1)
    assert [tb.consumir() for _ in range(3)] == [True, True, True]
    assert tb.consumir() is False, "agotada la rafaga debe aplicar backpressure"


def test_rate_limit_repone_tokens_con_el_tiempo():
    tb = TokenBucket(capacidad=2, tasa_por_seg=50)   # 50/s => 1 token en 20ms
    tb.consumir()
    tb.consumir()
    assert tb.consumir() is False
    time.sleep(0.05)
    assert tb.consumir() is True, "tras esperar debe haberse repuesto al menos un token"


def test_rate_limit_no_acumula_mas_alla_de_su_capacidad():
    tb = TokenBucket(capacidad=2, tasa_por_seg=1000)
    time.sleep(0.05)                                  # daria para muchos tokens
    assert [tb.consumir() for _ in range(3)] == [True, True, False], \
        "el bucket no puede exceder su capacidad por mucho que espere"


def test_rate_limit_informa_cuanto_esperar():
    """El Gateway usa este valor para la cabecera Retry-After del 429."""
    tb = TokenBucket(capacidad=1, tasa_por_seg=1)
    tb.consumir()
    espera = tb.segundos_hasta_proximo_token()
    assert 0 < espera <= 1

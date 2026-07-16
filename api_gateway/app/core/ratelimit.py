"""Rate limiting global (S34): token bucket.

A diferencia del bulkhead (que protege a CADA dependencia), esto protege
al Gateway MISMO: una ráfaga que supere su capacidad de atender tráfico,
sin importar hacia qué servicio vaya ni quién la origine. Es la última
línea de defensa antes de que el proceso se sature.

Backpressure explícito: cuando no hay tokens, se responde 429 con
Retry-After en vez de aceptar la petición y colapsar bajo carga.
"""
import time


class TokenBucket:
    def __init__(self, capacidad: int, tasa_por_seg: float):
        self.capacidad = capacidad
        self.tasa = tasa_por_seg
        self.tokens = float(capacidad)
        self.ultimo = time.monotonic()

    def _rellenar(self):
        ahora = time.monotonic()
        transcurrido = ahora - self.ultimo
        self.tokens = min(self.capacidad, self.tokens + transcurrido * self.tasa)
        self.ultimo = ahora

    def consumir(self) -> bool:
        self._rellenar()
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

    def segundos_hasta_proximo_token(self) -> float:
        self._rellenar()
        if self.tasa <= 0:
            return 1.0
        faltante = max(0.0, 1 - self.tokens)
        return faltante / self.tasa

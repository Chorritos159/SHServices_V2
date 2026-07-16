"""Bulkhead (S34): aísla la capacidad de cada dependencia.

Si un microservicio se pone lento, sin bulkhead las llamadas hacia él se
acumulan y agotan los recursos (conexiones, memoria) que el Gateway
necesita para atender a los DEMÁS servicios sanos. El bulkhead limita
cuántas llamadas EN VUELO puede tener cada servicio a la vez.

Deliberadamente NO hace cola: una cola oculta ante saturación solo pospone
el fallo (y rompe el fail-fast del circuit breaker). Al llegar al límite,
se rechaza de inmediato con 503.

Corre en el event loop de asyncio (un solo hilo, un solo worker Gunicorn
tras la Fase 1): no requiere locks.
"""


class Bulkhead:
    def __init__(self, nombre: str, limite: int):
        self.nombre = nombre
        self.limite = limite
        self.en_vuelo = 0

    def intentar_entrar(self) -> bool:
        """True si hay cupo y lo reserva; False si está al límite (rechazar ya)."""
        if self.en_vuelo >= self.limite:
            return False
        self.en_vuelo += 1
        return True

    def salir(self):
        self.en_vuelo = max(0, self.en_vuelo - 1)

    def ocupacion(self) -> float:
        """Fracción 0..1 de cupo usado (para decidir shedding antes de saturar)."""
        return self.en_vuelo / self.limite if self.limite else 0.0

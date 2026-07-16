"""Circuit breaker formal (S34): CLOSED -> OPEN -> HALF_OPEN.

El gateway anterior solo traducia excepciones a 503/504 (no dejaba de llamar a
la dependencia enferma). Un circuit breaker de verdad tiene ESTADO y hace
fail-fast mientras la dependencia se recupera.

Politica:
- Abre si hay >= UMBRAL_CONSECUTIVOS fallos seguidos, o si el error rate
  >= 50% en una ventana de 30s (minimo 4 muestras).
- En OPEN: fail-fast (no se llama a la dependencia) durante el cooldown (15s).
- Al vencer el cooldown pasa a HALF_OPEN: deja pasar UNA sonda controlada;
  exito -> CLOSED, fallo -> OPEN de nuevo.

Corre en el event loop de asyncio (un solo hilo): no requiere locks.
"""
import time


class CircuitBreaker:
    def __init__(self, nombre, umbral_consecutivos=3, ventana_seg=30.0,
                 min_muestras=4, umbral_error_rate=0.5, cooldown_seg=15.0):
        self.nombre = nombre
        self.umbral_consecutivos = umbral_consecutivos
        self.ventana_seg = ventana_seg
        self.min_muestras = min_muestras
        self.umbral_error_rate = umbral_error_rate
        self.cooldown_seg = cooldown_seg

        self.estado = "CLOSED"
        self.fallos_consecutivos = 0
        self.resultados = []          # [(timestamp, ok)]
        self.abierto_hasta = 0.0
        self.sonda_en_vuelo = False
        self.aperturas = 0            # veces que el circuito abrio (metrica)

    def permite(self) -> bool:
        """True si la llamada puede salir; False = fail-fast (circuito abierto)."""
        if self.estado == "OPEN":
            if time.monotonic() >= self.abierto_hasta:
                self.estado = "HALF_OPEN"
                self.sonda_en_vuelo = False
            else:
                return False
        if self.estado == "HALF_OPEN":
            if self.sonda_en_vuelo:
                return False  # ya hay una sonda probando la dependencia
            self.sonda_en_vuelo = True
        return True

    def registrar(self, ok: bool):
        """Registra el resultado de una llamada y actualiza el estado."""
        ahora = time.monotonic()
        self.resultados = [(t, o) for (t, o) in self.resultados if ahora - t <= self.ventana_seg]
        self.resultados.append((ahora, ok))

        if ok:
            self.fallos_consecutivos = 0
            if self.estado == "HALF_OPEN":
                self.estado = "CLOSED"   # la sonda salio bien: recuperado
                self.sonda_en_vuelo = False
            return

        self.fallos_consecutivos += 1
        if self.estado == "HALF_OPEN":
            self._abrir()
            return

        total = len(self.resultados)
        errores = sum(1 for _, o in self.resultados if not o)
        if (self.fallos_consecutivos >= self.umbral_consecutivos
                or (total >= self.min_muestras and errores / total >= self.umbral_error_rate)):
            self._abrir()

    def _abrir(self):
        self.estado = "OPEN"
        self.abierto_hasta = time.monotonic() + self.cooldown_seg
        self.sonda_en_vuelo = False
        self.aperturas += 1

    # Valor numerico del estado para exponerlo como metrica Prometheus.
    def estado_numerico(self) -> int:
        return {"CLOSED": 0, "HALF_OPEN": 1, "OPEN": 2}[self.estado]

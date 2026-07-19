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

Ahora con soporte de Redis para estado compartido entre workers distribuidos
y fallback automático en memoria si Redis no está disponible.
"""
import time
import os
import json

try:
    import redis
    # Usamos la URL de Redis provista por entorno o la por defecto.
    # decode_responses=True decodifica automáticamente los bytes de Redis a strings de Python
    _client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True, socket_timeout=2.0)
except Exception:
    _client = None


class CircuitBreaker:
    def __init__(self, nombre, umbral_consecutivos=3, ventana_seg=30.0,
                 min_muestras=4, umbral_error_rate=0.5, cooldown_seg=15.0):
        self.nombre = nombre
        self.umbral_consecutivos = umbral_consecutivos
        self.ventana_seg = ventana_seg
        self.min_muestras = min_muestras
        self.umbral_error_rate = umbral_error_rate
        self.cooldown_seg = cooldown_seg

        # Valores de fallback local (en memoria) si Redis falla o no está disponible
        self._local_estado = "CLOSED"
        self._local_fallos_consecutivos = 0
        self._local_resultados = []          # [(timestamp, ok)]
        self._local_abierto_hasta = 0.0
        self._local_sonda_en_vuelo = False
        self._local_aperturas = 0

        # Al inicializar (o reiniciar el worker/contenedor), limpiamos cualquier
        # estado sucio de la sonda en vuelo en Redis para evitar quedar atrapados en HALF_OPEN.
        try:
            self.sonda_en_vuelo = False
        except Exception:
            pass

    @property
    def redis_key(self):
        return f"cb:{self.nombre}"

    def _hget(self, field: str, default):
        if _client:
            try:
                val = _client.hget(self.redis_key, field)
                if val is not None:
                    return val
            except Exception:
                pass
        return getattr(self, f"_local_{field}")

    def _hset(self, field: str, val):
        if _client:
            try:
                _client.hset(self.redis_key, field, str(val))
                return
            except Exception:
                pass
        setattr(self, f"_local_{field}", val)

    @property
    def estado(self) -> str:
        return self._hget("estado", "CLOSED")

    @estado.setter
    def estado(self, val: str):
        self._hset("estado", val)

    @property
    def fallos_consecutivos(self) -> int:
        return int(self._hget("fallos_consecutivos", 0))

    @fallos_consecutivos.setter
    def fallos_consecutivos(self, val: int):
        self._hset("fallos_consecutivos", val)

    @property
    def abierto_hasta(self) -> float:
        return float(self._hget("abierto_hasta", 0.0))

    @abierto_hasta.setter
    def abierto_hasta(self, val: float):
        self._hset("abierto_hasta", val)

    @property
    def sonda_en_vuelo(self) -> bool:
        val = self._hget("sonda_en_vuelo", False)
        # En Redis se guarda como "True"/"False" o "1"/"0"
        return str(val) in ("True", "1")

    @sonda_en_vuelo.setter
    def sonda_en_vuelo(self, val: bool):
        self._hset("sonda_en_vuelo", "1" if val else "0")

    @property
    def aperturas(self) -> int:
        return int(self._hget("aperturas", 0))

    @aperturas.setter
    def aperturas(self, val: int):
        self._hset("aperturas", val)

    @property
    def resultados(self) -> list:
        if _client:
            try:
                val = _client.hget(self.redis_key, "resultados")
                if val is not None:
                    return json.loads(val)
            except Exception:
                pass
        return self._local_resultados

    @resultados.setter
    def resultados(self, val: list):
        if _client:
            try:
                _client.hset(self.redis_key, "resultados", json.dumps(val))
                return
            except Exception:
                pass
        self._local_resultados = val

    def permite(self) -> bool:
        """True si la llamada puede salir; False = fail-fast (circuito abierto)."""
        ahora = time.time()  # Absoluto en vez de monotonic para consistencia entre procesos
        if self.estado == "OPEN":
            if ahora >= self.abierto_hasta:
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
        ahora = time.time()
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
        self.abierto_hasta = time.time() + self.cooldown_seg
        self.sonda_en_vuelo = False
        self.aperturas += 1

    # Valor numerico del estado para exponerlo como metrica Prometheus.
    def estado_numerico(self) -> int:
        return {"CLOSED": 0, "HALF_OPEN": 1, "OPEN": 2}[self.estado]

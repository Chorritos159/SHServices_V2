"""
pruebas_resiliencia.py — Prueba automatizada del Circuit Breaker vía Toxiproxy.

Valida, de punta a punta y sin dependencias externas (solo stdlib), que el API
Gateway protege al sistema cuando el ticket-service (detrás de Toxiproxy) falla:

  - Servicio sano            -> 200
  - Latencia 8s (> 5s)       -> 504 Gateway Timeout   (Circuit Breaker por timeout)
  - Sin toxina               -> 200 (recuperado)
  - Servicio caído           -> 503 Service Unavailable (Circuit Breaker por conexión)
  - Servicio restaurado      -> 200

Requisitos: el stack levantado (docker compose up -d). Se ejecuta desde el host:
    python pruebas_resiliencia.py
"""
import json
import sys
import time
import urllib.request
import urllib.error

AUTH = "http://localhost:8003/api/v1/auth/login"
GATEWAY = "http://localhost:8000/api/v1/tickets/tickets/pendientes"
METRICS = "http://localhost:8000/metrics"
TOXI = "http://localhost:8474/proxies/ticket_proxy"

resultados = []


def http(url, method="GET", data=None, headers=None, timeout=20):
    cuerpo = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=cuerpo, method=method, headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return None, str(e)


def login():
    status, body = http(AUTH, "POST", {"usuario": "admin", "password": "admin123"})
    if status != 200:
        print(f"[ERROR] No se pudo hacer login ({status}). ¿Está el stack arriba?")
        sys.exit(2)
    return json.loads(body)["access_token"]


def probar(token):
    return http(GATEWAY, "GET", headers={"Authorization": f"Bearer {token}"})[0]


def add_latencia(ms):
    http(f"{TOXI}/toxics", "POST", {"name": "lat_test", "type": "latency", "attributes": {"latency": ms}})


def quitar_latencia():
    http(f"{TOXI}/toxics/lat_test", "DELETE")


def set_enabled(valor):
    http(TOXI, "POST", {"enabled": valor})


def check(nombre, esperado, obtenido):
    ok = obtenido == esperado
    resultados.append(ok)
    icono = "PASS" if ok else "FAIL"
    print(f"  [{icono}] {nombre:<45} esperado={esperado}  obtenido={obtenido}")


def circuit_breaker_total():
    _, body = http(METRICS, "GET")
    total = 0.0
    for linea in (body or "").splitlines():
        if linea.startswith("gateway_circuit_breaker_total{"):
            try:
                total += float(linea.rsplit(" ", 1)[1])
            except ValueError:
                pass
    return total


def main():
    print("== Prueba de Resiliencia: Circuit Breaker vía Toxiproxy ==\n")
    token = login()
    cb_inicio = circuit_breaker_total()

    # Estado limpio de Toxiproxy
    quitar_latencia()
    set_enabled(True)
    time.sleep(1)

    check("Baseline (servicio sano)", 200, probar(token))

    print("  ...inyectando latencia de 8s en ticket_proxy")
    add_latencia(8000)
    time.sleep(1)
    check("Latencia 8s -> Circuit Breaker (504)", 504, probar(token))

    print("  ...quitando la latencia")
    quitar_latencia()
    time.sleep(1)
    check("Recuperado sin toxina (200)", 200, probar(token))

    print("  ...deshabilitando el proxy (servicio caido)")
    set_enabled(False)
    time.sleep(1)
    check("Servicio caido -> Circuit Breaker (503)", 503, probar(token))

    print("  ...re-habilitando el proxy")
    set_enabled(True)
    time.sleep(1)
    check("Servicio restaurado (200)", 200, probar(token))

    cb_fin = circuit_breaker_total()
    print(f"\n  Cortes de Circuit Breaker registrados en esta corrida: {int(cb_fin - cb_inicio)}")
    print(f"\nResultado: {sum(resultados)}/{len(resultados)} pruebas OK")
    sys.exit(0 if all(resultados) else 1)


if __name__ == "__main__":
    main()

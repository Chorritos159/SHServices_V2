#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""RESILIENCIA EN VIVO — 8 demos cortas, para enseñar en la sustentación.

Cada demo dura menos de un minuto, dice EN CONSOLA qué servicio está tocando y
en qué panel de Grafana se ve, e imprime los logs REALES del Gateway que lo
prueban. Está pensada para proyectarla mientras se explica.

  1. SONDA ACTIVA — se corta 'almacen', el circuito se abre, se restaura la
     conectividad y NADIE toca el circuito: la sonda lo cierra sola.
  2. TIMEOUT + RETRY — se mete latencia con una toxina de Toxiproxy; el Gateway
     agota su timeout y reintenta.
  3. BULKHEAD — se lanzan más llamadas concurrentes que huecos tiene el
     mamparo, y las que sobran se rechazan sin tumbar al servicio.
  4. AUTO-HEALING DE PROCESO — se mata un worker de uvicorn y el maestro lo
     respawnea; el servicio NUNCA deja de responder.
  5. IDEMPOTENCIA — se manda el MISMO alta 3 veces y solo queda 1 fila en la
     base de datos. Trae un bloque comentado para ver el contraste SIN clave.
  6. BUFFERING — se para ticket-service, el tecnico diagnostica igual, y al
     volver el servicio procesa el backlog y mueve el ticket SOLO.
  7. QUEUE DEPTH y CONSUMER LAG — una rafaga satura a los consumidores; la cola
     sube y drena sola. Muestra donde mirar cada metrica en Grafana.
  8. CIRCUIT BREAKER — trafico real contra un servicio caido: multiples 503,
     apertura del circuito, fail-fast y cierre automatico por la sonda.

Uso:
    python pruebas/13_resiliencia_en_vivo.py            # las seis
    python pruebas/13_resiliencia_en_vivo.py --demo 1   # solo una
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, "reconfigure"):
        _f.reconfigure(encoding="utf-8", errors="replace")

GW = "http://localhost:8000"
TOXI = "http://localhost:8474"
PROXY = {"almacen": "almacen_proxy", "tickets": "ticket_proxy",
         "facturas": "factura_proxy", "diagnosticos": "diagnostico_proxy"}
ESTADOS = {0: "CLOSED", 1: "HALF_OPEN", 2: "OPEN"}


def pedir(url, metodo="GET", cuerpo=None, token=None, timeout=20, extra=None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cab = {"Content-Type": "application/json"}
    if token:
        cab["Authorization"] = f"Bearer {token}"
    if extra:
        cab.update(extra)
    pet = urllib.request.Request(url, data=datos, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(pet, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def login():
    _, cuerpo = pedir(f"{GW}/api/v1/auth/login", "POST",
                      {"usuario": "admin", "password": "admin123"})
    try:
        return json.loads(cuerpo).get("access_token", "")
    except Exception:
        return ""


def proxy(nombre, habilitado):
    pedir(f"{TOXI}/proxies/{nombre}", "POST", {"enabled": habilitado})


def toxina(nombre_proxy, latencia_ms):
    """Añade latencia en el proxy. Devuelve el nombre para poder quitarla."""
    pedir(f"{TOXI}/proxies/{nombre_proxy}/toxics", "POST",
          {"name": "lentitud", "type": "latency", "stream": "downstream",
           "attributes": {"latency": latencia_ms, "jitter": 0}})
    return "lentitud"


def quitar_toxina(nombre_proxy, nombre="lentitud"):
    pedir(f"{TOXI}/proxies/{nombre_proxy}/toxics/{nombre}", "DELETE")


def circuito(servicio):
    _, texto = pedir(f"{GW}/metrics")
    for linea in texto.splitlines():
        if linea.startswith(f'gateway_circuit_state{{service="{servicio}"}}'):
            return ESTADOS.get(int(float(linea.rsplit(" ", 1)[-1])), "?")
    return "?"


def logs(patron, segundos=90, cuantos=6):
    """Los logs REALES del Gateway que prueban lo que se acaba de ver."""
    r = subprocess.run(["docker", "logs", "api-gateway", "--since", f"{segundos}s"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    salida = []
    for linea in (r.stdout + r.stderr).splitlines():
        if patron.lower() in linea.lower():
            try:
                d = json.loads(linea)
                salida.append(f"    [{d.get('level','')}] {d.get('message','')[:130]}")
            except Exception:
                salida.append(f"    {linea[:130]}")
    if not salida:
        print("    (sin logs que casen; mira `docker logs api-gateway`)")
    for l in salida[-cuantos:]:
        print(l)


def _sql(consulta: str) -> str:
    """Consulta directa a PostgreSQL: la evidencia que no se puede discutir."""
    r = subprocess.run(
        ["docker", "exec", "postgres-db", "psql", "-U", "admin",
         "-d", "shservices_db", "-t", "-c", consulta],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip()


def _cola(nombre: str) -> str:
    """Mensajes pendientes en una cola, por la API HTTP de RabbitMQ."""
    import base64
    pet = urllib.request.Request(f"http://localhost:15672/api/queues/%2F/{nombre}")
    pet.add_header("Authorization", "Basic " + base64.b64encode(b"guest:guest").decode())
    try:
        return str(json.loads(urllib.request.urlopen(pet, timeout=6).read()).get("messages", "?"))
    except Exception:
        return "?"


def _colas():
    """Mensajes pendientes en TODAS las colas, por la API HTTP de RabbitMQ."""
    import base64
    pet = urllib.request.Request("http://localhost:15672/api/queues")
    pet.add_header("Authorization", "Basic " + base64.b64encode(b"guest:guest").decode())
    try:
        colas = json.loads(urllib.request.urlopen(pet, timeout=6).read())
    except Exception:
        return 0, "(no se pudo leer RabbitMQ)"
    total, detalle = 0, []
    for c in colas:
        n = c.get("messages", 0) or 0
        total += n
        detalle.append(f"{c.get('name')}={n}")
    return total, ", ".join(detalle)


def _estado_ticket(id_ticket: str) -> str:
    return _sql(f"SELECT estado FROM tickets WHERE id='{id_ticket}'")


def _logs_de(contenedor: str, patron: str, segundos=120, cuantos=4):
    """Como `logs()`, pero de cualquier contenedor y no solo del Gateway."""
    r = subprocess.run(["docker", "logs", contenedor, "--since", f"{segundos}s"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    salida = []
    for linea in (r.stdout + r.stderr).splitlines():
        if patron.lower() in linea.lower():
            try:
                d = json.loads(linea)
                salida.append(f"    [{d.get('level','')}] {d.get('message','')[:130]}")
            except Exception:
                salida.append(f"    {linea[:130]}")
    if not salida:
        print(f"    (sin logs que casen; mira `docker logs {contenedor}`)")
    for l in salida[-cuantos:]:
        print(l)


def titulo(n, texto, panel):
    print("\n" + "=" * 72)
    print(f" DEMO {n}: {texto}")
    print("=" * 72)
    print(f" En Grafana: {panel}")


# ----------------------------------------------------------------------
def demo1(token):
    titulo(1, "SONDA ACTIVA — el circuito se cierra SOLO",
           "panel 'Estado del circuito por servicio'")
    print(" Servicio comprometido: ALMACEN (se corta su proxy en Toxiproxy)\n")

    print(f"  estado inicial ............ {circuito('almacen')}")
    print("  cortando la conectividad de 'almacen'...")
    proxy(PROXY["almacen"], False)

    for _ in range(8):
        pedir(f"{GW}/api/v1/almacen/almacen/inventario", token=token, timeout=8)
    time.sleep(3)
    print(f"  tras unos fallos .......... {circuito('almacen')}  <-- fail-fast")

    codigo, _ = pedir(f"{GW}/api/v1/almacen/almacen/inventario", token=token, timeout=8)
    print(f"  una peticion mas .......... HTTP {codigo}  (503 con contrato, NO un 500)")
    print(f"  'tickets' mientras tanto .. {circuito('tickets')}  <-- sin cascada")

    print("\n  restauro la conectividad y NO toco el circuito.")
    print("  A partir de aqui nadie interviene: la sonda va sola cada 5s.")
    proxy(PROXY["almacen"], True)

    t0 = time.monotonic()
    while time.monotonic() - t0 < 90:
        if circuito("almacen") == "CLOSED":
            print(f"\n  >>> el circuito se CERRO SOLO en {time.monotonic()-t0:.0f}s <<<")
            break
        time.sleep(2)
    else:
        print("\n  el circuito NO se cerro en 90s — revisar la sonda")

    print("\n  Los logs del Gateway que lo prueban:")
    logs("circuit_breaker", 180)


def demo2(token):
    titulo(2, "TIMEOUT + RETRY — la dependencia se vuelve LENTA",
           "paneles 'Timeouts (/s)' y 'Reintentos (/s)'")
    print(" Servicio comprometido: FACTURAS (latencia de 9s inyectada)\n")

    print("  metiendo 9s de latencia en el proxy de 'facturas'...")
    toxina(PROXY["facturas"], 9000)
    time.sleep(1)

    t0 = time.monotonic()
    codigo, _ = pedir(f"{GW}/api/v1/facturas/facturas/", token=token, timeout=40)
    print(f"  respuesta ................. HTTP {codigo} en {time.monotonic()-t0:.1f}s")
    print("  (el Gateway corta por timeout y reintenta con backoff en vez de")
    print("   quedarse colgado esperando indefinidamente)")

    quitar_toxina(PROXY["facturas"])
    print("  latencia retirada.")
    print("\n  Los logs del Gateway:")
    logs("timeout", 90)
    logs("reintent", 90, 3)


def demo3(token):
    titulo(3, "BULKHEAD — mas llamadas concurrentes que huecos",
           "paneles 'Bulkhead: llamadas en vuelo' y 'rechazos (/s) por razon'")
    print(" Servicio comprometido: DIAGNOSTICOS (lento + 40 llamadas a la vez)\n")

    toxina(PROXY["diagnosticos"], 3000)
    time.sleep(1)
    print("  lanzando 40 peticiones simultaneas...")

    def una(_):
        c, _cuerpo = pedir(f"{GW}/api/v1/diagnosticos/diagnosticos/", token=token, timeout=30)
        return c

    with ThreadPoolExecutor(max_workers=40) as ex:
        codigos = list(ex.map(una, range(40)))

    quitar_toxina(PROXY["diagnosticos"])
    resumen = {}
    for c in codigos:
        resumen[c] = resumen.get(c, 0) + 1
    print(f"  respuestas ................ {resumen}")
    print("  Las 503 son el mamparo rechazando lo que no cabe: prefiere decir")
    print("  'ahora no' a aceptarlo todo y tumbar el servicio (y con el, a los")
    print("  demas que comparten el Gateway).")
    print("\n  Los logs del Gateway:")
    logs("bulkhead", 90)


def demo4(token):
    print("\n" + "=" * 72)
    print(" DEMO 4: AUTO-HEALING DE PROCESO — muere un worker y vuelve solo")
    print("=" * 72)
    print(" Servicio comprometido: ALMACEN (se mata 1 de sus 4 workers)\n")
    print("  Cada servicio corre con `uvicorn --workers 4`: un proceso maestro")
    print("  supervisa a 4 workers. Aqui se mata de verdad (os._exit) el worker")
    print("  que atiende la peticion, y se observa que el maestro lo respawnea")
    print("  en ~1s mientras los otros 3 siguen sirviendo: auto-healing a nivel")
    print("  de proceso, sin que el servicio deje de responder.\n")

    codigo, _ = pedir("http://localhost:8002/_chaos/crash", "POST", timeout=8)
    print(f"  crash provocado ........... HTTP {codigo}")

    caidas = 0
    for i in range(12):
        c, _cuerpo = pedir("http://localhost:8002/health", timeout=5)
        if c != 200:
            caidas += 1
        time.sleep(0.5)
    print(f"  12 sondeos en 6s .......... {12 - caidas} OK, {caidas} fallidos")
    if caidas == 0:
        print("  >>> el servicio NUNCA dejo de responder: el maestro respawneo <<<")
        print("  >>> el worker muerto sin que se notara desde fuera.          <<<")
    else:
        print("  (hubo un hueco: el worker muerto atendia parte del trafico)")

    print("\n  El log del propio servicio:")
    r = subprocess.run(["docker", "logs", "almacen-service", "--since", "60s"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    for linea in (r.stdout + r.stderr).splitlines():
        if "CHAOS" in linea or "Started server process" in linea:
            print(f"    {linea[:130]}")


def demo5(token):
    titulo(5, "IDEMPOTENCIA — mandar DOS VECES lo mismo no duplica",
           "no aplica: la evidencia esta en la BASE DE DATOS (se consulta abajo)")
    print(" Servicio comprometido: ninguno. Se simula al usuario dando doble clic.")
    print("")

    clave = f"demo5-{int(time.time())}"
    nombre = f"Demo Idempotencia {int(time.time())}"
    print(f"  Idempotency-Key: {clave}")
    print("  mandando el MISMO alta 3 veces seguidas...")
    for i in (1, 2, 3):
        cod, _c = pedir(f"{GW}/api/v1/almacen/almacen/productos", "POST", {
            "nombre": nombre, "categoria": "REPUESTO", "sede": "PIURA",
            "stock_inicial": 5, "precio_unitario": 20.0,
        }, token=token, timeout=20, extra={"Idempotency-Key": clave})
        print(f"    envio {i} -> HTTP {cod}")

    filas = _sql(f"SELECT COUNT(*) FROM inventario WHERE nombre='{nombre}'")
    print("")
    print(f"  Filas en la BASE DE DATOS: {filas}")
    if filas == "1":
        print("  >>> 3 envios, UNA sola fila: la clave hizo su trabajo <<<")
    else:
        print(f"  OJO: se esperaba 1 fila y hay {filas}")

    # ------------------------------------------------------------------
    # DESCOMENTA ESTE BLOQUE para ver el CONTRASTE: los mismos 3 envios
    # pero SIN Idempotency-Key. Salen 3 productos distintos, que es
    # exactamente el bug que la idempotencia evita.
    # ------------------------------------------------------------------
    # sin_clave = f"Demo SIN idempotencia {int(time.time())}"
    # print("")
    # print("  [CONTRASTE] los mismos 3 envios, pero SIN Idempotency-Key:")
    # for i in (1, 2, 3):
    #     cod, _c = pedir(f"{GW}/api/v1/almacen/almacen/productos", "POST", {
    #         "nombre": sin_clave, "categoria": "REPUESTO", "sede": "PIURA",
    #         "stock_inicial": 5, "precio_unitario": 20.0,
    #     }, token=token, timeout=20)
    #     print(f"    envio {i} -> HTTP {cod}")
    # print(f"  Filas en la BD: "
    #       f"{_sql(f\"SELECT COUNT(*) FROM inventario WHERE nombre='{sin_clave}'\")}")
    # print("  >>> 3 filas: sin la clave, cada clic crea un producto nuevo <<<")

    print("")
    print("  Los logs del almacen:")
    _logs_de("almacen-service", "duplicado", 120, 4)


def demo6(token):
    titulo(6, "BUFFERING — con el servicio caido, el trabajo NO se pierde",
           "paneles 'Queue depth' y 'Consumer lag' (seccion RabbitMQ)")
    print(" Servicio comprometido: TICKETS (se corta su proxy en Toxiproxy)")
    print("")
    print("  El tecnico registra un diagnostico mientras TICKETS esta caido.")
    print("  El diagnostico se guarda igual y el evento espera en la cola;")
    print("  cuando tickets vuelve procesa el backlog y mueve el ticket SOLO.")
    print("")

    cod, cuerpo = pedir(f"{GW}/api/v1/tickets/tickets/", "POST", {
        "datosCliente": "Cliente Demo Buffer", "documento_cliente": "70000006",
        "telefono_cliente": "999000666", "tipoOperacion": "SOPORTE",
        "prioridad": "MEDIA", "equipo": "PC", "numero_serie": "SN-DEMO6",
        "caracteristicas_falla": "No arranca",
    }, token=token, timeout=20, extra={"Idempotency-Key": f"d6-{int(time.time())}"})
    try:
        ticket = json.loads(cuerpo).get("idTicket")
    except Exception:
        ticket = None
    if not ticket:
        print(f"  no se pudo crear el ticket de la demo (HTTP {cod}); se aborta.")
        return
    print(f"  ticket creado ............. {ticket}")

    # `docker stop` y NO Toxiproxy, a proposito: el proxy solo corta la ruta
    # HTTP del Gateway, pero el CONSUMIDOR de RabbitMQ de ticket-service habla
    # directo con el broker y seguiria trabajando. Con el proxy cortado la demo
    # marcaba "backlog procesado en 0s" — el ticket ya estaba actualizado y no
    # se demostraba nada. Hay que parar el contenedor para que el consumidor
    # deje de consumir y los eventos se acumulen de verdad.
    print("  parando ticket-service (contenedor, no solo el proxy)...")
    subprocess.run(["docker", "stop", "ticket-service"], capture_output=True)
    time.sleep(2)

    cod, _c = pedir(f"{GW}/api/v1/diagnosticos/diagnosticos/", "POST", {
        "idTicket": ticket, "fallaDetectada": "Fuente danada",
        "mano_obra": 50, "precio_reparacion": 150,
        "repuestos": [{"codigo_repuesto": "REP-001", "cantidad": 1}],
    }, token=token, timeout=30)
    print(f"  diagnostico CON tickets caido -> HTTP {cod}   (201 = se guardo igual)")
    print(f"  estado del ticket ahora ... {_estado_ticket(ticket)}")

    print("")
    print("  cuantos eventos esperan en la cola:")
    print(f"    tickets_estado_queue = {_cola('tickets_estado_queue')} mensaje(s)")
    print("")
    print("  levanto ticket-service y NO toco nada mas.")
    subprocess.run(["docker", "start", "ticket-service"], capture_output=True)
    t0 = time.monotonic()
    while time.monotonic() - t0 < 90:
        if _estado_ticket(ticket) == "DIAGNOSTICADO":
            print("")
            print(f"  >>> el backlog se proceso SOLO en {time.monotonic()-t0:.0f}s: "
                  "el ticket paso a DIAGNOSTICADO <<<")
            break
        time.sleep(2)
    else:
        print(f"  el ticket sigue en {_estado_ticket(ticket)} tras 60s")

    print("")
    print("  Los logs del consumidor de tickets:")
    _logs_de("ticket-service", "consumir_diagnostico", 180, 3)


def demo7(token):
    titulo(7, "QUEUE DEPTH y CONSUMER LAG — la cola sube y drena sola",
           "seccion RabbitMQ: 'Queue depth', 'Consumer lag' y 'Consumidores activos'")
    print(" Servicio comprometido: ninguno. Se satura a los CONSUMIDORES.")
    print("")
    print("  Cada alta de producto publica un evento que auditoria y")
    print("  notificaciones deben procesar. Si se publica mas rapido de lo que")
    print("  consumen, la cola CRECE: eso es el desacoplamiento absorbiendo el")
    print("  exceso en vez de rechazar trabajo.")
    print("")

    antes, detalle = _colas()
    print(f"  cola al empezar ........... {antes} mensaje(s)  ({detalle})")
    print("  lanzando 400 altas en rafaga (40 a la vez)...")

    def alta(i):
        cod, _c = pedir(f"{GW}/api/v1/almacen/almacen/productos", "POST", {
            "nombre": f"CARGA-demo7 {int(time.time())}-{i}", "categoria": "REPUESTO",
            "sede": "PIURA", "stock_inicial": 3, "precio_unitario": 12.0,
        }, token=token, timeout=30)
        return cod

    with ThreadPoolExecutor(max_workers=40) as ex:
        list(ex.map(alta, range(400)))

    pico, detalle = _colas()
    print(f"  cola justo despues ........ {pico} mensaje(s)  ({detalle})")
    if pico > antes:
        print("  >>> LA COLA SUBIO: es el BUFFERING absorbiendo la rafaga <<<")
    else:
        print("  (los consumidores fueron mas rapidos que la rafaga; mira el")
        print("   panel 'Consumer lag', que es mas sensible que 'Queue depth')")

    print("")
    print("  Ahora NADIE interviene: se observa como DRENA sola.")
    for _ in range(12):
        time.sleep(5)
        actual, _d = _colas()
        print(f"    quedan {actual} mensaje(s)")
        if actual == 0:
            break

    print("")
    print("  Lo que hay que mirar en Grafana:")
    print("    - 'Queue depth': la curva sube y vuelve a cero. Eso es sano.")
    print("    - 'Consumer lag': mensajes entregados pero SIN confirmar. Un lag")
    print("      alto con la cola vacia significa consumidor atascado, no ocioso.")
    print("    - 'Consumidores activos': si marca 0 en alguna cola, el consumidor")
    print("      murio; ahi la cola crece y NO baja.")


def demo8(token):
    titulo(8, "CIRCUIT BREAKER — multiples 503, circuito abierto y fallback",
           "panel 'Estado del circuito por servicio' y 'Aperturas de circuito'")
    print(" Servicio comprometido: ALMACEN (se corta su proxy en Toxiproxy)")
    print("")
    print("  Se manda trafico REAL contra un servicio caido. El breaker necesita")
    print("  ver fallos para abrir: si nadie llama al servicio caido, su circuito")
    print("  se queda CLOSED, y eso es correcto, no un fallo.")
    print("")

    print(f"  estado inicial ............ {circuito('almacen')}")
    proxy(PROXY["almacen"], False)
    print("  'almacen' sin conectividad. Mandando 8 peticiones...")

    codigos = []
    for i in range(8):
        cod, _c = pedir(f"{GW}/api/v1/almacen/almacen/productos",
                        token=token, timeout=12)
        codigos.append(cod)
        print(f"    peticion {i+1} -> HTTP {cod}  (circuito: {circuito('almacen')})")

    resumen = {}
    for c in codigos:
        resumen[c] = resumen.get(c, 0) + 1
    print("")
    print(f"  respuestas ................ {resumen}")
    print(f"  estado del circuito ....... {circuito('almacen')}")
    print(f"  'tickets' mientras tanto .. {circuito('tickets')}  <-- sin cascada")
    print("")
    print("  Los primeros fallos tardan (se agota el timeout); a partir de la")
    print("  apertura las respuestas son INMEDIATAS: eso es el fail-fast, que")
    print("  deja de gastar timeout contra algo que ya se sabe caido.")

    print("")
    print("  restaurando la conectividad; el circuito se cierra SOLO.")
    proxy(PROXY["almacen"], True)
    t0 = time.monotonic()
    while time.monotonic() - t0 < 90:
        if circuito("almacen") == "CLOSED":
            print(f"  >>> circuito CERRADO SOLO en {time.monotonic()-t0:.0f}s "
                  "(sonda activa, ADR-0014) <<<")
            break
        time.sleep(2)

    print("")
    print("  Los logs del Gateway (una linea por TRANSICION, no por peticion):")
    logs("circuit_breaker", 200, 6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", type=int, choices=[1, 2, 3, 4, 5, 6, 7, 8],
                    help="Correr solo una (por defecto: las cuatro)")
    args = ap.parse_args()

    token = login()
    if not token:
        print("No se pudo iniciar sesion. Esta todo levantado? (docker compose ps)")
        sys.exit(1)

    demos = {1: demo1, 2: demo2, 3: demo3, 4: demo4,
             5: demo5, 6: demo6, 7: demo7, 8: demo8}
    elegidas = [args.demo] if args.demo else [1, 2, 3, 4, 5, 6, 7, 8]
    try:
        for n in elegidas:
            demos[n](token)
    finally:
        # Pase lo que pase: ni un proxy cortado ni una toxina viva.
        for nombre in PROXY.values():
            quitar_toxina(nombre)
            proxy(nombre, True)

    print("\n" + "=" * 72)
    print(" Todo restaurado. Para ver los logs completos de cualquier servicio:")
    print("   docker logs api-gateway --since 10m")
    print("   docker logs almacen-service --since 10m")
    print(" Y en Grafana (http://localhost:3000) los paneles citados arriba.")
    print("=" * 72)


if __name__ == "__main__":
    main()

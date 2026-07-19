/**
 * Carga mixta con k6 — SHServices V2
 *
 * POR QUE k6 Y NO EL GENERADOR DE PYTHON
 * `pruebas/lib/carga_nodos.py` topa en ~105 peticiones/segundo por proceso: es
 * un solo proceso con GIL donde enviar, deserializar y contabilizar compiten
 * entre si. Se comprobo lanzando generadores en paralelo (1 -> 105 rps,
 * 2 -> 171, 4 -> 257): el total escalaba con el numero de procesos, o sea que
 * el techo medido era del CLIENTE y no del sistema.
 *
 * k6 esta escrito en Go: sus usuarios virtuales son goroutines, sin GIL, y un
 * solo proceso sostiene miles de peticiones concurrentes. Ademas corre DENTRO
 * de la red Docker, asi que habla con `api-gateway:80` directamente y se salta
 * la traduccion de red de Windows, que anade latencia por peticion.
 *
 * MEZCLA (la misma que las pruebas de Python, para poder comparar)
 *   ~70% lecturas repartidas entre los 4 servicios con endpoint de consulta
 *   ~30% escrituras reales: crear ticket y registrar producto
 *
 * Las escrituras importan: son las que abren transaccion, bloquean filas y
 * publican eventos a RabbitMQ. Una prueba de solo lecturas mide otra cosa.
 */
import http from "k6/http";
import { check } from "k6";
import { Counter, Trend } from "k6/metrics";

const GATEWAY = __ENV.GATEWAY || "http://api-gateway:80";
const TOTAL = parseInt(__ENV.TOTAL || "100000", 10);
const VUS = parseInt(__ENV.VUS || "50", 10);
const SEDE = __ENV.SEDE || "PIURA";

// Metricas propias: k6 agrupa por defecto y aqui interesa el desglose.
const lecturas = new Counter("op_lecturas");
const escrituras = new Counter("op_escrituras");
const errores_negocio = new Counter("http_409");
const errores_500 = new Counter("http_500");
const degradados = new Counter("http_503_504_429");
const errores_reales = new Counter("errores_reales");   // solo 5xx
const encolados = new Counter("http_202");
const latencia_lectura = new Trend("latencia_lectura_ms");
const latencia_escritura = new Trend("latencia_escritura_ms");

export const options = {
  scenarios: {
    carga: {
      executor: "shared-iterations",   // reparte TOTAL iteraciones entre los VUs
      vus: VUS,
      iterations: TOTAL,
      maxDuration: __ENV.MAX_DURACION || "30m",
    },
  },
  // Umbrales: si se incumplen, k6 termina con codigo != 0 y la prueba FALLA.
  thresholds: {
    // Un 500 es el sistema perdiendo el control: cero tolerancia.
    "http_500": ["count==0"],
    // OJO: `http_req_failed` cuenta como fallo TODO status >= 400, incluidos
    // los 409 de conflicto de negocio (ticket ya diagnosticado, factura ya
    // emitida), que bajo carga mixta con datos aleatorios son inevitables y
    // CORRECTOS. Por eso el umbral mira `errores_reales`, que solo cuenta
    // 5xx: lo unico que de verdad delata al sistema.
    "errores_reales": ["count==0"],
  },
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
};

/** Login una sola vez por VU; el token se reutiliza en toda la iteracion. */
export function setup() {
  const r = http.post(
    `${GATEWAY}/api/v1/auth/login`,
    JSON.stringify({ usuario: "admin", password: "admin123" }),
    { headers: { "Content-Type": "application/json" }, timeout: "30s" },
  );
  if (r.status !== 200) {
    throw new Error(`El login fallo con HTTP ${r.status}. ¿Esta el sistema levantado?`);
  }
  return { token: r.json("access_token") };
}

const RUTAS_LECTURA = [
  "/api/v1/tickets/tickets/?limite=50",
  "/api/v1/almacen/almacen/productos?limite=50",
  "/api/v1/auditoria/auditoria/eventos",
  "/api/v1/notificaciones/notificaciones/mis-alertas",
  // Facturas y diagnosticos TIENEN que estar aqui. Sin trafico hacia ellos su
  // circuito no puede abrirse nunca: la prueba de caos tumbaba 'facturas' y el
  // panel lo mostraba CLOSED todo el rato, no porque aguantara, sino porque
  // nadie lo estaba llamando. Se vio comparando con almacen y tickets, que si
  // abrian.
  "/api/v1/facturas/garantias/",
  "/api/v1/diagnosticos/asignaciones/",
];

/** Clasifica la respuesta en las metricas que alimentan la tabla. */
function clasificar(res) {
  if (res.status >= 500 && res.status !== 503 && res.status !== 504) {
    errores_reales.add(1);
  }
  if (res.status === 500) errores_500.add(1);
  else if (res.status === 409) errores_negocio.add(1);
  else if (res.status === 202) encolados.add(1);
  else if ([503, 504, 429].includes(res.status)) degradados.add(1);
}

export default function (datos) {
  const cabeceras = {
    headers: {
      Authorization: `Bearer ${datos.token}`,
      "Content-Type": "application/json",
      "X-Correlation-ID": `k6-${__VU}-${__ITER}`,
    },
    timeout: "30s",
  };

  // 70/30 lecturas/escrituras, decidido por iteracion.
  if (Math.random() < 0.7) {
    const ruta = RUTAS_LECTURA[__ITER % RUTAS_LECTURA.length];
    const res = http.get(`${GATEWAY}${ruta}`, cabeceras);
    lecturas.add(1);
    latencia_lectura.add(res.timings.duration);
    clasificar(res);
    check(res, { "lectura sin 500": (r) => r.status !== 500 });
  } else {
    const rand = Math.random();
    if (rand < 0.33) {
      // Escritura A: crear ticket de VENTA (no engorda la cola del tecnico).
      const res = http.post(
        `${GATEWAY}/api/v1/tickets/tickets/`,
        JSON.stringify({
          datosCliente: `Cliente k6 ${__VU}-${__ITER}`,
          documento_cliente: `${10000000 + (__VU * 1000 + __ITER) % 89999999}`,
          telefono_cliente: "999000111",
          tipoOperacion: "VENTA",
          prioridad: "MEDIA",
        }),
        cabeceras,
      );
      escrituras.add(1);
      latencia_escritura.add(res.timings.duration);
      clasificar(res);
      check(res, { "ticket sin 500": (r) => r.status !== 500 });
    } else if (rand < 0.66) {
      // Escritura B: alta de producto (dispara evento -> auditoria y notificaciones).
      const res = http.post(
        `${GATEWAY}/api/v1/almacen/almacen/productos`,
        JSON.stringify({
          nombre: `CARGA-k6 ${__VU}-${__ITER}`,
          categoria: "REPUESTO",
          sede: SEDE,
          stock_inicial: 5,
          precio_unitario: 10.0,
        }),
        cabeceras,
      );
      escrituras.add(1);
      latencia_escritura.add(res.timings.duration);
      clasificar(res);
      check(res, { "producto sin 500": (r) => r.status !== 500 });
    } else {
      // Escritura C: Flujo completo de Soporte (conecta todos los servicios y genera todos los datos)
      // 1. Alta de un repuesto para el diagnóstico
      const repuestoRes = http.post(
        `${GATEWAY}/api/v1/almacen/almacen/productos`,
        JSON.stringify({
          nombre: `CARGA-k6-Rep-${__VU}-${__ITER}`,
          categoria: "REPUESTO",
          sede: SEDE,
          stock_inicial: 10,
          precio_unitario: 25.0,
        }),
        cabeceras,
      );
      escrituras.add(1);
      latencia_escritura.add(repuestoRes.timings.duration);
      clasificar(repuestoRes);
      check(repuestoRes, { "producto k6 sin 500": (r) => r.status !== 500 });

      if (repuestoRes.status === 201) {
        const repuestoCod = repuestoRes.json("codigo");

        // 2. Crear un ticket de SOPORTE
        const ticketRes = http.post(
          `${GATEWAY}/api/v1/tickets/tickets/`,
          JSON.stringify({
            datosCliente: `Cliente k6-Soporte ${__VU}-${__ITER}`,
            documento_cliente: `${10000000 + (__VU * 1000 + __ITER) % 89999999}`,
            telefono_cliente: "999888777",
            tipoOperacion: "SOPORTE",
            prioridad: "ALTA",
            equipo: "Laptop Gamer K6",
            numero_serie: `SN-K6-${__VU}-${__ITER}`,
            caracteristicas_falla: "Pantalla azul recurrente bajo carga",
          }),
          cabeceras,
        );
        escrituras.add(1);
        latencia_escritura.add(ticketRes.timings.duration);
        clasificar(ticketRes);
        check(ticketRes, { "ticket k6 sin 500": (r) => r.status !== 500 });

        if (ticketRes.status === 201) {
          const ticketId = ticketRes.json("idTicket");

          // 3. Tomar el ticket (asignación)
          const tomarRes = http.post(
            `${GATEWAY}/api/v1/diagnosticos/asignaciones/tomar`,
            JSON.stringify({
              id_ticket: ticketId,
              datos_cliente: `Cliente k6-Soporte ${__VU}-${__ITER}`,
              equipo: "Laptop Gamer K6",
              numero_serie: `SN-K6-${__VU}-${__ITER}`,
              prioridad: "ALTA",
              tipo_operacion: "SOPORTE",
            }),
            cabeceras,
          );
          escrituras.add(1);
          latencia_escritura.add(tomarRes.timings.duration);
          clasificar(tomarRes);
          check(tomarRes, { "asignacion k6 sin 500": (r) => r.status !== 500 });

          if (tomarRes.status === 201) {
            // 4. Registrar diagnóstico
            const diagnosticoRes = http.post(
              `${GATEWAY}/api/v1/diagnosticos/diagnosticos/`,
              JSON.stringify({
                idTicket: ticketId,
                fallaDetectada: "Falla de memoria RAM detectada",
                mano_obra: 50.0,
                precio_reparacion: 75.0,
                repuestos: [{
                  codigo_repuesto: repuestoCod,
                  descripcion: "Memoria RAM",
                  cantidad: 1,
                  precio_unitario: 25.0
                }],
              }),
              cabeceras,
            );
            escrituras.add(1);
            latencia_escritura.add(diagnosticoRes.timings.duration);
            clasificar(diagnosticoRes);
            check(diagnosticoRes, { "diagnostico k6 sin 500": (r) => r.status !== 500 });

            if (diagnosticoRes.status === 201) {
              // 5. Emitir factura y garantía
              const facturaRes = http.post(
                `${GATEWAY}/api/v1/facturas/facturas/`,
                JSON.stringify({
                  idTicket: ticketId,
                  sede: SEDE,
                  montoManoObra: 50.0,
                  montoRepuestos: 25.0,
                  metodoPago: "TARJETA",
                  lineas: [],
                  tipoOperacion: "SOPORTE",
                  documentoCliente: `${10000000 + (__VU * 1000 + __ITER) % 89999999}`,
                  equipo: "Laptop Gamer K6",
                  numeroSerie: `SN-K6-${__VU}-${__ITER}`,
                  descripcion: "Falla de memoria RAM detectada",
                }),
                cabeceras,
              );
              escrituras.add(1);
              latencia_escritura.add(facturaRes.timings.duration);
              clasificar(facturaRes);
              check(facturaRes, { "factura k6 sin 500": (r) => r.status !== 500 });
            }
          }
        }
      }
    }
  }
}


/**
 * Emite el resumen como JSON entre marcas, para que el runner de Python lo
 * extraiga sin confundirlo con el resto de la salida.
 *
 * `--summary-export` desaparecio en k6 v2, asi que esta es la via soportada.
 */
export function handleSummary(data) {
  const marcaInicio = "<<<RESUMEN_JSON>>>";
  const marcaFin = "<<<FIN_RESUMEN_JSON>>>";
  return {
    stdout: `\n${marcaInicio}\n${JSON.stringify(data)}\n${marcaFin}\n`,
  };
}

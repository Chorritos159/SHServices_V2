import { NextResponse, type NextRequest } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: VENTA DIRECTA de mostrador (rol CAJA).
 *
 * Es el único flujo de la aplicación que orquesta varias llamadas, y por eso
 * vive aquí y no en el Gateway: el Gateway se mantiene en seguridad,
 * enrutamiento y adaptación (ADR-0002), sin lógica de negocio.
 *
 * ORDEN DE LOS PASOS — no es arbitrario:
 *
 *   1. Ticket (BEST-EFFORT). Una venta directa deja constancia como ticket en
 *      estado VENTA_REGISTRADA, pero el ticket NO es lo esencial: lo esencial
 *      es que se cobre y que salga el stock. Si ticket-service está caído la
 *      venta continúa con una referencia propia `VENTA-{SEDE}-{hex}`.
 *   2. Stock (DURO y ATÓMICO). Se descuenta ANTES de cobrar: si falta stock
 *      devolvemos 409 y no se ha cobrado nada. Al revés habríamos cobrado algo
 *      que no se puede entregar, que es el error caro. Va en UNA sola llamada
 *      con todo el carrito, así que o salen todos los productos o ninguno: no
 *      hace falta compensar nada desde aquí.
 *   3. Factura. Si facturación está caída, el Gateway la encola en su outbox
 *      (202) y se entrega sola cuando vuelva, así que el stock ya descontado
 *      termina casando con su comprobante.
 */

interface LineaVenta {
  codigo_producto: string;
  descripcion: string;
  cantidad: number;
  precio_unitario: number;
}

export async function POST(request: NextRequest) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "No autenticado." }, { status: 401 });
  }
  if (session.rol !== "CAJA" && session.rol !== "ADMIN") {
    return NextResponse.json(
      { error: "Solo Caja o Administración pueden registrar una venta." },
      { status: 403 },
    );
  }

  const body = await request.json();
  const lineas: LineaVenta[] = Array.isArray(body.lineas) ? body.lineas : [];
  const sede = session.sede;

  if (lineas.length === 0) {
    return NextResponse.json(
      { error: "Agrega al menos un producto a la venta." },
      { status: 422 },
    );
  }

  const total = lineas.reduce((acc, l) => acc + l.cantidad * l.precio_unitario, 0);

  // ── Paso 1: ticket (best-effort) ──────────────────────────────────────
  let idVenta = `VENTA-${sede.slice(0, 3).toUpperCase()}-${crypto.randomUUID().slice(0, 8).toUpperCase()}`;
  let ticketRegistrado = false;
  let avisoDegradado: string | null = null;

  try {
    const res = await gateway.post(
      "/tickets/tickets/",
      {
        datosCliente: body.datosCliente,
        documento_cliente: body.documento_cliente,
        telefono_cliente: body.telefono_cliente,
        tipoOperacion: "VENTA",
        prioridad: body.prioridad ?? "MEDIA",
        equipo: null,
        numero_serie: null,
        caracteristicas_falla: null,
        precio_estimado: total,
      },
      { headers: { "Idempotency-Key": crypto.randomUUID() } },
    );
    // 202 = el Gateway lo encoló porque ticket-service no respondía. La venta
    // NO espera a eso: seguimos con nuestra referencia propia.
    if (res.status === 202 || res.data?.encolado) {
      avisoDegradado =
        "El servicio de tickets no está disponible: la venta se registró igual con su comprobante. El ticket se creará solo cuando el servicio vuelva.";
    } else {
      idVenta = res.data.idTicket;
      ticketRegistrado = true;
    }
  } catch {
    // Caído del todo: la venta sigue. Es exactamente el caso que pide la S34.
    avisoDegradado =
      "El servicio de tickets no está disponible: la venta se completó igual con su comprobante y el descuento de stock.";
  }

  // ── Paso 2: stock (duro, atómico) ─────────────────────────────────────
  // UNA sola llamada con todo el carrito: almacen-service bloquea las N filas,
  // valida todas y hace un único commit. O salen todos los productos o no sale
  // ninguno, así que aquí no hay nada que compensar si algo falla.
  try {
    await gateway.post("/almacen/almacen/venta", {
      lineas: lineas.map((l) => ({
        codigo_producto: l.codigo_producto,
        cantidad: l.cantidad,
      })),
    });
  } catch (err) {
    const e = err as { status?: number; data?: { detail?: string } };
    return NextResponse.json(
      {
        error:
          e.data?.detail ??
          `No se pudo descontar la venta del inventario de ${sede}. No se ha cobrado nada.`,
      },
      { status: e.status === 409 || e.status === 404 ? (e.status as number) : 503 },
    );
  }

  // ── Paso 3: factura ───────────────────────────────────────────────────
  try {
    const res = await gateway.post(
      "/facturas/facturas/",
      {
        idTicket: idVenta,
        montoManoObra: 0,
        montoRepuestos: 0,
        lineas,
        metodoPago: body.metodoPago ?? "EFECTIVO",
        sede,
        tipoOperacion: "VENTA", // VENTA no emite garantía
        documentoCliente: body.documento_cliente ?? null,
      },
      { headers: { "Idempotency-Key": crypto.randomUUID() } },
    );

    if (res.status === 202 || res.data?.encolado) {
      return NextResponse.json(
        {
          ...res.data,
          idVenta,
          ticketRegistrado,
          degradado: true,
          mensaje:
            "El stock ya salió y el cobro quedó en cola: el comprobante se emitirá solo en cuanto facturación vuelva. No lo vuelvas a cobrar.",
        },
        { status: 202 },
      );
    }

    return NextResponse.json(
      { ...res.data, idVenta, ticketRegistrado, avisoDegradado },
      { status: 201 },
    );
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo al emitir el comprobante." }, {
      status: e.status ?? 500,
    });
  }
}

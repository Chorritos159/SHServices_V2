import { NextResponse, type NextRequest } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: emisión de comprobantes (facturación).
 * Mapea a POST /api/v1/facturas/facturas/ (service=facturas, path=facturas/).
 */
export async function POST(request: NextRequest) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "No autenticado." }, { status: 401 });
  }

  const body = await request.json();

  // Los datos del equipo viajan con el cobro para que facturacion-service
  // emita la GARANTIA sin depender del ticket-service.
  const payload = {
    idTicket: body.idTicket,
    montoManoObra: Number(body.montoManoObra),
    montoRepuestos: Number(body.montoRepuestos ?? 0),
    metodoPago: body.metodoPago,
    sede: body.sede,
    tipoOperacion: body.tipoOperacion ?? "SOPORTE",
    documentoCliente: body.documentoCliente ?? null,
    equipo: body.equipo ?? null,
    numeroSerie: body.numeroSerie ?? null,
    descripcion: body.descripcion ?? null,
  };

  let data: unknown;
  try {
    const res = await gateway.post("/facturas/facturas/", payload, {
      headers: { "Idempotency-Key": crypto.randomUUID() },
    });
    data = res.data;
    // Si facturación estaba caída, el cobro quedó ENCOLADO: avisamos y NO
    // seguimos con el cierre del ticket (todavía no hay comprobante).
    if (res.status === 202 || (data as { encolado?: boolean })?.encolado) {
      return NextResponse.json(data, { status: 202 });
    }
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }

  // Transición gobernada → ENTREGADO: el ticket_service CONFIRMA (consume) el
  // stock reservado y cierra el ticket. La GARANTÍA ya la emitió facturación
  // junto con el cobro, así que si esto falla el comprobante sigue completo.
  try {
    const montoTotal = (data as { montoTotal?: number })?.montoTotal ?? 0;
    await gateway.post(
      `/tickets/tickets/${encodeURIComponent(payload.idTicket)}/entregar`,
      { monto_total: montoTotal },
    );
  } catch {
    // La factura y la garantía ya existen; no bloqueamos el éxito por el cierre.
  }

  return NextResponse.json(data as Record<string, unknown>, { status: 201 });
}

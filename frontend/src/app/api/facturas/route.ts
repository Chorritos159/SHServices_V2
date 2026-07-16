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

  const payload = {
    idTicket: body.idTicket,
    montoManoObra: Number(body.montoManoObra),
    montoRepuestos: Number(body.montoRepuestos ?? 0),
    metodoPago: body.metodoPago,
    sede: body.sede,
  };

  let data: unknown;
  try {
    const res = await gateway.post("/facturas/facturas/", payload);
    data = res.data;
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }

  // Transición gobernada → ENTREGADO: el ticket_service CONFIRMA (consume) el stock
  // reservado y genera la GARANTÍA de 90 días. Devolvemos la garantía al comprobante.
  let garantia: unknown = null;
  try {
    const montoTotal = (data as { montoTotal?: number })?.montoTotal ?? 0;
    const res = await gateway.post(
      `/tickets/tickets/${encodeURIComponent(payload.idTicket)}/entregar`,
      { monto_total: montoTotal },
    );
    garantia = (res.data as { garantia?: unknown })?.garantia ?? null;
  } catch {
    // La factura ya se emitió; no bloqueamos el éxito por el cierre del ticket.
  }

  return NextResponse.json({ ...(data as Record<string, unknown>), garantia }, { status: 201 });
}

import { NextResponse } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: comprobante que respalda una garantía. Al hacer clic en una garantía,
 * la UI pide aquí la factura de ese ticket.
 *
 * Todo lo sirve **facturacion-service** (`/facturas/garantias/factura-de/{id}`):
 * garantía y comprobante viven juntos, sin depender del ticket-service.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ idTicket: string }> },
) {
  const session = await getSession();
  if (!session || (session.rol !== "ADMIN" && session.rol !== "CAJA")) {
    return NextResponse.json({ error: "No autorizado." }, { status: 403 });
  }
  const { idTicket } = await params;

  try {
    const { data } = await gateway.get(
      `/facturas/garantias/factura-de/${encodeURIComponent(idTicket)}`,
    );
    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }
}

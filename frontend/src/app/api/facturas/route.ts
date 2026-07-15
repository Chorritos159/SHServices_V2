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

  try {
    const { data } = await gateway.post("/facturas/facturas/", payload);
    return NextResponse.json(data, { status: 201 });
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }
}

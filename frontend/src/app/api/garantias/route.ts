import { NextResponse } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: consulta de garantías (para CAJA y ADMIN).
 * Ruta DOBLADA → /tickets/tickets/garantias → ticket-service:80/api/v1/tickets/garantias.
 */
export async function GET() {
  const session = await getSession();
  if (!session || (session.rol !== "ADMIN" && session.rol !== "CAJA")) {
    return NextResponse.json({ error: "No autorizado." }, { status: 403 });
  }

  try {
    const { data } = await gateway.get("/tickets/tickets/garantias");
    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }
}

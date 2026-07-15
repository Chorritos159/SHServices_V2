import { NextResponse } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: bandeja del técnico (tickets EN_COLA).
 * Ruta DOBLADA hacia el Gateway → /tickets/tickets/pendientes
 *   → (Toxiproxy) → ticket-service:80/api/v1/tickets/pendientes  ✅
 * Es ruta fija, no ?estado=..., porque el Gateway descarta los query strings.
 */
export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "No autenticado." }, { status: 401 });
  }

  try {
    const { data } = await gateway.get("/tickets/tickets/pendientes");
    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }
}

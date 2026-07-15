import { NextResponse } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: tickets filtrados por estado (ej. DIAGNOSTICADO para Entregas y Cobros).
 * Ruta DOBLADA hacia el Gateway → /tickets/tickets/por-estado/{estado}.
 * Filtro por RUTA (no query) porque el Gateway descarta los query strings.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ estado: string }> },
) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "No autenticado." }, { status: 401 });
  }
  const { estado } = await params;

  try {
    const { data } = await gateway.get(`/tickets/tickets/por-estado/${encodeURIComponent(estado)}`);
    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }
}

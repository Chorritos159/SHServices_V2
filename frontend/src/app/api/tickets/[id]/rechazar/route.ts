import { NextResponse } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: rechazo de presupuesto. Transición gobernada → RECHAZADO en el ticket_service,
 * que LIBERA el stock reservado (vuelve a disponible).
 */
export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "No autenticado." }, { status: 401 });
  }
  const { id } = await params;

  try {
    const { data } = await gateway.post(`/tickets/tickets/${encodeURIComponent(id)}/rechazar`, {});
    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }
}

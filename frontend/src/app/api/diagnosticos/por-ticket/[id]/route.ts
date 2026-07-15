import { NextResponse } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: desglose del diagnóstico de un ticket (para el modal de cobro).
 * Ruta DOBLADA → /diagnosticos/diagnosticos/por-ticket/{id}.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "No autenticado." }, { status: 401 });
  }
  const { id } = await params;

  try {
    const { data } = await gateway.get(`/diagnosticos/diagnosticos/por-ticket/${encodeURIComponent(id)}`);
    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }
}

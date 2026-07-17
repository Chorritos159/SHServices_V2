import { NextResponse } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: "Mis Tickets" del técnico. La lista la sirve el diagnostico-service, así
 * que sigue funcionando aunque el ticket-service esté caído (resiliencia: el
 * trabajo del técnico no se detiene por una caída de tickets).
 */
export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "No autenticado." }, { status: 401 });
  }

  try {
    const { data } = await gateway.get("/diagnosticos/asignaciones/mias");
    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }
}

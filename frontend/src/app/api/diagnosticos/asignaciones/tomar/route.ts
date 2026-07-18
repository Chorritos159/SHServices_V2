import { NextResponse, type NextRequest } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: el técnico TOMA un ticket de la cola.
 * Navegador → (POST /api/diagnosticos/asignaciones/tomar) → Gateway
 *   → diagnostico-service (dueño de las asignaciones).
 *
 * El técnico y la sede los inyecta el Gateway desde el JWT; aquí solo se
 * reenvían los datos del ticket que el frontend ya tenía (para cachearlos y
 * poder pintar "Mis Tickets" sin depender del ticket-service).
 */
export async function POST(request: NextRequest) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "No autenticado." }, { status: 401 });
  }

  const body = await request.json();
  if (!body?.id_ticket) {
    return NextResponse.json({ error: "Falta el id del ticket a tomar." }, { status: 400 });
  }

  try {
    const res = await gateway.post("/diagnosticos/asignaciones/tomar", body, {
      headers: { "Idempotency-Key": crypto.randomUUID() },
    });
    return NextResponse.json(res.data, { status: res.status });
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }
}

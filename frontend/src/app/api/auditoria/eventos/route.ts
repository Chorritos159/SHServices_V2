import { NextResponse } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: traza de auditoría.
 * Ruta DOBLADA hacia el Gateway → /auditoria/auditoria/eventos
 *   → auditoria-service:80/api/v1/auditoria/eventos  ✅
 * (Requiere que "auditoria" esté registrado en MICROSERVICIOS del Gateway.)
 */
export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "No autenticado." }, { status: 401 });
  }

  try {
    const { data } = await gateway.get("/auditoria/auditoria/eventos");
    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }
}

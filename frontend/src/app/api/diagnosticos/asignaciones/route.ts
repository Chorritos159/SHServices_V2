import { NextResponse } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF (ADMIN): todos los tickets tomados y quién los atiende.
 * La sirve el diagnostico-service. El RBAC real vive en el backend (403 si el
 * rol del JWT no es ADMIN); aquí solo exigimos sesión.
 */
export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "No autenticado." }, { status: 401 });
  }

  try {
    const { data } = await gateway.get("/diagnosticos/asignaciones/");
    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }
}

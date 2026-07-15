import { NextResponse } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/** BFF: marca como leídas las alertas del rol (al abrir la campanita). */
export async function POST() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ actualizadas: 0 }, { status: 200 });
  }
  try {
    const { data } = await gateway.post("/notificaciones/notificaciones/marcar-leidas", {});
    return NextResponse.json(data, { status: 200 });
  } catch {
    return NextResponse.json({ actualizadas: 0 }, { status: 200 });
  }
}

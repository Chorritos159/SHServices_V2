import { NextResponse } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: alertas no leídas del rol del usuario. El Gateway inyecta X-User-Rol y el
 * notificacion-service filtra por ese rol.
 */
export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json([], { status: 200 });
  }
  try {
    const { data } = await gateway.get("/notificaciones/notificaciones/mis-alertas");
    return NextResponse.json(data, { status: 200 });
  } catch {
    // No rompemos la UI por un fallo del polling.
    return NextResponse.json([], { status: 200 });
  }
}

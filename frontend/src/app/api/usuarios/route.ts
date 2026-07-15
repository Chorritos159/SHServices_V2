import { NextResponse, type NextRequest } from "next/server";
import { getSession, getSessionToken } from "@/lib/auth/session";
import { authClient } from "@/lib/api/auth";

/**
 * BFF de gestión de usuarios (solo ADMIN).
 *
 * OJO: /auth NO pasa por el Gateway (lo bloquea), así que estas llamadas van
 * DIRECTO al auth-service con el Bearer tomado de la cookie HttpOnly. El
 * auth-service revalida el token y exige rol ADMIN.
 */
async function authHeader() {
  const token = await getSessionToken();
  return { Authorization: `Bearer ${token ?? ""}` };
}

export async function GET() {
  const session = await getSession();
  if (session?.rol !== "ADMIN") {
    return NextResponse.json({ error: "Solo ADMIN." }, { status: 403 });
  }
  try {
    const { data } = await authClient.get("/usuarios", { headers: await authHeader() });
    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    return reenviarError(err);
  }
}

export async function POST(request: NextRequest) {
  const session = await getSession();
  if (session?.rol !== "ADMIN") {
    return NextResponse.json({ error: "Solo ADMIN." }, { status: 403 });
  }
  const body = await request.json();
  try {
    const { data } = await authClient.post("/usuarios", body, { headers: await authHeader() });
    return NextResponse.json(data, { status: 201 });
  } catch (err) {
    return reenviarError(err);
  }
}

function reenviarError(err: unknown) {
  const e = err as { response?: { status?: number; data?: unknown } };
  return NextResponse.json(e.response?.data ?? { error: "Fallo al contactar el auth-service." }, {
    status: e.response?.status ?? 500,
  });
}

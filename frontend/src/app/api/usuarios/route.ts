import { NextResponse, type NextRequest } from "next/server";
import { getSession, getSessionToken } from "@/lib/auth/session";
import { authClient } from "@/lib/api/auth";

/**
 * BFF de gestión de usuarios (solo ADMIN).
 *
 * Va por el Gateway con el path DOBLADO (`/auth/usuarios` sobre el baseURL
 * `/api/v1/auth`): el proxy generico reenvia `/api/v1/{svc}/{path}` como
 * `{svc}/api/v1/{path}`, y la ruta interna del auth-service es
 * `/api/v1/auth/usuarios`. Sin doblar daba 404 ("No encontrado" en el panel).
 * El login NO se dobla porque usa la ruta publica especial del Gateway.
 * El Bearer sale de la cookie HttpOnly; el auth-service exige rol ADMIN.
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
    const { data } = await authClient.get("/auth/usuarios", { headers: await authHeader() });
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
    const { data } = await authClient.post("/auth/usuarios", body, { headers: await authHeader() });
    return NextResponse.json(data, { status: 201 });
  } catch (err) {
    return reenviarError(err);
  }
}

function reenviarError(err: unknown) {
  const e = err as { response?: { status?: number; data?: unknown }; code?: string };

  // Sin respuesta = no se pudo ni contactar (auth caido, DNS, timeout). Antes
  // esto se convertia en un 500 generico, que es MENTIRA y ademas confunde: un
  // 500 dice "el servidor se rompio procesando tu peticion", cuando lo que
  // pasa es que la peticion no llego a procesarse. Se responde 503, que es lo
  // que el front sabe traducir a "no se creo nada, reintenta".
  if (!e.response) {
    return NextResponse.json(
      {
        error: "El servicio de identidad no esta disponible.",
        detalle:
          "No se pudo contactar con el auth-service. Si acabas de intentar un alta y el " +
          "servicio vuelve en unos segundos, el Gateway puede entregarla desde su outbox: " +
          "refresca la lista antes de reintentar.",
      },
      { status: 503 },
    );
  }

  return NextResponse.json(e.response.data ?? { error: "Fallo al contactar el auth-service." }, {
    status: e.response.status ?? 503,
  });
}

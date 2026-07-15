import { NextResponse, type NextRequest } from "next/server";
import { verifyToken } from "@/lib/auth/jwt";
import { config as appConfig } from "@/lib/config";
import type { Rol } from "@/lib/types/auth";

/** Panel de inicio de cada rol. */
function homeDeRol(rol: Rol): string {
  if (rol === "ADMIN") return "/admin";
  if (rol === "CAJA") return "/caja";
  return "/tecnico";
}

/**
 * Proxy RBAC (Edge) — primera línea de defensa de rutas.
 * Separación estricta por rol:
 *   · /admin/*   → solo ADMIN
 *   · /caja/*    → solo CAJA    (Registro de Tickets + Facturación)
 *   · /tecnico/* → solo TECNICO (Diagnóstico)
 * Un rol que entre a un área ajena es redirigido a SU panel.
 *
 * ⚠️ No reemplaza el RBAC del backend (el Gateway revalida el token y el rol).
 */
export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get(appConfig.sessionCookieName)?.value;
  const session = token ? await verifyToken(token) : null;

  // Ruta pública de login.
  if (pathname === "/login") {
    if (session) {
      return NextResponse.redirect(new URL(homeDeRol(session.rol), request.url));
    }
    return NextResponse.next();
  }

  // A partir de aquí, todo exige sesión válida.
  if (!session) {
    const loginUrl = new URL("/login", request.url);
    if (pathname !== "/") loginUrl.searchParams.set("next", pathname);
    const response = NextResponse.redirect(loginUrl);
    if (token) response.cookies.delete(appConfig.sessionCookieName);
    return response;
  }

  const home = homeDeRol(session.rol);

  // Raíz → panel del rol.
  if (pathname === "/") {
    return NextResponse.redirect(new URL(home, request.url));
  }

  // Guardas por área: si el rol no corresponde, a su propio panel.
  const areas: Array<{ prefijo: string; rol: Rol }> = [
    { prefijo: "/admin", rol: "ADMIN" },
    { prefijo: "/caja", rol: "CAJA" },
    { prefijo: "/tecnico", rol: "TECNICO" },
  ];
  for (const area of areas) {
    if (pathname.startsWith(area.prefijo) && session.rol !== area.rol) {
      return NextResponse.redirect(new URL(home, request.url));
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/", "/login", "/admin/:path*", "/caja/:path*", "/tecnico/:path*"],
};

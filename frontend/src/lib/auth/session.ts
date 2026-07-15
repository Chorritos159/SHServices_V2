import "server-only";
import { cookies } from "next/headers";
import { config } from "@/lib/config";
import { verifyToken } from "@/lib/auth/jwt";
import type { SessionPayload } from "@/lib/types/auth";

/**
 * Gestión de la sesión en una cookie HttpOnly.
 *
 * ¿Por qué HttpOnly? El JWT NUNCA queda accesible a `document.cookie` ni a
 * ningún script del navegador ⇒ inmune a robo por XSS. El token solo viaja
 * servidor↔servidor (Server Actions / Route Handlers → backend).
 */

const COOKIE = config.sessionCookieName;

/** Guarda el JWT en la cookie HttpOnly. `maxAgeSeconds` = expires_in del login. */
export async function createSession(token: string, maxAgeSeconds: number): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.set(COOKIE, token, {
    httpOnly: true, // ← blindaje anti-XSS: inaccesible desde JS del cliente
    secure: process.env.NODE_ENV === "production", // solo HTTPS en prod
    sameSite: "lax", // mitiga CSRF en navegación entre sitios
    path: "/",
    maxAge: maxAgeSeconds,
  });
}

/** Borra la cookie de sesión (logout / token inválido). */
export async function destroySession(): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.delete(COOKIE);
}

/** Devuelve el JWT crudo o `undefined` si no hay sesión. */
export async function getSessionToken(): Promise<string | undefined> {
  const cookieStore = await cookies();
  return cookieStore.get(COOKIE)?.value;
}

/**
 * Devuelve el payload verificado o `null`. Úsalo en Server Components /
 * Server Actions para conocer el usuario y su rol.
 */
export async function getSession(): Promise<SessionPayload | null> {
  const token = await getSessionToken();
  if (!token) return null;
  return verifyToken(token);
}

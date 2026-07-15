import { jwtVerify } from "jose";
import { jwtSecretKey } from "@/lib/config";
import type { SessionPayload } from "@/lib/types/auth";

/**
 * Verifica firma + expiración del JWT emitido por el auth-service.
 * Usa `jose` (no `jsonwebtoken`) porque el middleware corre en el
 * runtime Edge, donde los módulos nativos de Node no están disponibles.
 *
 * @returns el payload si el token es válido; `null` si es inválido/expirado.
 */
export async function verifyToken(token: string): Promise<SessionPayload | null> {
  try {
    const { payload } = await jwtVerify(token, jwtSecretKey, {
      algorithms: ["HS256"],
    });

    const rolesValidos = ["ADMIN", "CAJA", "TECNICO"];
    if (typeof payload.sub !== "string" || !rolesValidos.includes(payload.rol as string)) {
      return null;
    }

    return {
      sub: payload.sub,
      rol: payload.rol as SessionPayload["rol"],
      sede: typeof payload.sede === "string" ? payload.sede : "",
      exp: payload.exp ?? 0,
    };
  } catch {
    // Firma inválida, token corrupto o expirado.
    return null;
  }
}

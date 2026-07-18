/**
 * Lectura centralizada de configuración de servidor.
 * Nunca importes esto desde un Client Component: contiene el secreto JWT.
 */

function required(name: string, fallback?: string): string {
  const value = process.env[name] ?? fallback;
  if (!value) {
    throw new Error(`Falta la variable de entorno "${name}". Revisa tu .env.local`);
  }
  return value;
}

export const config = {
  // Único destino del backend: TODO pasa por el Gateway, incluido el login
  // (antes había un `authServiceUrl` apuntando al puerto 8003 del
  // auth-service; ese puerto ya no se publica — ver OWASP hallazgo 3).
  gatewayUrl: required("GATEWAY_URL", "http://localhost:8000"),
  jwtSecret: required("JWT_SECRET_KEY", "super_secreto_shservices_2026"),
  sessionCookieName: process.env.SESSION_COOKIE_NAME ?? "sh_session",
} as const;

/** Secreto JWT codificado para `jose` (HS256). */
export const jwtSecretKey = new TextEncoder().encode(config.jwtSecret);

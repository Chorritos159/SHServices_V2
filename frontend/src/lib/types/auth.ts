/** Roles que emite el auth-service en el claim `rol` del JWT. */
export type Rol = "ADMIN" | "CAJA" | "TECNICO";

/**
 * Forma del payload del JWT tal como lo fabrica
 * `auth_service/app/api/auth.py` → { sub, rol, sede, exp }.
 */
export interface SessionPayload {
  /** Usuario (claim estándar `sub`). Ej: "admin", "caja01". */
  sub: string;
  rol: Rol;
  /** Sede del empleado (ej. "PIURA", "LIMA"). */
  sede: string;
  /** Expiración (epoch en segundos). */
  exp: number;
}

/** Respuesta de POST /api/v1/auth/login. */
export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

/** Estado que devuelve la Server Action de login a `useActionState`. */
export interface LoginState {
  error?: string;
}

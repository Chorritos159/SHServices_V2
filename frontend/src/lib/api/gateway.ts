import "server-only";
import axios, { AxiosError } from "axios";
import { config } from "@/lib/config";
import { getSessionToken } from "@/lib/auth/session";

/**
 * Cliente HTTP (Axios) hacia el API Gateway.
 *
 * SOLO se usa en el servidor (Server Actions / Route Handlers), porque su
 * interceptor lee el JWT desde la cookie HttpOnly — algo imposible en el
 * navegador por diseño. Este es el patrón BFF: el navegador nunca toca el
 * token; Next actúa de proxy y lo inyecta aquí.
 */
export const gateway = axios.create({
  baseURL: `${config.gatewayUrl}/api/v1`,
  timeout: 8000,
  headers: { "Content-Type": "application/json" },
});

// ── Interceptor de PETICIÓN ──────────────────────────────────────────────
// Inyecta el "Authorization: Bearer <jwt>" en CADA petición saliente y
// propaga un X-Correlation-ID para casar el rastro con Prometheus/Grafana.
gateway.interceptors.request.use(async (request) => {
  const token = await getSessionToken();
  if (token) {
    request.headers.set("Authorization", `Bearer ${token}`);
  }
  request.headers.set("X-Correlation-ID", crypto.randomUUID());
  return request;
});

/**
 * Error normalizado del Gateway.
 *
 * Es una subclase de `Error` (y no un objeto plano) para que conserve el stack
 * trace y para que cualquier `catch` genérico pueda tratarlo como un error de
 * verdad. Los handlers del BFF siguen leyendo `.status` y `.data` igual que
 * antes.
 */
export class GatewayError extends Error {
  readonly status: number;
  readonly data: unknown;

  constructor(status: number, data: unknown) {
    super(`El API Gateway respondió ${status}.`);
    this.name = "GatewayError";
    this.status = status;
    this.data = data;
  }
}

// ── Interceptor de RESPUESTA ─────────────────────────────────────────────
// Normaliza los errores del Gateway (401 token expirado, 403 RBAC,
// 503 circuit-breaker, 504 timeout) para que el BFF los reenvíe limpios.
gateway.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const status = error.response?.status ?? 500;
    const data = error.response?.data ?? {
      error: "No se pudo contactar al API Gateway.",
    };
    return Promise.reject(new GatewayError(status, data));
  },
);

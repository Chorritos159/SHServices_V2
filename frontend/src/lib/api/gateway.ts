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

// ── Interceptor de RESPUESTA ─────────────────────────────────────────────
// Normaliza los errores del Gateway (401 token expirado, 403 RBAC,
// 503 circuit-breaker, 504 timeout) para que el BFF los reenvíe limpios.
gateway.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const status = error.response?.status;
    const data = error.response?.data;
    return Promise.reject({
      status: status ?? 500,
      data: data ?? { error: "No se pudo contactar al API Gateway." },
    });
  },
);

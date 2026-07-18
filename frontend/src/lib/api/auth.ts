import "server-only";
import axios from "axios";
import { config } from "@/lib/config";

/**
 * Cliente Axios para las operaciones de identidad.
 *
 * Va por el **API Gateway**, igual que todo lo demás. Antes apuntaba directo
 * al puerto 8003 del auth-service porque el Gateway bloqueaba `/api/v1/auth/*`
 * con un 403, y eso dejaba el login como la única operación del sistema sin
 * rate limit, sin circuit breaker y sin pasar por el punto de entrada único
 * (hallazgos 3 y 4 de `seguridad/OWASP_Top10.md`).
 *
 * No lleva interceptor de Bearer: en el login todavía no hay token, y para
 * `/usuarios` el BFF adjunta la cabecera a mano desde la cookie HttpOnly.
 */
export const authClient = axios.create({
  baseURL: `${config.gatewayUrl}/api/v1/auth`,
  timeout: 8000,
  headers: { "Content-Type": "application/json" },
});

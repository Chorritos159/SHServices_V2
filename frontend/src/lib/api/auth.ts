import "server-only";
import axios from "axios";
import { config } from "@/lib/config";

/**
 * Cliente Axios exclusivo para el auth-service.
 *
 * ⚠️ Va DIRECTO al puerto 8003, NO por el Gateway: el Gateway bloquea
 * explícitamente /api/v1/auth/* (api_gateway/app/main.py). Aún no hay token
 * en el login, así que este cliente no lleva interceptor de Bearer.
 */
export const authClient = axios.create({
  baseURL: `${config.authServiceUrl}/api/v1/auth`,
  timeout: 8000,
  headers: { "Content-Type": "application/json" },
});

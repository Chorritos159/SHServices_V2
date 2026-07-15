"use client";
import axios from "axios";

/**
 * Cliente Axios del NAVEGADOR. Habla únicamente con el BFF de Next
 * (rutas /api/* del mismo origen), nunca directo con el backend.
 *
 * No necesita inyectar el Bearer: la cookie HttpOnly viaja sola en las
 * peticiones al mismo origen (withCredentials). El token permanece oculto
 * a JavaScript ⇒ sigue siendo inmune a XSS.
 */
export const api = axios.create({
  baseURL: "/api",
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

// Si el BFF responde 401 (sesión caducada), mandamos al login.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (typeof window !== "undefined" && error?.response?.status === 401) {
      window.location.href = "/login";
    }
    return Promise.reject(error);
  },
);

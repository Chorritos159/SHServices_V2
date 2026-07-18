"use server";

import { redirect } from "next/navigation";
import { isAxiosError } from "axios";
import { authClient } from "@/lib/api/auth";
import { createSession, destroySession } from "@/lib/auth/session";
import { verifyToken } from "@/lib/auth/jwt";
import type { LoginState, TokenResponse } from "@/lib/types/auth";
import { campoTexto } from "@/lib/form";

/**
 * Server Action del login.
 *
 * Flujo seguro (todo en el servidor, el token nunca toca el navegador):
 *   1. POST directo al auth-service (8003) con { usuario, password }.
 *   2. Se verifica la firma del JWT recibido y se extrae el rol.
 *   3. Se guarda el JWT en una cookie HttpOnly (anti-XSS).
 *   4. Se redirige según el rol (ADMIN → /admin, CAJA → /caja, TECNICO → /tecnico).
 *
 * Compatible con `useActionState`: en error devuelve { error }.
 */
function homeDeRol(rol: string): string {
  if (rol === "ADMIN") return "/admin";
  if (rol === "CAJA") return "/caja";
  return "/tecnico";
}
export async function loginAction(
  _prev: LoginState,
  formData: FormData,
): Promise<LoginState> {
  const usuario = campoTexto(formData, "usuario").trim();
  const password = campoTexto(formData, "password");

  if (!usuario || !password) {
    return { error: "Ingresa usuario y contraseña." };
  }

  let token: string;
  let expiresIn: number;

  try {
    const { data } = await authClient.post<TokenResponse>("/login", {
      usuario,
      password,
    });
    token = data.access_token;
    expiresIn = data.expires_in;
  } catch (err) {
    if (isAxiosError(err)) {
      const estado = err.response?.status;
      // El Gateway ya redacta mensajes pensados para una persona (servicio de
      // acceso caído, bloqueo por intentos, demasiadas solicitudes). Si viene
      // uno, se muestra tal cual en vez de sustituirlo por un genérico.
      const delGateway = (err.response?.data as { detalle?: string })?.detalle;

      if (estado === 401) {
        return { error: "Usuario o contraseña incorrectos." };
      }
      if (estado === 429 || estado === 503) {
        return { error: delGateway ?? "El servicio de acceso no está disponible ahora mismo." };
      }
      if (!err.response) {
        return {
          error:
            "No se pudo contactar con el sistema. Revisa tu conexión y vuelve a intentarlo.",
        };
      }
      if (delGateway) return { error: delGateway };
    }
    return { error: "Error inesperado al iniciar sesión. Vuelve a intentarlo." };
  }

  // Doble verificación: confirmamos la firma antes de confiar en el rol.
  const payload = await verifyToken(token);
  if (!payload) {
    return { error: "El servidor devolvió un token inválido." };
  }

  await createSession(token, expiresIn);

  // redirect() lanza una excepción de control: debe ir FUERA del try/catch.
  redirect(homeDeRol(payload.rol));
}

/** Cierra la sesión: borra la cookie y vuelve al login. */
export async function logoutAction(): Promise<void> {
  await destroySession();
  redirect("/login");
}

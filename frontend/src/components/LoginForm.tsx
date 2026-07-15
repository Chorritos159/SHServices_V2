"use client";

import { useActionState } from "react";
import { loginAction } from "@/lib/auth/actions";
import type { LoginState } from "@/lib/types/auth";

const initialState: LoginState = {};

export default function LoginForm() {
  const [state, formAction, pending] = useActionState(loginAction, initialState);

  return (
    <form action={formAction} className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <label htmlFor="usuario" className="text-sm font-medium text-slate-300">
          Usuario
        </label>
        <input
          id="usuario"
          name="usuario"
          type="text"
          autoComplete="username"
          placeholder="admin"
          required
          className="rounded-lg border border-slate-700 bg-slate-900 px-3.5 py-2.5 text-slate-100 placeholder:text-slate-600 outline-none transition focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="password" className="text-sm font-medium text-slate-300">
          Contraseña
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          placeholder="••••••••"
          required
          className="rounded-lg border border-slate-700 bg-slate-900 px-3.5 py-2.5 text-slate-100 placeholder:text-slate-600 outline-none transition focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30"
        />
      </div>

      {state.error && (
        <p
          role="alert"
          className="rounded-lg border border-red-900/60 bg-red-950/50 px-3.5 py-2.5 text-sm text-red-300"
        >
          {state.error}
        </p>
      )}

      <button
        type="submit"
        disabled={pending}
        className="mt-1 rounded-lg bg-sky-600 px-4 py-2.5 font-semibold text-white transition hover:bg-sky-500 focus:ring-2 focus:ring-sky-500/40 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {pending ? "Verificando…" : "Iniciar sesión"}
      </button>
    </form>
  );
}

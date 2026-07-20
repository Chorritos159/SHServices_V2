"use client";

import { useCallback, useEffect, useState } from "react";
import { isAxiosError } from "axios";
import { api } from "@/lib/api/client";
import type { Usuario } from "@/lib/types/backend";
import { campoTexto } from "@/lib/form";

type Estado = { tipo: "idle" } | { tipo: "ok"; mensaje: string } | { tipo: "error"; mensaje: string };

const ROL_COLOR: Record<string, string> = {
  ADMIN: "text-emerald-400",
  CAJA: "text-amber-400",
  TECNICO: "text-cyan-400",
};

/**
 * Gestión de empleados (solo ADMIN). Alta de usuario con rol + sede y listado,
 * consumiendo el BFF /api/usuarios → auth-service.
 */
export default function UsuariosView() {
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [cargando, setCargando] = useState(true);
  const [errorLista, setErrorLista] = useState<string | null>(null);
  const [estado, setEstado] = useState<Estado>({ tipo: "idle" });
  const [enviando, setEnviando] = useState(false);

  const cargar = useCallback(async () => {
    setCargando(true);
    setErrorLista(null);
    try {
      const { data } = await api.get<Usuario[]>("/usuarios");
      setUsuarios(data);
    } catch (err) {
      setErrorLista(extraer(err));
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    cargar();
  }, [cargar]);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    setEnviando(true);
    setEstado({ tipo: "idle" });
    const fd = new FormData(form);
    try {
      const { data } = await api.post<Usuario>("/usuarios", {
        usuario: campoTexto(fd, "usuario").trim(),
        password: campoTexto(fd, "password"),
        rol: campoTexto(fd, "rol"),
        sede: campoTexto(fd, "sede").trim(),
      });
      setEstado({ tipo: "ok", mensaje: `✅ Usuario ${data.usuario} creado (${data.rol} · ${data.sede}).` });
      form.reset();
      cargar();
    } catch (err) {
      setEstado({ tipo: "error", mensaje: extraer(err) });
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
      {/* Formulario de alta */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-6">
        <h3 className="mb-4 text-base font-semibold text-white">Nuevo empleado</h3>
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <Campo name="usuario" label="Usuario" placeholder="caja02" />
          <Campo name="password" label="Contraseña" type="password" placeholder="mínimo 4 caracteres" />
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-300">Rol</span>
            <select
              name="rol"
              defaultValue="CAJA"
              required
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30"
            >
              <option value="ADMIN">ADMIN</option>
              <option value="CAJA">CAJA</option>
              <option value="TECNICO">TECNICO</option>
            </select>
          </label>
          <Campo name="sede" label="Sede" placeholder="PIURA, LIMA, TRUJILLO…" />
          <button
            type="submit"
            disabled={enviando}
            className="mt-1 rounded-lg bg-sky-600 px-4 py-2 font-semibold text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {enviando ? "Registrando…" : "Registrar empleado"}
          </button>
          {estado.tipo !== "idle" && (
            <p
              role="status"
              className={`rounded-lg border px-3 py-2 text-sm ${
                estado.tipo === "ok"
                  ? "border-emerald-900/60 bg-emerald-950/40 text-emerald-300"
                  : "border-red-900/60 bg-red-950/40 text-red-300"
              }`}
            >
              {estado.mensaje}
            </p>
          )}
        </form>
      </section>

      {/* Listado */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40">
        <header className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-200">Empleados{!cargando && ` · ${usuarios.length}`}</h3>
          <button
            onClick={cargar}
            disabled={cargando}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 transition hover:border-sky-700 hover:text-sky-300 disabled:opacity-50"
          >
            {cargando ? "Cargando…" : "↻ Refrescar"}
          </button>
        </header>

        {errorLista ? (
          <p className="px-5 py-6 text-sm text-red-300">{errorLista}</p>
        ) : cargando ? (
          <p className="px-5 py-6 text-sm text-slate-500">Cargando empleados…</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-500">
                <tr className="border-b border-slate-800">
                  <th className="px-5 py-2.5 font-medium">Usuario</th>
                  <th className="px-5 py-2.5 font-medium">Rol</th>
                  <th className="px-5 py-2.5 font-medium">Sede</th>
                </tr>
              </thead>
              <tbody>
                {usuarios.map((u) => (
                  <tr key={u.usuario} className="border-b border-slate-800/60 last:border-0">
                    <td className="px-5 py-2.5 font-medium text-slate-200">{u.usuario}</td>
                    <td className={`px-5 py-2.5 font-semibold ${ROL_COLOR[u.rol] ?? "text-slate-300"}`}>{u.rol}</td>
                    <td className="px-5 py-2.5 text-slate-400">{u.sede}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function extraer(err: unknown): string {
  if (!isAxiosError(err)) return "Error inesperado.";

  const status = err.response?.status;
  // OJO con el nombre del campo: el Gateway responde `detalle` (en espanol),
  // no `detail`. Al leer solo `detail` se perdia el texto util y el usuario
  // veia un escueto "Error 503" sin saber que hacer.
  const data = err.response?.data as
    | { error?: string; detalle?: string; detail?: string }
    | undefined;
  const delServidor = data?.detalle ?? data?.detail ?? data?.error;

  // Mensajes explicitos para los casos que el usuario SI puede accionar.
  if (status === 503 || status === 504) {
    return (
      "⏳ El servicio de identidad no responde. El Gateway puede haber dejado " +
      "el alta en su outbox y entregarla sola cuando el servicio vuelva: " +
      "REFRESCA la lista antes de reintentar, para no crear un duplicado."
    );
  }
  if (status === 429) {
    return "Demasiadas peticiones seguidas. Espera unos segundos y reintenta.";
  }
  if (status === 409) {
    return delServidor ?? "Ese usuario ya existe. Elige otro identificador.";
  }
  if (status === 403) {
    return "Solo un ADMIN puede dar de alta empleados.";
  }
  if (status === 401) {
    return "Tu sesion caduco. Vuelve a iniciar sesion.";
  }
  return delServidor ?? `Error ${status ?? ""}`.trim();
}

function Campo({
  name,
  label,
  type = "text",
  placeholder,
}: Readonly<{
  name: string;
  label: string;
  type?: string;
  placeholder?: string;
}>) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-slate-300">{label}</span>
      <input
        name={name}
        type={type}
        placeholder={placeholder}
        required
        className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 placeholder:text-slate-600 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30"
      />
    </label>
  );
}

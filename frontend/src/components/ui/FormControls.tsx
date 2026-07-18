"use client";

import { isAxiosError } from "axios";

/** Estado de resultado compartido por los formularios del operador. */
export type Estado =
  | { tipo: "idle" }
  | { tipo: "ok"; mensaje: string }
  | { tipo: "encolado"; mensaje: string }
  | { tipo: "error"; mensaje: string };

/**
 * ¿La respuesta del BFF indica que la escritura se ENCOLÓ? Cuando el servicio
 * destino está caído, el Gateway responde `202 { encolado:true, mensaje }` y la
 * reintenta sola con la misma Idempotency-Key (no se pierde ni se duplica). Los
 * formularios usan esto para mostrar un aviso amable en vez de tratarlo como éxito.
 */
export function esEncolado(data: unknown): data is { encolado: true; mensaje?: string; operacion?: string } {
  return !!data && typeof data === "object" && (data as { encolado?: boolean }).encolado === true;
}

/** Extrae un mensaje legible de un error de Axios (respeta { error } / { detail } del backend). */
export function extraerError(err: unknown): string {
  if (isAxiosError(err)) {
    const data = err.response?.data as { error?: string; detail?: string } | undefined;
    return data?.error ?? data?.detail ?? `Error ${err.response?.status ?? ""}`.trim();
  }
  return "Error inesperado.";
}

export function Campo({
  name,
  label,
  type = "text",
  placeholder,
  defaultValue,
  min,
  step,
  required = true,
}: Readonly<{
  name: string;
  label: string;
  type?: string;
  placeholder?: string;
  defaultValue?: string | number;
  min?: number;
  step?: string;
  required?: boolean;
}>) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-slate-300">{label}</span>
      <input
        name={name}
        type={type}
        placeholder={placeholder}
        defaultValue={defaultValue}
        min={min}
        step={step}
        required={required}
        className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 placeholder:text-slate-600 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/30"
      />
    </label>
  );
}

export function Select({
  name,
  label,
  options,
  defaultValue,
  onChange,
}: Readonly<{
  name: string;
  label: string;
  options: string[];
  defaultValue?: string;
  onChange?: (value: string) => void;
}>) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-slate-300">{label}</span>
      <select
        name={name}
        defaultValue={defaultValue}
        onChange={(e) => onChange?.(e.target.value)}
        required
        className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/30"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

export function Boton({ cargando, children }: Readonly<{ cargando: boolean; children: React.ReactNode }>) {
  return (
    <button
      type="submit"
      disabled={cargando}
      className="mt-1 rounded-lg bg-amber-600 px-4 py-2 font-semibold text-white transition hover:bg-amber-500 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {cargando ? "Enviando…" : children}
    </button>
  );
}

export function Feedback({ estado }: Readonly<{ estado: Estado }>) {
  if (estado.tipo === "idle") return null;
  const estilo =
    estado.tipo === "ok"
      ? "border-emerald-800/60 bg-emerald-950/40 text-emerald-200"
      : estado.tipo === "encolado"
        ? "border-amber-700/60 bg-amber-950/40 text-amber-200"
        : "border-red-900/60 bg-red-950/40 text-red-300";
  return (
    <div role="status" className={`rounded-lg border px-4 py-3 text-sm ${estilo}`}>
      {estado.mensaje}
    </div>
  );
}

"use client";

import { useState } from "react";
import { isAxiosError } from "axios";
import { api } from "@/lib/api/client";

type Estado =
  | { tipo: "idle" }
  | { tipo: "ok"; mensaje: string }
  | { tipo: "error"; mensaje: string };

/**
 * Alta de inventario (rol ADMIN). El código se autogenera en el backend (REP-001…),
 * así que aquí el Admin SOLO ingresa. La reserva/descuento de stock la hace el
 * técnico desde su panel de Diagnóstico (ya no vive aquí).
 */
export default function InventarioForm() {
  const [estado, setEstado] = useState<Estado>({ tipo: "idle" });
  const [cargando, setCargando] = useState(false);

  async function crearProducto(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    setCargando(true);
    setEstado({ tipo: "idle" });
    const fd = new FormData(form);
    try {
      const { data } = await api.post("/almacen/productos", {
        nombre: String(fd.get("nombre")),
        categoria: String(fd.get("categoria")),
        sede: String(fd.get("sede")),
        stock_inicial: Number(fd.get("stock_inicial")),
      });
      setEstado({
        tipo: "ok",
        mensaje: `✅ Producto ${data.codigo} · ${data.nombre} · stock ${data.stock_disponible} en ${data.sede}.`,
      });
      form.reset();
    } catch (err) {
      setEstado({ tipo: "error", mensaje: extraerError(err) });
    } finally {
      setCargando(false);
    }
  }

  return (
    <section className="max-w-xl rounded-xl border border-slate-800 bg-slate-900/50 p-6">
      <h3 className="mb-1 text-base font-semibold text-white">Ingresar producto</h3>
      <p className="mb-5 text-sm text-slate-400">El código (REP-XXX) se genera automáticamente.</p>
      <form onSubmit={crearProducto} className="flex flex-col gap-3">
        <Campo name="nombre" label="Nombre" placeholder="Fuente 500W" />
        <div className="grid grid-cols-2 gap-3">
          <Select name="categoria" label="Categoría" options={["REPUESTO", "PRODUCTO_VENTA"]} />
          <Select name="sede" label="Sede" options={["PIURA", "LIMA"]} />
        </div>
        <Campo name="stock_inicial" label="Stock inicial" type="number" placeholder="10" min={0} />
        <Boton cargando={cargando}>Guardar producto</Boton>
        <Feedback estado={estado} />
      </form>
    </section>
  );
}

function extraerError(err: unknown): string {
  if (isAxiosError(err)) {
    const data = err.response?.data as { error?: string; detail?: string } | undefined;
    return data?.error ?? data?.detail ?? `Error ${err.response?.status ?? ""}`.trim();
  }
  return "Error inesperado.";
}

function Campo({
  name,
  label,
  type = "text",
  placeholder,
  min,
}: {
  name: string;
  label: string;
  type?: string;
  placeholder?: string;
  min?: number;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-slate-300">{label}</span>
      <input
        name={name}
        type={type}
        placeholder={placeholder}
        min={min}
        required
        className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 placeholder:text-slate-600 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30"
      />
    </label>
  );
}

function Select({ name, label, options }: { name: string; label: string; options: string[] }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-slate-300">{label}</span>
      <select
        name={name}
        required
        className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30"
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

function Boton({ cargando, children }: { cargando: boolean; children: React.ReactNode }) {
  return (
    <button
      type="submit"
      disabled={cargando}
      className="mt-1 rounded-lg bg-sky-600 px-4 py-2 font-semibold text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {cargando ? "Enviando…" : children}
    </button>
  );
}

function Feedback({ estado }: { estado: Estado }) {
  if (estado.tipo === "idle") return null;
  const ok = estado.tipo === "ok";
  return (
    <p
      role="status"
      className={`rounded-lg border px-3 py-2 text-sm ${
        ok
          ? "border-emerald-900/60 bg-emerald-950/40 text-emerald-300"
          : "border-red-900/60 bg-red-950/40 text-red-300"
      }`}
    >
      {estado.mensaje}
    </p>
  );
}

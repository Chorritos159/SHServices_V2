"use client";

import { useCallback, useEffect, useState } from "react";
import { isAxiosError } from "axios";
import { api } from "@/lib/api/client";
import type { ProductoInventario } from "@/lib/types/backend";

/**
 * Tabla de inventario. Navegador → Axios BFF (/api/almacen/productos) → Gateway
 * → GET /api/v1/almacen/productos.
 */
export default function ProductosTable() {
  const [productos, setProductos] = useState<ProductoInventario[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const { data } = await api.get<ProductoInventario[]>("/almacen/productos");
      setProductos(data);
    } catch (err) {
      setError(
        isAxiosError(err)
          ? (err.response?.data as { error?: string })?.error ?? `Error ${err.response?.status ?? ""}`
          : "Error inesperado.",
      );
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    cargar();
  }, [cargar]);

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/40">
      <header className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
        <h3 className="text-sm font-semibold text-slate-200">
          Inventario actual{!cargando && ` · ${productos.length}`}
        </h3>
        <button
          onClick={cargar}
          disabled={cargando}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 transition hover:border-sky-700 hover:text-sky-300 disabled:opacity-50"
        >
          {cargando ? "Cargando…" : "↻ Refrescar"}
        </button>
      </header>

      {error ? (
        <p className="px-5 py-6 text-sm text-red-300">{error}</p>
      ) : cargando ? (
        <p className="px-5 py-6 text-sm text-slate-500">Cargando inventario…</p>
      ) : productos.length === 0 ? (
        <p className="px-5 py-6 text-sm text-slate-500">
          Sin productos aún. Registra uno con el formulario de abajo.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-500">
              <tr className="border-b border-slate-800">
                <th className="px-5 py-2.5 font-medium">Código</th>
                <th className="px-5 py-2.5 font-medium">Nombre</th>
                <th className="px-5 py-2.5 font-medium">Categoría</th>
                <th className="px-5 py-2.5 font-medium">Sede</th>
                <th className="px-5 py-2.5 text-right font-medium">Disponible</th>
                <th className="px-5 py-2.5 text-right font-medium">Reservado</th>
              </tr>
            </thead>
            <tbody>
              {productos.map((p) => (
                <tr key={`${p.sede}-${p.codigo}`} className="border-b border-slate-800/60 last:border-0">
                  <td className="px-5 py-2.5 font-mono text-xs text-sky-300">{p.codigo}</td>
                  <td className="px-5 py-2.5 text-slate-200">{p.nombre}</td>
                  <td className="px-5 py-2.5 text-slate-400">{p.categoria}</td>
                  <td className="px-5 py-2.5 text-slate-400">{p.sede}</td>
                  <td className="px-5 py-2.5 text-right font-semibold text-emerald-300">{p.stock_disponible}</td>
                  <td className="px-5 py-2.5 text-right text-amber-300">{p.stock_reservado}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { isAxiosError } from "axios";
import { api } from "@/lib/api/client";
import { Boton, Feedback, extraerError, type Estado } from "@/components/ui/FormControls";
import type { TicketPendiente, DiagnosticoResponse, ProductoInventario } from "@/lib/types/backend";

const PRIORIDAD_COLOR: Record<string, string> = {
  ALTA: "bg-red-500/15 text-red-300",
  MEDIA: "bg-amber-500/15 text-amber-300",
  BAJA: "bg-slate-500/15 text-slate-300",
};

const money = (n: number) => `S/. ${n.toFixed(2)}`;

interface RepuestoSel {
  codigo_repuesto: string;
  nombre: string;
  cantidad: number;
  precio_unitario: number;
  stock: number;
}

/**
 * Bandeja del técnico (rol TECNICO). Buscador/autocomplete de repuestos (soporta
 * inventario grande) + calculadora en vivo: Precio Reparación = Repuestos + Mano de Obra.
 */
export default function DiagnosticoView() {
  const [tickets, setTickets] = useState<TicketPendiente[]>([]);
  const [productos, setProductos] = useState<ProductoInventario[]>([]);
  const [cargando, setCargando] = useState(true);
  const [errorLista, setErrorLista] = useState<string | null>(null);
  const [sel, setSel] = useState<TicketPendiente | null>(null);
  const [estado, setEstado] = useState<Estado>({ tipo: "idle" });
  const [enviando, setEnviando] = useState(false);

  const [repuestos, setRepuestos] = useState<RepuestoSel[]>([]);
  const [busqueda, setBusqueda] = useState("");
  const [manoObra, setManoObra] = useState<number>(0);

  const cargar = useCallback(async () => {
    setCargando(true);
    setErrorLista(null);
    try {
      const [tk, pr] = await Promise.all([
        api.get<TicketPendiente[]>("/tickets/pendientes"),
        api.get<ProductoInventario[]>("/almacen/productos"),
      ]);
      setTickets(tk.data);
      setProductos(pr.data);
    } catch (err) {
      setErrorLista(
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

  const productosSede = useMemo(
    () => (sel ? productos.filter((p) => p.sede === sel.sede) : []),
    [productos, sel],
  );

  // Autocomplete: hasta 8 coincidencias por código o nombre que aún no estén agregadas.
  const sugerencias = useMemo(() => {
    const s = busqueda.trim().toLowerCase();
    if (!s) return [];
    const yaAgregados = new Set(repuestos.map((r) => r.codigo_repuesto));
    return productosSede
      .filter(
        (p) =>
          !yaAgregados.has(p.codigo) &&
          (p.codigo.toLowerCase().includes(s) || p.nombre.toLowerCase().includes(s)),
      )
      .slice(0, 8);
  }, [busqueda, productosSede, repuestos]);

  // Desglose dinámico en vivo.
  const totalRepuestos = useMemo(
    () => repuestos.reduce((acc, r) => acc + r.cantidad * r.precio_unitario, 0),
    [repuestos],
  );
  const precioReparacion = totalRepuestos + (Number(manoObra) || 0);

  function seleccionarTicket(t: TicketPendiente) {
    setSel(t);
    setEstado({ tipo: "idle" });
    setRepuestos([]);
    setBusqueda("");
    setManoObra(0);
  }

  function agregarProducto(p: ProductoInventario) {
    if (p.stock_disponible === 0) return;
    setRepuestos((prev) => [
      ...prev,
      { codigo_repuesto: p.codigo, nombre: p.nombre, cantidad: 1, precio_unitario: p.precio_unitario, stock: p.stock_disponible },
    ]);
    setBusqueda("");
  }

  function cambiarCantidad(codigo: string, cantidad: number) {
    setRepuestos((prev) =>
      prev.map((r) =>
        r.codigo_repuesto === codigo ? { ...r, cantidad: Math.max(1, Math.min(cantidad, r.stock)) } : r,
      ),
    );
  }

  function quitarRepuesto(codigo: string) {
    setRepuestos((prev) => prev.filter((r) => r.codigo_repuesto !== codigo));
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!sel) return;
    setEnviando(true);
    setEstado({ tipo: "idle" });
    const fd = new FormData(e.currentTarget);
    try {
      const { data } = await api.post<DiagnosticoResponse>("/diagnosticos", {
        idTicket: sel.id,
        fallaDetectada: String(fd.get("fallaDetectada")),
        mano_obra: Number(manoObra) || 0,
        precio_reparacion: precioReparacion,
        repuestos: repuestos.map((r) => ({
          codigo_repuesto: r.codigo_repuesto,
          cantidad: r.cantidad,
          precio_unitario: r.precio_unitario,
          descripcion: r.nombre,
        })),
      });
      setEstado({
        tipo: "ok",
        mensaje: `✅ ${data.idDiagnostico} · total ${money(data.precioReparacion)} · ${data.repuestosDescontados} repuesto(s) · ${data.estadoReserva}`,
      });
      setSel(null);
      setRepuestos([]);
      cargar();
    } catch (err) {
      setEstado({ tipo: "error", mensaje: extraerError(err) });
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
      {/* Columna izquierda: bandeja */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40">
        <header className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-200">En cola{!cargando && ` · ${tickets.length}`}</h3>
          <button
            onClick={cargar}
            disabled={cargando}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 transition hover:border-cyan-700 hover:text-cyan-300 disabled:opacity-50"
          >
            {cargando ? "…" : "↻"}
          </button>
        </header>

        <div className="max-h-[70vh] overflow-y-auto p-3">
          {errorLista ? (
            <p className="px-2 py-4 text-sm text-red-300">{errorLista}</p>
          ) : cargando ? (
            <p className="px-2 py-4 text-sm text-slate-500">Cargando bandeja…</p>
          ) : tickets.length === 0 ? (
            <p className="px-2 py-4 text-sm text-slate-500">No hay tickets en cola. 🎉</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {tickets.map((t) => {
                const activo = sel?.id === t.id;
                return (
                  <li key={t.id}>
                    <button
                      onClick={() => seleccionarTicket(t)}
                      className={`w-full rounded-lg border p-3 text-left transition ${
                        activo ? "border-cyan-600 bg-cyan-600/10" : "border-slate-800 bg-slate-950/50 hover:border-slate-700"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-xs text-cyan-300">{t.id}</span>
                        <span className={`rounded px-2 py-0.5 text-[10px] font-medium ${PRIORIDAD_COLOR[t.prioridad] ?? PRIORIDAD_COLOR.BAJA}`}>
                          {t.prioridad}
                        </span>
                      </div>
                      <p className="mt-1 truncate text-sm text-slate-200">{t.datos_cliente}</p>
                      <p className="truncate text-xs text-slate-500">{t.equipo ?? t.datos_equipo ?? "—"} · {t.sede}</p>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </section>

      {/* Columna derecha: diagnóstico */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
        {!sel ? (
          <div className="flex h-full min-h-[200px] items-center justify-center text-center">
            <p className="text-sm text-slate-500">← Selecciona un ticket de la bandeja para diagnosticarlo.</p>
          </div>
        ) : (
          <>
            <div className="mb-5 border-b border-slate-800 pb-4">
              <h3 className="text-base font-semibold text-white">
                Diagnosticar <span className="font-mono text-cyan-300">{sel.id}</span>
              </h3>
              <p className="mt-1 text-sm text-slate-400">
                {sel.datos_cliente} · {sel.equipo ?? sel.datos_equipo ?? "sin equipo"} · sede {sel.sede}
              </p>
            </div>

            <form onSubmit={onSubmit} className="flex flex-col gap-4">
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-slate-300">Falla detectada</span>
                <textarea
                  name="fallaDetectada"
                  required
                  rows={2}
                  placeholder="Ej. No enciende; fuente de poder dañada."
                  className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 placeholder:text-slate-600 outline-none focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/30"
                />
              </label>

              {/* Buscador / autocomplete de repuestos */}
              <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4">
                <p className="mb-2 text-sm font-medium text-slate-300">Repuestos (descuentan stock de {sel.sede})</p>
                <div className="relative">
                  <input
                    value={busqueda}
                    onChange={(e) => setBusqueda(e.target.value)}
                    placeholder="🔍 Buscar repuesto por código o nombre…"
                    className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 outline-none focus:border-cyan-500"
                  />
                  {sugerencias.length > 0 && (
                    <ul className="absolute z-10 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-slate-700 bg-slate-900 shadow-xl">
                      {sugerencias.map((p) => (
                        <li key={p.codigo}>
                          <button
                            type="button"
                            onClick={() => agregarProducto(p)}
                            disabled={p.stock_disponible === 0}
                            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-slate-800 disabled:opacity-40"
                          >
                            <span className="text-slate-200">
                              <span className="font-mono text-xs text-cyan-300">{p.codigo}</span> · {p.nombre}
                            </span>
                            <span className="shrink-0 text-xs text-slate-400">
                              {money(p.precio_unitario)} · stock {p.stock_disponible}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {productosSede.length === 0 && (
                  <p className="mt-2 text-xs text-slate-500">No hay productos en el almacén de {sel.sede}.</p>
                )}

                {repuestos.length > 0 && (
                  <ul className="mt-3 flex flex-col gap-1.5">
                    {repuestos.map((r) => (
                      <li key={r.codigo_repuesto} className="flex items-center gap-2 rounded-md bg-slate-900 px-3 py-1.5 text-sm">
                        <span className="flex-1 truncate text-slate-200">
                          <span className="font-mono text-xs text-cyan-300">{r.codigo_repuesto}</span> · {r.nombre}
                        </span>
                        <input
                          type="number"
                          min={1}
                          max={r.stock}
                          value={r.cantidad}
                          onChange={(e) => cambiarCantidad(r.codigo_repuesto, Number(e.target.value))}
                          className="w-14 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-center text-xs text-slate-100 outline-none focus:border-cyan-500"
                        />
                        <span className="w-20 text-right text-xs text-slate-300">{money(r.cantidad * r.precio_unitario)}</span>
                        <button
                          type="button"
                          onClick={() => quitarRepuesto(r.codigo_repuesto)}
                          className="text-xs text-red-400 hover:text-red-300"
                        >
                          ✕
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Calculadora en vivo */}
              <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-400">Repuestos ({repuestos.length})</span>
                  <span className="font-medium text-slate-200">{money(totalRepuestos)}</span>
                </div>
                <div className="mt-2 flex items-center justify-between gap-3 text-sm">
                  <span className="text-slate-400">Mano de obra (S/.)</span>
                  <input
                    type="number"
                    min={0}
                    step="0.01"
                    value={manoObra}
                    onChange={(e) => setManoObra(Number(e.target.value))}
                    className="w-28 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-right text-slate-100 outline-none focus:border-cyan-500"
                  />
                </div>
                <div className="mt-3 flex items-center justify-between border-t border-slate-800 pt-3">
                  <span className="text-sm font-medium text-slate-300">Precio Reparación</span>
                  <span className="text-xl font-bold text-cyan-300">{money(precioReparacion)}</span>
                </div>
              </div>

              <Boton cargando={enviando}>Registrar diagnóstico</Boton>
              <Feedback estado={estado} />
            </form>
          </>
        )}
      </section>
    </div>
  );
}

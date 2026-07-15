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

interface RepuestoSel {
  codigo_repuesto: string;
  nombre: string;
  cantidad: number;
}

/**
 * Bandeja del técnico (rol TECNICO). GET de tickets EN_COLA + POST de diagnóstico
 * con precio y ARRAY de repuestos. Los repuestos se buscan consumiendo el GET de
 * almacén (filtrado por la sede del ticket); si un producto tiene stock 0, se
 * deshabilita.
 */
export default function DiagnosticoView() {
  const [tickets, setTickets] = useState<TicketPendiente[]>([]);
  const [productos, setProductos] = useState<ProductoInventario[]>([]);
  const [cargando, setCargando] = useState(true);
  const [errorLista, setErrorLista] = useState<string | null>(null);
  const [sel, setSel] = useState<TicketPendiente | null>(null);
  const [estado, setEstado] = useState<Estado>({ tipo: "idle" });
  const [enviando, setEnviando] = useState(false);

  // Repuestos elegidos + estado del picker.
  const [repuestos, setRepuestos] = useState<RepuestoSel[]>([]);
  const [codigoSel, setCodigoSel] = useState("");
  const [cantSel, setCantSel] = useState(1);

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

  // Productos disponibles en la sede del ticket seleccionado.
  const productosSede = useMemo(
    () => (sel ? productos.filter((p) => p.sede === sel.sede) : []),
    [productos, sel],
  );

  function seleccionarTicket(t: TicketPendiente) {
    setSel(t);
    setEstado({ tipo: "idle" });
    setRepuestos([]);
    setCodigoSel("");
    setCantSel(1);
  }

  function agregarRepuesto() {
    const prod = productosSede.find((p) => p.codigo === codigoSel);
    if (!prod) return;
    if (cantSel < 1 || cantSel > prod.stock_disponible) return;
    setRepuestos((prev) => {
      const existente = prev.find((r) => r.codigo_repuesto === prod.codigo);
      if (existente) {
        return prev.map((r) =>
          r.codigo_repuesto === prod.codigo
            ? { ...r, cantidad: Math.min(r.cantidad + cantSel, prod.stock_disponible) }
            : r,
        );
      }
      return [...prev, { codigo_repuesto: prod.codigo, nombre: prod.nombre, cantidad: cantSel }];
    });
    setCodigoSel("");
    setCantSel(1);
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
        precio_reparacion: Number(fd.get("precio_reparacion") ?? 0),
        repuestos: repuestos.map((r) => ({ codigo_repuesto: r.codigo_repuesto, cantidad: r.cantidad })),
      });
      setEstado({
        tipo: "ok",
        mensaje: `✅ ${data.idDiagnostico} · S/. ${data.precioReparacion} · ${data.repuestosDescontados} repuesto(s) descontado(s) · ${data.estadoReserva}`,
      });
      setSel(null);
      setRepuestos([]);
      cargar(); // refresca bandeja (el ticket sale) y stock
    } catch (err) {
      setEstado({ tipo: "error", mensaje: extraerError(err) });
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
      {/* Columna izquierda: bandeja de pendientes */}
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
                      <p className="truncate text-xs text-slate-500">{t.datos_equipo ?? "—"} · {t.sede}</p>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </section>

      {/* Columna derecha: formulario de diagnóstico */}
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
                {sel.datos_cliente} · {sel.datos_equipo ?? "sin equipo"} · sede {sel.sede}
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

              <label className="flex max-w-[200px] flex-col gap-1 text-sm">
                <span className="font-medium text-slate-300">Precio reparación (S/.)</span>
                <input
                  name="precio_reparacion"
                  type="number"
                  min={0}
                  step="0.01"
                  defaultValue={0}
                  className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/30"
                />
              </label>

              {/* Buscador dinámico de repuestos */}
              <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4">
                <p className="mb-3 text-sm font-medium text-slate-300">Repuestos (descuentan stock de {sel.sede})</p>

                <div className="flex flex-wrap items-end gap-2">
                  <label className="flex flex-1 flex-col gap-1 text-xs">
                    <span className="text-slate-400">Producto</span>
                    <select
                      value={codigoSel}
                      onChange={(e) => setCodigoSel(e.target.value)}
                      className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-500"
                    >
                      <option value="">— elegir —</option>
                      {productosSede.map((p) => (
                        <option key={p.codigo} value={p.codigo} disabled={p.stock_disponible === 0}>
                          {p.codigo} · {p.nombre} (stock {p.stock_disponible})
                          {p.stock_disponible === 0 ? " — SIN STOCK" : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex w-20 flex-col gap-1 text-xs">
                    <span className="text-slate-400">Cant.</span>
                    <input
                      type="number"
                      min={1}
                      value={cantSel}
                      onChange={(e) => setCantSel(Number(e.target.value))}
                      className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-500"
                    />
                  </label>
                  <button
                    type="button"
                    onClick={agregarRepuesto}
                    disabled={!codigoSel}
                    className="rounded-lg border border-cyan-700 px-3 py-2 text-sm text-cyan-300 transition hover:bg-cyan-600/10 disabled:opacity-40"
                  >
                    + Agregar
                  </button>
                </div>

                {productosSede.length === 0 && (
                  <p className="mt-2 text-xs text-slate-500">No hay productos en el almacén de {sel.sede}.</p>
                )}

                {repuestos.length > 0 && (
                  <ul className="mt-3 flex flex-col gap-1.5">
                    {repuestos.map((r) => (
                      <li key={r.codigo_repuesto} className="flex items-center justify-between rounded-md bg-slate-900 px-3 py-1.5 text-sm">
                        <span className="text-slate-200">
                          <span className="font-mono text-xs text-cyan-300">{r.codigo_repuesto}</span> · {r.nombre} × {r.cantidad}
                        </span>
                        <button
                          type="button"
                          onClick={() => quitarRepuesto(r.codigo_repuesto)}
                          className="text-xs text-red-400 hover:text-red-300"
                        >
                          Quitar
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
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

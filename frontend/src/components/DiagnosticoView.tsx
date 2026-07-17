"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { isAxiosError } from "axios";
import { api } from "@/lib/api/client";
import { fechaHora } from "@/lib/fecha";
import { Boton, Feedback, extraerError, type Estado } from "@/components/ui/FormControls";
import type { TicketPendiente, DiagnosticoResponse, ProductoInventario, Asignacion } from "@/lib/types/backend";

const PRIORIDAD_COLOR: Record<string, string> = {
  ALTA: "bg-red-500/15 text-red-300",
  MEDIA: "bg-amber-500/15 text-amber-300",
  BAJA: "bg-slate-500/15 text-slate-300",
};

const money = (n: number) => `S/. ${n.toFixed(2)}`;

// Orden de la cola: primero por prioridad (ALTA arriba), luego por fecha desc.
const RANK_PRIORIDAD: Record<string, number> = { ALTA: 0, MEDIA: 1, BAJA: 2 };
function ordenarCola(a: TicketPendiente, b: TicketPendiente): number {
  const pr = (RANK_PRIORIDAD[a.prioridad] ?? 9) - (RANK_PRIORIDAD[b.prioridad] ?? 9);
  if (pr !== 0) return pr;
  return new Date(b.fecha_registro).getTime() - new Date(a.fecha_registro).getTime();
}

interface RepuestoSel {
  codigo_repuesto: string;
  nombre: string;
  cantidad: number;
  precio_unitario: number;
  stock: number;
}

/**
 * Bandeja del técnico (rol TECNICO). Dos apartados:
 *  - "Cola disponible": tickets EN_COLA de SU sede que aún nadie tomó. Botón "Tomar".
 *  - "Mis Tickets": los que el técnico ya tomó — los sirve el diagnostico-service,
 *    así que siguen visibles aunque el ticket-service esté caído (resiliencia).
 * Solo se puede diagnosticar un ticket que YA tomaste (queda solo para ti).
 */
export default function DiagnosticoView({ sede }: { sede: string }) {
  const [disponibles, setDisponibles] = useState<TicketPendiente[]>([]);
  const [misTickets, setMisTickets] = useState<Asignacion[]>([]);
  const [productos, setProductos] = useState<ProductoInventario[]>([]);
  // Flags de carga SEPARADOS: "Mis Tickets" (diagnostico) se pinta en cuanto
  // llega, sin esperar a la cola (ticket-service), que puede estar caída/lenta.
  const [cargandoMis, setCargandoMis] = useState(true);
  const [cargandoCola, setCargandoCola] = useState(true);
  const [errorCola, setErrorCola] = useState<string | null>(null);   // cola disponible (ticket-service)
  const [errorMis, setErrorMis] = useState<string | null>(null);     // mis tickets (diagnostico)
  const [tomandoId, setTomandoId] = useState<string | null>(null);
  const [avisoTomar, setAvisoTomar] = useState<Estado>({ tipo: "idle" });

  const [sel, setSel] = useState<Asignacion | null>(null);
  const [estado, setEstado] = useState<Estado>({ tipo: "idle" });
  const [enviando, setEnviando] = useState(false);

  const [repuestos, setRepuestos] = useState<RepuestoSel[]>([]);
  const [busqueda, setBusqueda] = useState("");
  const [manoObra, setManoObra] = useState<number>(0);

  // "Mis Tickets" es lo crítico: se carga por separado para que una caída del
  // ticket-service (cola disponible) NO impida ver ni trabajar tus tickets.
  const cargarMisTickets = useCallback(async () => {
    setErrorMis(null);
    try {
      const { data } = await api.get<Asignacion[]>("/diagnosticos/asignaciones/mias");
      setMisTickets(data);
    } catch (err) {
      setErrorMis(
        isAxiosError(err)
          ? (err.response?.data as { error?: string })?.error ?? `Error ${err.response?.status ?? ""}`
          : "No se pudieron cargar tus tickets.",
      );
    } finally {
      setCargandoMis(false);
    }
  }, []);

  const cargarCola = useCallback(async () => {
    setErrorCola(null);
    try {
      const { data } = await api.get<TicketPendiente[]>("/tickets/pendientes");
      // Solo la cola de MI sede (un técnico no atiende otra sede).
      setDisponibles(data.filter((t) => t.sede === sede).sort(ordenarCola));
    } catch (err) {
      setErrorCola(
        isAxiosError(err)
          ? (err.response?.data as { error?: string })?.error ?? `Error ${err.response?.status ?? ""}`
          : "La cola no está disponible ahora mismo.",
      );
    } finally {
      setCargandoCola(false);
    }
  }, [sede]);

  const cargarProductos = useCallback(async () => {
    try {
      const { data } = await api.get<ProductoInventario[]>("/almacen/productos");
      setProductos(data);
    } catch {
      /* el almacén se reintenta al diagnosticar; no bloquea la bandeja */
    }
  }, []);

  useEffect(() => {
    // Cada fuente se dispara por su cuenta: "Mis Tickets" NO espera a la cola.
    cargarMisTickets();
    cargarCola();
    cargarProductos();
  }, [cargarMisTickets, cargarCola, cargarProductos]);

  // IDs que ya tomé: para no ofrecer "Tomar" sobre algo que ya es mío.
  const idsMios = useMemo(() => new Set(misTickets.map((a) => a.id_ticket)), [misTickets]);
  const colaFiltrada = useMemo(
    () => disponibles.filter((t) => !idsMios.has(t.id)),
    [disponibles, idsMios],
  );

  const productosSede = useMemo(
    () => (sel ? productos.filter((p) => p.sede === sel.sede) : []),
    [productos, sel],
  );

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

  const totalRepuestos = useMemo(
    () => repuestos.reduce((acc, r) => acc + r.cantidad * r.precio_unitario, 0),
    [repuestos],
  );
  const precioReparacion = totalRepuestos + (Number(manoObra) || 0);

  async function tomar(t: TicketPendiente) {
    setTomandoId(t.id);
    setAvisoTomar({ tipo: "idle" });
    try {
      await api.post("/diagnosticos/asignaciones/tomar", {
        id_ticket: t.id,
        datos_cliente: t.datos_cliente,
        documento_cliente: t.documento_cliente,
        telefono_cliente: t.telefono_cliente,
        tipo_operacion: t.tipo_operacion,
        equipo: t.equipo ?? t.datos_equipo,
        numero_serie: t.numero_serie,
        caracteristicas_falla: t.caracteristicas_falla,
        prioridad: t.prioridad,
      });
      setAvisoTomar({ tipo: "ok", mensaje: `✅ Tomaste ${t.id}. Ya es tuyo y aparece en "Mis Tickets".` });
      await Promise.allSettled([cargarMisTickets(), cargarCola()]);
    } catch (err) {
      // 409 = otro técnico lo tomó primero: mensaje claro, no error feo.
      setAvisoTomar({ tipo: "error", mensaje: extraerError(err) });
      cargarCola();
    } finally {
      setTomandoId(null);
    }
  }

  function seleccionarParaDiagnosticar(a: Asignacion) {
    if (a.estado === "DIAGNOSTICADO") return; // ya tiene diagnóstico
    setSel(a);
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
        idTicket: sel.id_ticket,
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
      cargarMisTickets();
    } catch (err) {
      setEstado({ tipo: "error", mensaje: extraerError(err) });
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
      {/* Columna izquierda: Mis Tickets + Cola disponible */}
      <div className="flex flex-col gap-6">
        {/* MIS TICKETS (los sirve diagnostico-service: resiliente a caída de tickets) */}
        <section className="rounded-xl border border-cyan-900/50 bg-cyan-950/10">
          <header className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
            <h3 className="text-sm font-semibold text-cyan-200">
              Mis Tickets{!cargandoMis && ` · ${misTickets.length}`}
            </h3>
            <button
              onClick={cargarMisTickets}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 transition hover:border-cyan-700 hover:text-cyan-300"
            >
              ↻
            </button>
          </header>
          <div className="max-h-[38vh] overflow-y-auto p-3">
            {errorMis ? (
              <p className="px-2 py-4 text-sm text-red-300">{errorMis}</p>
            ) : cargandoMis ? (
              <p className="px-2 py-4 text-sm text-slate-500">Cargando…</p>
            ) : misTickets.length === 0 ? (
              <p className="px-2 py-4 text-sm text-slate-500">Aún no has tomado ningún ticket.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {misTickets.map((a) => {
                  const activo = sel?.id_ticket === a.id_ticket;
                  const diagnosticado = a.estado === "DIAGNOSTICADO";
                  return (
                    <li key={a.id_ticket}>
                      <button
                        onClick={() => seleccionarParaDiagnosticar(a)}
                        disabled={diagnosticado}
                        className={`w-full rounded-lg border p-3 text-left transition ${
                          activo
                            ? "border-cyan-600 bg-cyan-600/10"
                            : "border-slate-800 bg-slate-950/50 hover:border-slate-700"
                        } ${diagnosticado ? "opacity-60" : ""}`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-xs text-cyan-300">{a.id_ticket}</span>
                          <span
                            className={`rounded px-2 py-0.5 text-[10px] font-medium ${
                              diagnosticado ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/15 text-amber-300"
                            }`}
                          >
                            {diagnosticado ? "DIAGNOSTICADO" : "TOMADO"}
                          </span>
                        </div>
                        <p className="mt-1 truncate text-sm text-slate-200">{a.datos_cliente ?? "—"}</p>
                        <p className="truncate text-xs text-slate-500">
                          {a.equipo ?? "—"} · {a.sede} · {fechaHora(a.fecha_tomado)}
                        </p>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </section>

        {/* COLA DISPONIBLE (ticket-service). Botón Tomar por ticket. */}
        <section className="rounded-xl border border-slate-800 bg-slate-900/40">
          <header className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
            <h3 className="text-sm font-semibold text-slate-200">
              Cola disponible · {sede}{!cargandoCola && ` · ${colaFiltrada.length}`}
            </h3>
            <button
              onClick={cargarCola}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 transition hover:border-cyan-700 hover:text-cyan-300"
            >
              ↻
            </button>
          </header>
          <div className="p-3">
            <Feedback estado={avisoTomar} />
            <div className="mt-1 max-h-[40vh] overflow-y-auto">
              {errorCola ? (
                <p className="rounded-lg border border-amber-900/50 bg-amber-950/20 px-3 py-3 text-sm text-amber-300">
                  {errorCola} Tus tickets ya tomados siguen disponibles arriba.
                </p>
              ) : cargandoCola ? (
                <p className="px-2 py-4 text-sm text-slate-500">Cargando cola…</p>
              ) : colaFiltrada.length === 0 ? (
                <p className="px-2 py-4 text-sm text-slate-500">No hay tickets libres en {sede}. 🎉</p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {colaFiltrada.map((t) => (
                    <li key={t.id} className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-xs text-cyan-300">{t.id}</span>
                        <span className={`rounded px-2 py-0.5 text-[10px] font-medium ${PRIORIDAD_COLOR[t.prioridad] ?? PRIORIDAD_COLOR.BAJA}`}>
                          {t.prioridad}
                        </span>
                      </div>
                      <p className="mt-1 truncate text-sm text-slate-200">{t.datos_cliente}</p>
                      <p className="truncate text-xs text-slate-500">{t.equipo ?? t.datos_equipo ?? "—"}</p>
                      <button
                        onClick={() => tomar(t)}
                        disabled={tomandoId === t.id}
                        className="mt-2 w-full rounded-lg bg-cyan-600/90 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-500 disabled:opacity-50"
                      >
                        {tomandoId === t.id ? "Tomando…" : "Tomar ticket"}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </section>
      </div>

      {/* Columna derecha: diagnóstico del ticket seleccionado (de Mis Tickets) */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
        {!sel ? (
          <div className="flex h-full min-h-[200px] items-center justify-center text-center">
            <p className="text-sm text-slate-500">
              Toma un ticket de la cola y luego selecciónalo en <b className="text-cyan-300">Mis Tickets</b> para diagnosticarlo.
            </p>
          </div>
        ) : (
          <>
            <div className="mb-5 border-b border-slate-800 pb-4">
              <h3 className="text-base font-semibold text-white">
                Diagnosticar <span className="font-mono text-cyan-300">{sel.id_ticket}</span>
              </h3>
              <p className="mt-1 text-sm text-slate-400">
                {sel.datos_cliente ?? "—"} · {sel.equipo ?? "sin equipo"} · sede {sel.sede}
              </p>
              {sel.caracteristicas_falla ? (
                <p className="mt-1 text-xs text-slate-500">Falla reportada: {sel.caracteristicas_falla}</p>
              ) : null}
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
                  <p className="mt-2 text-xs text-slate-500">No hay productos en el almacén de {sel.sede} (o el almacén no respondió).</p>
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

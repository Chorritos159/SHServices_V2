"use client";

import { useCallback, useEffect, useState } from "react";
import { isAxiosError } from "axios";
import { api } from "@/lib/api/client";
import type { TicketPendiente } from "@/lib/types/backend";
import CobroModal from "@/components/CobroModal";
import ComprobanteModal, { type ComprobanteData } from "@/components/print/ComprobanteModal";

/**
 * Bandeja de Entregas y Cobros (rol CAJA). Lista tickets DIAGNOSTICADO listos
 * para cobrar. "Cobrar y Entregar" → modal de cobro → comprobante imprimible.
 */
export default function EntregasView() {
  const [tickets, setTickets] = useState<TicketPendiente[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cobrar, setCobrar] = useState<TicketPendiente | null>(null);
  const [comprobante, setComprobante] = useState<ComprobanteData | null>(null);

  const cargar = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const { data } = await api.get<TicketPendiente[]>("/tickets/por-estado/DIAGNOSTICADO");
      setTickets(data);
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

  async function rechazar(t: TicketPendiente) {
    if (!window.confirm(`¿Rechazar el presupuesto de ${t.id}? Se liberará el stock reservado.`)) return;
    try {
      await api.post(`/tickets/${t.id}/rechazar`);
      cargar();
    } catch {
      window.alert("No se pudo rechazar el ticket.");
    }
  }

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/40">
      <header className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
        <h3 className="text-sm font-semibold text-slate-200">
          Listos para cobrar (DIAGNOSTICADO){!cargando && ` · ${tickets.length}`}
        </h3>
        <button
          onClick={cargar}
          disabled={cargando}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 transition hover:border-amber-700 hover:text-amber-300 disabled:opacity-50"
        >
          {cargando ? "Cargando…" : "↻ Refrescar"}
        </button>
      </header>

      {error ? (
        <p className="px-5 py-6 text-sm text-red-300">{error}</p>
      ) : cargando ? (
        <p className="px-5 py-6 text-sm text-slate-500">Cargando bandeja…</p>
      ) : tickets.length === 0 ? (
        <p className="px-5 py-6 text-sm text-slate-500">No hay tickets diagnosticados pendientes de cobro.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-500">
              <tr className="border-b border-slate-800">
                <th className="px-5 py-2.5 font-medium">Ticket</th>
                <th className="px-5 py-2.5 font-medium">Cliente</th>
                <th className="px-5 py-2.5 font-medium">Equipo</th>
                <th className="px-5 py-2.5 text-right font-medium">Estimado</th>
                <th className="px-5 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {tickets.map((t) => (
                <tr key={t.id} className="border-b border-slate-800/60 last:border-0">
                  <td className="px-5 py-2.5 font-mono text-xs text-amber-300">{t.id}</td>
                  <td className="px-5 py-2.5 text-slate-200">{t.datos_cliente}</td>
                  <td className="px-5 py-2.5 text-slate-400">{t.equipo ?? t.datos_equipo ?? "—"}</td>
                  <td className="px-5 py-2.5 text-right text-slate-300">
                    {t.precio_estimado != null ? `S/. ${t.precio_estimado.toFixed(2)}` : "—"}
                  </td>
                  <td className="px-5 py-2.5 text-right">
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => rechazar(t)}
                        className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 transition hover:border-red-800 hover:text-red-300"
                      >
                        Rechazar
                      </button>
                      <button
                        onClick={() => setCobrar(t)}
                        className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-500"
                      >
                        Cobrar y Entregar
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {cobrar && (
        <CobroModal
          ticket={cobrar}
          onClose={() => setCobrar(null)}
          onDone={(comp) => {
            setCobrar(null);
            setComprobante(comp);
            cargar(); // el ticket ya está ENTREGADO → sale de la bandeja
          }}
        />
      )}

      {comprobante && <ComprobanteModal data={comprobante} onClose={() => setComprobante(null)} />}
    </section>
  );
}

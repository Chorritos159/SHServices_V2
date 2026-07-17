"use client";

import { useCallback, useEffect, useState } from "react";
import { isAxiosError } from "axios";
import { api } from "@/lib/api/client";
import { fechaHora } from "@/lib/fecha";
import type { EventoAuditoria } from "@/lib/types/backend";

/**
 * Tabla de la traza de auditoría. Navegador → Axios BFF (/api/auditoria/eventos)
 * → Gateway → GET /api/v1/auditoria/eventos.
 */
export default function EventosTable() {
  const [eventos, setEventos] = useState<EventoAuditoria[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const { data } = await api.get<EventoAuditoria[]>("/auditoria/eventos");
      setEventos(data);
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
          Eventos auditados{!cargando && ` · ${eventos.length}`}
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
        <p className="px-5 py-6 text-sm text-slate-500">Cargando traza…</p>
      ) : eventos.length === 0 ? (
        <p className="px-5 py-6 text-sm text-slate-500">
          Sin eventos aún. Crea o factura un ticket en el panel de operador y refresca.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-500">
              <tr className="border-b border-slate-800">
                <th className="px-5 py-2.5 font-medium">Fecha (UTC)</th>
                <th className="px-5 py-2.5 font-medium">Evento</th>
                <th className="px-5 py-2.5 font-medium">Sede</th>
                <th className="px-5 py-2.5 font-medium">ID Ticket</th>
                <th className="px-5 py-2.5 font-medium">Trace ID</th>
              </tr>
            </thead>
            <tbody>
              {eventos.map((e, i) => (
                <tr key={`${e.trace_id}-${i}`} className="border-b border-slate-800/60 last:border-0">
                  <td className="px-5 py-2.5 whitespace-nowrap text-xs text-slate-400">
                    {fechaHora(e.recibido_en)}
                  </td>
                  <td className="px-5 py-2.5">
                    <span className="rounded bg-sky-600/15 px-2 py-0.5 text-xs font-medium text-sky-300">
                      {e.evento ?? "—"}
                    </span>
                  </td>
                  <td className="px-5 py-2.5 text-slate-300">{e.sede ?? "—"}</td>
                  <td className="px-5 py-2.5 font-mono text-xs text-slate-300">{e.idTicket ?? "—"}</td>
                  <td className="px-5 py-2.5 font-mono text-xs text-slate-500">{e.trace_id ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

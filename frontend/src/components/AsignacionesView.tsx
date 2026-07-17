"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { isAxiosError } from "axios";
import { api } from "@/lib/api/client";
import { fechaHora } from "@/lib/fecha";
import type { Asignacion } from "@/lib/types/backend";

const ESTADO_BADGE: Record<string, string> = {
  TOMADO: "bg-amber-500/15 text-amber-300",
  DIAGNOSTICADO: "bg-emerald-500/15 text-emerald-300",
};

/**
 * Vista de ADMIN: todos los tickets tomados y quién los atiende.
 * La sirve el diagnostico-service (dueño de las asignaciones), no el ticket-service.
 */
export default function AsignacionesView() {
  const [asignaciones, setAsignaciones] = useState<Asignacion[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");

  const cargar = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const { data } = await api.get<Asignacion[]>("/diagnosticos/asignaciones");
      setAsignaciones(data);
    } catch (err) {
      setError(
        isAxiosError(err)
          ? (err.response?.data as { error?: string })?.error ?? `Error ${err.response?.status ?? ""}`
          : "No se pudieron cargar las asignaciones.",
      );
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    cargar();
  }, [cargar]);

  const filtradas = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return asignaciones;
    return asignaciones.filter(
      (a) =>
        a.id_ticket.toLowerCase().includes(s) ||
        a.tecnico.toLowerCase().includes(s) ||
        a.sede.toLowerCase().includes(s) ||
        (a.datos_cliente ?? "").toLowerCase().includes(s),
    );
  }, [asignaciones, q]);

  // Resumen: cuántos tickets atiende cada técnico.
  const porTecnico = useMemo(() => {
    const m = new Map<string, number>();
    for (const a of asignaciones) m.set(a.tecnico, (m.get(a.tecnico) ?? 0) + 1);
    return [...m.entries()].sort((x, y) => y[1] - x[1]);
  }, [asignaciones]);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Buscar por ticket, técnico, sede o cliente…"
          className="w-full max-w-md rounded-lg border border-slate-700 bg-slate-950 px-3.5 py-2.5 text-slate-100 placeholder:text-slate-600 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30"
        />
        <button
          onClick={cargar}
          disabled={cargando}
          className="rounded-lg border border-slate-700 px-3 py-2.5 text-sm text-slate-300 transition hover:border-sky-700 hover:text-sky-300 disabled:opacity-50"
        >
          {cargando ? "Cargando…" : "↻ Refrescar"}
        </button>
        {!cargando && (
          <span className="text-sm text-slate-500">
            {filtradas.length} de {asignaciones.length} asignación(es)
          </span>
        )}
      </div>

      {/* Resumen por técnico */}
      {!cargando && !error && porTecnico.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {porTecnico.map(([tec, n]) => (
            <span key={tec} className="rounded-full border border-slate-700 bg-slate-900 px-3 py-1 text-xs text-slate-300">
              {tec}: <span className="font-semibold text-sky-300">{n}</span>
            </span>
          ))}
        </div>
      )}

      {error ? (
        <p className="rounded-lg border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-300">{error}</p>
      ) : cargando ? (
        <p className="text-sm text-slate-500">Cargando asignaciones…</p>
      ) : filtradas.length === 0 ? (
        <p className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-6 text-sm text-slate-500">
          {q ? `Sin resultados para "${q}".` : "Aún no hay tickets tomados por ningún técnico."}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-5 py-2.5 font-medium">Ticket</th>
                <th className="px-5 py-2.5 font-medium">Técnico</th>
                <th className="px-5 py-2.5 font-medium">Sede</th>
                <th className="px-5 py-2.5 font-medium">Cliente</th>
                <th className="px-5 py-2.5 font-medium">Equipo</th>
                <th className="px-5 py-2.5 font-medium">Estado</th>
                <th className="px-5 py-2.5 font-medium">Tomado</th>
              </tr>
            </thead>
            <tbody>
              {filtradas.map((a) => (
                <tr key={a.id_ticket} className="border-t border-slate-800/60">
                  <td className="px-5 py-2.5 font-mono text-xs text-cyan-300">{a.id_ticket}</td>
                  <td className="px-5 py-2.5 font-medium text-slate-200">{a.tecnico}</td>
                  <td className="px-5 py-2.5 text-slate-300">{a.sede}</td>
                  <td className="px-5 py-2.5 text-slate-300">{a.datos_cliente ?? "—"}</td>
                  <td className="px-5 py-2.5 text-slate-400">{a.equipo ?? "—"}</td>
                  <td className="px-5 py-2.5">
                    <span className={`rounded px-2 py-0.5 text-[10px] font-medium ${ESTADO_BADGE[a.estado] ?? "bg-slate-500/15 text-slate-300"}`}>
                      {a.estado}
                    </span>
                  </td>
                  <td className="px-5 py-2.5 whitespace-nowrap text-xs text-slate-400">{fechaHora(a.fecha_tomado)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

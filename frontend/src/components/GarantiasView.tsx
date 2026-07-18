"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { isAxiosError } from "axios";
import { api } from "@/lib/api/client";
import { soloFecha } from "@/lib/fecha";
import ComprobanteModal, { type ComprobanteData } from "@/components/print/ComprobanteModal";
import type { Garantia } from "@/lib/types/backend";

/**
 * Consulta de Garantías (CAJA y ADMIN). Busca por DNI/RUC o N° de serie y muestra
 * tarjetas con la vigencia: VIGENTE (verde) / VENCIDA (rojo), días restantes y los
 * datos de la reparación original.
 */
export default function GarantiasView() {
  const [garantias, setGarantias] = useState<Garantia[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  // Comprobante que respalda la garantia (se abre al hacer clic en una tarjeta).
  const [comprobante, setComprobante] = useState<ComprobanteData | null>(null);
  const [cargandoComp, setCargandoComp] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const { data } = await api.get<Garantia[]>("/garantias");
      setGarantias(data);
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

  async function verComprobante(g: Garantia) {
    setCargandoComp(g.id);
    setError(null);
    try {
      const { data } = await api.get<{
        idFactura: string; montoManoObra: number; montoRepuestos: number;
        montoTotal: number; fechaEmision: string; estadoPago: string;
        metodoPago?: string; garantiaVence?: string | null;
      }>(`/garantias/factura/${encodeURIComponent(g.id_ticket)}`);
      setComprobante({
        idFactura: data.idFactura,
        idTicket: g.id_ticket,
        cliente: g.documento_cliente ?? "—",
        documento: g.documento_cliente ?? "—",
        manoObra: data.montoManoObra ?? 0,
        repuestos: data.montoRepuestos ?? 0,
        total: data.montoTotal ?? (g.monto_total ?? 0),
        metodoPago: data.metodoPago ?? "—",
        estadoPago: data.estadoPago ?? "PAGADO",
        fecha: data.fechaEmision,
        garantiaVence: data.garantiaVence ?? g.fecha_vencimiento,
      });
    } catch (err) {
      setError(
        isAxiosError(err)
          ? (err.response?.data as { error?: string; detalle?: string })?.detalle ??
            (err.response?.data as { error?: string })?.error ??
            "No se pudo cargar el comprobante."
          : "No se pudo cargar el comprobante.",
      );
    } finally {
      setCargandoComp(null);
    }
  }

  const filtradas = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return garantias;
    return garantias.filter(
      (g) =>
        (g.documento_cliente ?? "").toLowerCase().includes(s) ||
        (g.numero_serie ?? "").toLowerCase().includes(s),
    );
  }, [garantias, q]);

  return (
    <div className="flex flex-col gap-5">
      {/* Buscador */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Buscar por DNI/RUC o N° de serie…"
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
            {filtradas.length} de {garantias.length} garantía(s)
          </span>
        )}
      </div>

      {error ? (
        <p className="rounded-lg border border-red-900/60 bg-red-950/40 px-4 py-3 text-sm text-red-300">{error}</p>
      ) : cargando ? (
        <p className="text-sm text-slate-500">Cargando garantías…</p>
      ) : filtradas.length === 0 ? (
        <p className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-6 text-sm text-slate-500">
          {q ? `Sin garantías para "${q}".` : "Aún no hay garantías registradas."}
        </p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {filtradas.map((g) => (
            <TarjetaGarantia
              key={g.id}
              g={g}
              onVerComprobante={() => verComprobante(g)}
              cargando={cargandoComp === g.id}
            />
          ))}
        </div>
      )}

      {comprobante && (
        <ComprobanteModal data={comprobante} onClose={() => setComprobante(null)} />
      )}
    </div>
  );
}

function TarjetaGarantia({
  g,
  onVerComprobante,
  cargando,
}: Readonly<{
  g: Garantia;
  onVerComprobante: () => void;
  cargando: boolean;
}>) {
  const color = g.vigente
    ? "border-emerald-800/60 bg-emerald-950/20"
    : "border-red-900/60 bg-red-950/20";
  const badge = g.vigente
    ? "bg-emerald-500/15 text-emerald-300"
    : "bg-red-500/15 text-red-300";

  // <div> y no <article>: a un elemento de contenido (landmark) no se le debe
  // encima el rol "button"; el <div> es genérico y sí lo admite.
  return (
    <div
      onClick={onVerComprobante}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        // Un role="button" real responde a Enter Y a Espacio.
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onVerComprobante();
        }
      }}
      title="Ver el comprobante de esta garantía"
      className={`cursor-pointer rounded-xl border p-5 transition hover:brightness-125 ${color}`}
    >
      <div className="mb-3 flex items-center justify-between">
        <span className="font-mono text-xs text-slate-400">{g.id}</span>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide ${badge}`}>
          {g.vigente ? "Vigente" : "Vencida"}
        </span>
      </div>

      <p className="text-sm text-slate-300">
        {g.vigente ? (
          <>
            <span className="text-lg font-bold text-emerald-300">{g.dias_restantes}</span> días restantes
          </>
        ) : (
          <span className="font-medium text-red-300">Garantía vencida</span>
        )}
      </p>

      <p className="mt-2 rounded-lg bg-slate-800/60 px-3 py-1.5 text-sm">
        <span className="text-slate-400">Monto cobrado: </span>
        <span className="font-bold text-white">
          {g.monto_total != null ? `S/. ${g.monto_total.toFixed(2)}` : "—"}
        </span>
      </p>

      <dl className="mt-3 space-y-1 border-t border-slate-800 pt-3 text-sm">
        <Fila k="DNI/RUC" v={g.documento_cliente ?? "—"} />
        <Fila k="Equipo" v={g.equipo ?? "—"} />
        <Fila k="N° de serie" v={g.numero_serie ?? "—"} mono />
        <Fila k="Reparación" v={g.descripcion ?? "—"} />
        <Fila k="Ticket" v={g.id_ticket} mono />
        <Fila k="Entrega" v={soloFecha(g.fecha_entrega)} />
        <Fila k="Vence" v={soloFecha(g.fecha_vencimiento)} />
      </dl>
      <p className="mt-3 border-t border-slate-800 pt-2 text-center text-xs text-slate-500">
        {cargando ? "Cargando comprobante…" : "Clic para ver el comprobante"}
      </p>
    </div>
  );
}

function Fila({ k, v, mono = false }: Readonly<{ k: string; v: string; mono?: boolean }>) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-slate-500">{k}</dt>
      <dd className={`text-right text-slate-200 ${mono ? "font-mono text-xs" : ""}`}>{v}</dd>
    </div>
  );
}

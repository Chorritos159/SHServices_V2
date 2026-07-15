"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api/client";
import { extraerError } from "@/components/ui/FormControls";
import type { TicketPendiente, DiagnosticoResponse } from "@/lib/types/backend";
import type { ComprobanteData } from "@/components/print/ComprobanteModal";

/**
 * Modal de cobro: ID del ticket precargado + costos (mano de obra y repuestos).
 * Emite la factura (facturacion_service) y devuelve los datos del comprobante.
 */
export default function CobroModal({
  ticket,
  onDone,
  onClose,
}: {
  ticket: TicketPendiente;
  onDone: (comprobante: ComprobanteData) => void;
  onClose: () => void;
}) {
  const [manoObra, setManoObra] = useState<number>(ticket.precio_estimado ?? 0);
  const [repuestos, setRepuestos] = useState<number>(0);
  const [metodoPago, setMetodoPago] = useState("EFECTIVO");
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const total = useMemo(() => (Number(manoObra) || 0) + (Number(repuestos) || 0), [manoObra, repuestos]);

  async function cobrar() {
    setEnviando(true);
    setError(null);
    try {
      const { data } = await api.post<DiagnosticoResponse & {
        idFactura: string; montoTotal: number; estadoPago: string; fechaEmision: string;
      }>("/facturas", {
        idTicket: ticket.id,
        montoManoObra: Number(manoObra),
        montoRepuestos: Number(repuestos),
        metodoPago,
        sede: ticket.sede,
      });
      onDone({
        idFactura: data.idFactura,
        idTicket: ticket.id,
        cliente: ticket.datos_cliente,
        documento: ticket.documento_cliente ?? "—",
        manoObra: Number(manoObra),
        repuestos: Number(repuestos),
        total: data.montoTotal ?? total,
        metodoPago,
        estadoPago: data.estadoPago ?? "PAGADO",
        fecha: data.fechaEmision ?? new Date().toISOString(),
      });
    } catch (err) {
      setError(extraerError(err));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-900 p-6">
        <div className="mb-4 border-b border-slate-800 pb-3">
          <h3 className="text-lg font-semibold text-white">Cobrar y Entregar</h3>
          <p className="mt-0.5 text-sm text-slate-400">
            Ticket <span className="font-mono text-amber-300">{ticket.id}</span> · {ticket.datos_cliente}
          </p>
        </div>

        <div className="flex flex-col gap-3">
          <Num label="Mano de obra (S/.)" value={manoObra} onChange={setManoObra} />
          <Num label="Repuestos (S/.)" value={repuestos} onChange={setRepuestos} />
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-slate-300">Método de pago</span>
            <select
              value={metodoPago}
              onChange={(e) => setMetodoPago(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-amber-500"
            >
              <option value="EFECTIVO">EFECTIVO</option>
              <option value="TARJETA">TARJETA</option>
              <option value="YAPE">YAPE</option>
            </select>
          </label>

          <div className="flex items-center justify-between rounded-lg bg-slate-950 px-4 py-3">
            <span className="text-sm text-slate-400">TOTAL</span>
            <span className="text-xl font-bold text-emerald-300">S/. {total.toFixed(2)}</span>
          </div>

          {error && (
            <p className="rounded-lg border border-red-900/60 bg-red-950/40 px-3 py-2 text-sm text-red-300">{error}</p>
          )}

          <div className="mt-1 flex gap-2">
            <button
              onClick={cobrar}
              disabled={enviando}
              className="flex-1 rounded-lg bg-emerald-600 px-4 py-2.5 font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-60"
            >
              {enviando ? "Procesando…" : "Emitir comprobante"}
            </button>
            <button
              onClick={onClose}
              disabled={enviando}
              className="rounded-lg border border-slate-700 px-4 py-2.5 text-sm text-slate-300 transition hover:bg-slate-800"
            >
              Cancelar
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Num({ label, value, onChange }: { label: string; value: number; onChange: (n: number) => void }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-slate-300">{label}</span>
      <input
        type="number"
        min={0}
        step="0.01"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/30"
      />
    </label>
  );
}

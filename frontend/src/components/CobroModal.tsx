"use client";

import { useEffect, useMemo, useState } from "react";
import { isAxiosError } from "axios";
import { api } from "@/lib/api/client";
import { extraerError } from "@/components/ui/FormControls";
import type { TicketPendiente, DiagnosticoDetalle } from "@/lib/types/backend";
import type { ComprobanteData } from "@/components/print/ComprobanteModal";

const money = (n: number) => `S/. ${n.toFixed(2)}`;

/**
 * Modal de cobro: recupera el DESGLOSE del diagnóstico (falla, repuestos y mano de
 * obra fijada por el técnico) para que el cajero vea qué está cobrando, precarga los
 * montos, emite la factura y devuelve el comprobante.
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
  const [detalle, setDetalle] = useState<DiagnosticoDetalle | null>(null);
  const [cargandoDet, setCargandoDet] = useState(true);
  const [manoObra, setManoObra] = useState<number>(ticket.precio_estimado ?? 0);
  const [repuestos, setRepuestos] = useState<number>(0);
  const [metodoPago, setMetodoPago] = useState("EFECTIVO");
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Recupera el diagnóstico del ticket y precarga los montos.
  useEffect(() => {
    let vivo = true;
    (async () => {
      setCargandoDet(true);
      try {
        const { data } = await api.get<DiagnosticoDetalle>(`/diagnosticos/por-ticket/${ticket.id}`);
        if (!vivo) return;
        setDetalle(data);
        setManoObra(data.manoObra);
        setRepuestos(data.totalRepuestos);
      } catch {
        // Sin diagnóstico (ej. venta): se mantienen los valores por defecto.
      } finally {
        if (vivo) setCargandoDet(false);
      }
    })();
    return () => {
      vivo = false;
    };
  }, [ticket.id]);

  const total = useMemo(() => (Number(manoObra) || 0) + (Number(repuestos) || 0), [manoObra, repuestos]);

  async function cobrar() {
    setEnviando(true);
    setError(null);
    try {
      const { data } = await api.post<{
        idFactura: string; montoTotal: number; estadoPago: string; fechaEmision: string;
        garantia?: { fecha_vencimiento?: string } | null;
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
        garantiaVence: data.garantia?.fecha_vencimiento ?? null,
      });
    } catch (err) {
      setError(isAxiosError(err) ? extraerError(err) : "Error inesperado.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="max-h-[85vh] w-full max-w-md overflow-y-auto rounded-xl border border-slate-700 bg-slate-900 p-6">
        <div className="mb-4 border-b border-slate-800 pb-3">
          <h3 className="text-lg font-semibold text-white">Cobrar y Entregar</h3>
          <p className="mt-0.5 text-sm text-slate-400">
            Ticket <span className="font-mono text-amber-300">{ticket.id}</span> · {ticket.datos_cliente}
          </p>
        </div>

        {/* Desglose del diagnóstico */}
        <div className="mb-4 rounded-lg border border-slate-800 bg-slate-950/50 p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Detalle del diagnóstico</p>
          {cargandoDet ? (
            <p className="text-sm text-slate-500">Cargando diagnóstico…</p>
          ) : detalle ? (
            <>
              <p className="text-sm text-slate-300">
                <span className="text-slate-500">Falla: </span>
                {detalle.fallaDetectada}
              </p>
              {detalle.repuestos.length > 0 ? (
                <table className="mt-2 w-full text-left text-xs">
                  <thead className="text-slate-500">
                    <tr>
                      <th className="py-1 font-medium">Repuesto</th>
                      <th className="py-1 text-center font-medium">Cant.</th>
                      <th className="py-1 text-right font-medium">P. Unit.</th>
                      <th className="py-1 text-right font-medium">Subtotal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detalle.repuestos.map((r) => (
                      <tr key={r.codigo_repuesto} className="border-t border-slate-800/60">
                        <td className="py-1 text-slate-300">
                          <span className="font-mono text-cyan-300">{r.codigo_repuesto}</span> {r.descripcion}
                        </td>
                        <td className="py-1 text-center text-slate-300">{r.cantidad}</td>
                        <td className="py-1 text-right text-slate-400">{money(r.precio_unitario)}</td>
                        <td className="py-1 text-right text-slate-200">{money(r.subtotal)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="mt-1 text-xs text-slate-500">Sin repuestos.</p>
              )}
              <div className="mt-2 flex justify-between border-t border-slate-800 pt-2 text-xs text-slate-400">
                <span>Mano de obra fijada por el técnico</span>
                <span className="font-medium text-slate-200">{money(detalle.manoObra)}</span>
              </div>
            </>
          ) : (
            <p className="text-sm text-slate-500">Este ticket no tiene diagnóstico registrado.</p>
          )}
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
            <span className="text-xl font-bold text-emerald-300">{money(total)}</span>
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

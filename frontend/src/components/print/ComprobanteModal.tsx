"use client";

import PrintableModal, { EncabezadoEmpresa, Fila } from "@/components/print/PrintableModal";

export interface ComprobanteData {
  idFactura: string;
  idTicket: string;
  cliente: string;
  documento: string;
  manoObra: number;
  repuestos: number;
  total: number;
  metodoPago: string;
  estadoPago: string;
  fecha: string;
  garantiaVence?: string | null; // fecha de vencimiento de la garantía (90 días)
}

const money = (n: number) => `S/. ${n.toFixed(2)}`;

/** Boleta/Factura final tras el cobro. Imprimible (A4 o ticketera). */
export default function ComprobanteModal({ data, onClose }: { data: ComprobanteData; onClose: () => void }) {
  return (
    <PrintableModal onClose={onClose} anchoTicket>
      <EncabezadoEmpresa titulo="Comprobante de Pago" />

      <div className="my-3 rounded bg-slate-100 px-3 py-2 text-center">
        <p className="text-xs text-slate-500">N° de Comprobante</p>
        <p className="font-mono text-lg font-bold">{data.idFactura}</p>
      </div>

      <Fila label="Fecha" value={new Date(data.fecha).toLocaleString()} />
      <Fila label="Ticket" value={data.idTicket} />
      <Fila label="Cliente" value={data.cliente} />
      <Fila label="DNI/RUC" value={data.documento} />

      <div className="my-2 border-t border-dashed border-slate-300 pt-2">
        <Fila label="Mano de obra" value={money(data.manoObra)} />
        <Fila label="Repuestos" value={money(data.repuestos)} />
        <div className="mt-1 flex justify-between border-t border-slate-300 pt-1 text-base font-bold">
          <span>TOTAL</span>
          <span>{money(data.total)}</span>
        </div>
      </div>

      <Fila label="Método de pago" value={data.metodoPago} />

      <div className="mt-3 flex items-center justify-center gap-2 border-t border-dashed border-slate-400 pt-3">
        <span className="rounded bg-emerald-100 px-3 py-1 text-xs font-bold uppercase tracking-wide text-emerald-700">
          {data.estadoPago} · ENTREGADO
        </span>
      </div>
      {data.garantiaVence ? (
        <p className="mt-2 text-center text-xs font-medium text-slate-600">
          🛡️ Garantía de 90 días válida hasta el {new Date(data.garantiaVence).toLocaleDateString()}
        </p>
      ) : null}
      <p className="mt-2 text-center text-xs text-slate-500">¡Gracias por su preferencia!</p>
    </PrintableModal>
  );
}

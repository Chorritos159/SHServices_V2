"use client";

import PrintableModal, { EncabezadoEmpresa, Fila } from "@/components/print/PrintableModal";
import { fechaHora } from "@/lib/fecha";

export interface ReciboData {
  idTicket: string;
  fecha: string;
  cliente: string;
  documento: string;
  telefono: string;
  equipo: string;
  serie?: string;
  falla: string;
}

/** Ticket de Recojo (recepción de un equipo en SOPORTE). Imprimible. */
export default function ReciboModal({ data, onClose }: { data: ReciboData; onClose: () => void }) {
  return (
    <PrintableModal onClose={onClose} anchoTicket>
      <EncabezadoEmpresa titulo="Ticket de Recepción" />

      <div className="my-3 rounded bg-slate-100 px-3 py-2 text-center">
        <p className="text-xs text-slate-500">N° de Ticket</p>
        <p className="font-mono text-lg font-bold">{data.idTicket}</p>
      </div>

      <Fila label="Fecha" value={fechaHora(data.fecha)} />

      <div className="my-2 border-t border-dashed border-slate-300 pt-2">
        <p className="mb-1 text-xs font-semibold uppercase text-slate-400">Cliente</p>
        <Fila label="Nombre" value={data.cliente} />
        <Fila label="DNI/RUC" value={data.documento} />
        <Fila label="Teléfono" value={data.telefono} />
      </div>

      <div className="my-2 border-t border-dashed border-slate-300 pt-2">
        <p className="mb-1 text-xs font-semibold uppercase text-slate-400">Equipo</p>
        <Fila label="Ingresado" value={data.equipo} />
        {data.serie ? <Fila label="N° de serie" value={data.serie} /> : null}
        <div className="mt-1 text-sm">
          <span className="text-slate-500">Falla descrita:</span>
          <p className="mt-0.5 font-medium">{data.falla}</p>
        </div>
      </div>

      <p className="mt-3 border-t border-dashed border-slate-400 pt-3 text-center text-xs font-medium text-slate-600">
        Por favor, conserve este ticket para recoger su equipo.
      </p>
    </PrintableModal>
  );
}

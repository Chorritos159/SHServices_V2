"use client";

/**
 * Envoltorio de modal imprimible. El contenido (children) va dentro de
 * `.print-area` (blanco, texto negro) y se aísla al imprimir vía window.print().
 * Los botones llevan `.no-print` para no aparecer en el papel.
 */
export default function PrintableModal({
  onClose,
  children,
  anchoTicket = false,
}: {
  onClose: () => void;
  children: React.ReactNode;
  anchoTicket?: boolean; // true = ancho angosto tipo ticketera térmica
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className={anchoTicket ? "w-full max-w-xs" : "w-full max-w-md"}>
        <div className="print-area max-h-[80vh] overflow-y-auto rounded-lg bg-white p-6 text-black shadow-2xl">
          {children}
        </div>
        <div className="no-print mt-3 flex gap-2">
          <button
            onClick={() => window.print()}
            className="flex-1 rounded-lg bg-slate-800 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-700"
          >
            🖨 Imprimir
          </button>
          <button
            onClick={onClose}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
          >
            Cerrar
          </button>
        </div>
      </div>
    </div>
  );
}

/** Encabezado común de los comprobantes (logo/nombre de la empresa). */
export function EncabezadoEmpresa({ titulo }: { titulo: string }) {
  return (
    <div className="border-b border-dashed border-slate-400 pb-3 text-center">
      <div className="mx-auto mb-1 flex h-10 w-10 items-center justify-center rounded bg-slate-900 text-sm font-bold text-white">
        SH
      </div>
      <h2 className="text-lg font-bold tracking-tight">SHServices</h2>
      <p className="text-xs text-slate-500">Servicio Técnico &amp; Ventas</p>
      <p className="mt-1 text-sm font-semibold uppercase tracking-wide">{titulo}</p>
    </div>
  );
}

/** Fila etiqueta/valor reutilizable en los comprobantes. */
export function Fila({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 py-0.5 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
}

import EntregasView from "@/components/EntregasView";

export default function EntregasPage() {
  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-bold text-white">Entregas y Cobros</h2>
        <p className="mt-1 text-slate-400">
          Tickets <b>DIAGNOSTICADO</b> listos para cobrar y entregar. Al cobrar se emite el
          comprobante imprimible y el ticket pasa a <code className="text-amber-300">ENTREGADO</code>.
        </p>
      </header>
      <EntregasView />
    </div>
  );
}

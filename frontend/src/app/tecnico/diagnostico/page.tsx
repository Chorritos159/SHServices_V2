import DiagnosticoView from "@/components/DiagnosticoView";

export default function DiagnosticoPage() {
  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-bold text-white">Diagnóstico Técnico</h2>
        <p className="mt-1 text-slate-400">
          Revisa los tickets <b>EN_COLA</b>, registra el diagnóstico con su precio y repuestos.
          Al guardar, se descuenta stock y el ticket pasa a{" "}
          <code className="text-cyan-300">DIAGNOSTICADO</code>.
        </p>
      </header>
      <DiagnosticoView />
    </div>
  );
}

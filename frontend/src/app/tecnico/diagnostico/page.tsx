import DiagnosticoView from "@/components/DiagnosticoView";
import { getSession } from "@/lib/auth/session";

export default async function DiagnosticoPage() {
  const session = await getSession();
  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-bold text-white">Diagnóstico Técnico</h2>
        <p className="mt-1 text-slate-400">
          <b>Toma</b> un ticket de la cola de tu sede (queda solo para ti) y diagnostícalo desde{" "}
          <b className="text-cyan-300">Mis Tickets</b>. Al guardar, se descuenta stock y el ticket pasa a{" "}
          <code className="text-cyan-300">DIAGNOSTICADO</code>.
        </p>
      </header>
      <DiagnosticoView sede={session?.sede ?? ""} />
    </div>
  );
}

import Link from "next/link";
import { getSession } from "@/lib/auth/session";

export default async function TecnicoHomePage() {
  const session = await getSession();

  return (
    <div>
      <header className="mb-8">
        <h2 className="text-2xl font-bold text-white">Taller Técnico</h2>
        <p className="mt-1 text-slate-400">
          Bienvenido, <span className="text-cyan-300">{session?.sub}</span> · sede{" "}
          <span className="font-semibold text-cyan-400">{session?.sede}</span>.
        </p>
      </header>

      <Link
        href="/tecnico/diagnostico"
        className="group block max-w-md rounded-xl border border-slate-800 bg-slate-900/50 p-6 transition hover:border-cyan-700 hover:bg-slate-900"
      >
        <h3 className="text-lg font-semibold text-white group-hover:text-cyan-300">Diagnóstico Técnico</h3>
        <p className="mt-2 text-sm text-slate-400">
          Revisa los tickets en cola, registra el diagnóstico y descuenta repuestos del almacén.
        </p>
      </Link>
    </div>
  );
}

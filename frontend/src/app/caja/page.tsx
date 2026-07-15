import Link from "next/link";
import { getSession } from "@/lib/auth/session";

export default async function CajaHomePage() {
  const session = await getSession();

  const tarjetas = [
    { href: "/caja/tickets", titulo: "Registro de Tickets", texto: "Crea atenciones de soporte o registra ventas." },
    { href: "/caja/entregas", titulo: "Entregas y Cobros", texto: "Cobra y entrega los equipos diagnosticados; emite el comprobante." },
  ];

  return (
    <div>
      <header className="mb-8">
        <h2 className="text-2xl font-bold text-white">Caja / Recepción</h2>
        <p className="mt-1 text-slate-400">
          Bienvenido, <span className="text-amber-300">{session?.sub}</span> · sede{" "}
          <span className="font-semibold text-amber-400">{session?.sede}</span>.
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2">
        {tarjetas.map((t) => (
          <Link
            key={t.href}
            href={t.href}
            className="group rounded-xl border border-slate-800 bg-slate-900/50 p-6 transition hover:border-amber-700 hover:bg-slate-900"
          >
            <h3 className="text-lg font-semibold text-white group-hover:text-amber-300">{t.titulo}</h3>
            <p className="mt-2 text-sm text-slate-400">{t.texto}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}

import Link from "next/link";
import { getSession } from "@/lib/auth/session";

export default async function AdminDashboardPage() {
  const session = await getSession();

  const tarjetas = [
    {
      href: "/admin/inventario",
      titulo: "Gestión de Inventario",
      texto: "Alta de repuestos y reserva de stock por sede vía el almacen-service.",
    },
    {
      href: "/admin/auditoria",
      titulo: "Auditoría",
      texto: "Trazabilidad de eventos del sistema (consumidor asíncrono).",
    },
  ];

  return (
    <div>
      <header className="mb-8">
        <h2 className="text-2xl font-bold text-white">Panel de Administración</h2>
        <p className="mt-1 text-slate-400">
          Bienvenido, <span className="text-sky-300">{session?.sub}</span>. Sesión con rol{" "}
          <span className="font-semibold text-emerald-400">ADMIN</span>.
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {tarjetas.map((t) => (
          <Link
            key={t.href}
            href={t.href}
            className="group rounded-xl border border-slate-800 bg-slate-900/50 p-6 transition hover:border-sky-700 hover:bg-slate-900"
          >
            <h3 className="text-lg font-semibold text-white group-hover:text-sky-300">
              {t.titulo}
            </h3>
            <p className="mt-2 text-sm text-slate-400">{t.texto}</p>
          </Link>
        ))}
      </div>

      <section className="mt-8 rounded-xl border border-slate-800 bg-slate-900/30 p-6">
        <h3 className="text-sm font-semibold text-slate-300">Arquitectura del cliente</h3>
        <ul className="mt-3 space-y-1.5 text-sm text-slate-400">
          <li>• JWT en cookie <b>HttpOnly</b> (inmune a XSS), fijada por Server Action.</li>
          <li>• Axios de servidor inyecta el <b>Bearer</b> en cada llamada al Gateway.</li>
          <li>• Middleware RBAC en el Edge: solo ADMIN entra aquí.</li>
        </ul>
      </section>
    </div>
  );
}

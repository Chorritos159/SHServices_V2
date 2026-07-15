import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth/session";
import TecnicoSidebar from "@/components/TecnicoSidebar";
import NotificationBell from "@/components/NotificationBell";

/** Área TECNICO (taller/diagnóstico). Guard de servidor: solo rol TECNICO. */
export default async function TecnicoLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();
  if (!session) redirect("/login");
  if (session.rol !== "TECNICO") redirect("/"); // el middleware reencamina a su panel

  return (
    <div className="flex min-h-screen">
      <TecnicoSidebar usuario={session.sub} sede={session.sede} />
      <div className="flex flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-end border-b border-slate-800 bg-slate-950/50 px-8">
          <NotificationBell />
        </header>
        <main className="flex-1 overflow-y-auto p-8">{children}</main>
      </div>
    </div>
  );
}

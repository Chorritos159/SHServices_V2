import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth/session";
import CajaSidebar from "@/components/CajaSidebar";
import NotificationBell from "@/components/NotificationBell";

/** Área CAJA (recepción/ventas). Guard de servidor: solo rol CAJA. */
export default async function CajaLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();
  if (!session) redirect("/login");
  if (session.rol !== "CAJA") redirect("/"); // el middleware reencamina a su panel

  return (
    <div className="flex min-h-screen">
      <CajaSidebar usuario={session.sub} sede={session.sede} />
      <div className="flex flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-end border-b border-slate-800 bg-slate-950/50 px-8">
          <NotificationBell />
        </header>
        <main className="flex-1 overflow-y-auto p-8">{children}</main>
      </div>
    </div>
  );
}

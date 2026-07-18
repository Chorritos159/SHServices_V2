import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth/session";
import Sidebar from "@/components/Sidebar";
import NotificationBell from "@/components/NotificationBell";

/**
 * Layout del área ADMIN. Doble candado de seguridad:
 *   1. El middleware ya bloqueó a los no-ADMIN antes de llegar aquí.
 *   2. Este guard de servidor revalida la sesión (defensa en profundidad).
 */
export default async function AdminLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const session = await getSession();
  if (!session) redirect("/login");
  if (session.rol !== "ADMIN") redirect("/");

  return (
    <div className="flex min-h-screen">
      <Sidebar usuario={session.sub} />
      <div className="flex flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-end border-b border-slate-800 bg-slate-950/50 px-8">
          <NotificationBell />
        </header>
        <main className="flex-1 overflow-y-auto p-8">{children}</main>
      </div>
    </div>
  );
}

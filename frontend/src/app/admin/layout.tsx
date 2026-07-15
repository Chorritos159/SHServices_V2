import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth/session";
import Sidebar from "@/components/Sidebar";

/**
 * Layout del área ADMIN. Doble candado de seguridad:
 *   1. El middleware ya bloqueó a los no-ADMIN antes de llegar aquí.
 *   2. Este guard de servidor revalida la sesión (defensa en profundidad).
 */
export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await getSession();
  if (!session) redirect("/login");
  if (session.rol !== "ADMIN") redirect("/operador");

  return (
    <div className="flex min-h-screen">
      <Sidebar usuario={session.sub} />
      <main className="flex-1 overflow-y-auto p-8">{children}</main>
    </div>
  );
}

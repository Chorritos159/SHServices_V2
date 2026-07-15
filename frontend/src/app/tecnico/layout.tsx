import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth/session";
import TecnicoSidebar from "@/components/TecnicoSidebar";

/** Área TECNICO (taller/diagnóstico). Guard de servidor: solo rol TECNICO. */
export default async function TecnicoLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();
  if (!session) redirect("/login");
  if (session.rol !== "TECNICO") redirect("/"); // el middleware reencamina a su panel

  return (
    <div className="flex min-h-screen">
      <TecnicoSidebar usuario={session.sub} sede={session.sede} />
      <main className="flex-1 overflow-y-auto p-8">{children}</main>
    </div>
  );
}

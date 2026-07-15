import { redirect } from "next/navigation";
import { getSession } from "@/lib/auth/session";
import CajaSidebar from "@/components/CajaSidebar";

/** Área CAJA (recepción/ventas). Guard de servidor: solo rol CAJA. */
export default async function CajaLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();
  if (!session) redirect("/login");
  if (session.rol !== "CAJA") redirect("/"); // el middleware reencamina a su panel

  return (
    <div className="flex min-h-screen">
      <CajaSidebar usuario={session.sub} sede={session.sede} />
      <main className="flex-1 overflow-y-auto p-8">{children}</main>
    </div>
  );
}

import { logoutAction } from "@/lib/auth/actions";

/** Botón de cierre de sesión: dispara la Server Action que borra la cookie. */
export default function LogoutButton() {
  return (
    <form action={logoutAction}>
      <button
        type="submit"
        className="w-full rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 transition hover:border-red-800 hover:bg-red-950/40 hover:text-red-300"
      >
        Cerrar sesión
      </button>
    </form>
  );
}

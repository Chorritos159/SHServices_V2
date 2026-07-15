import { redirect } from "next/navigation";

/**
 * La raíz nunca se renderiza: el middleware ya redirige "/" según el rol.
 * Este redirect es solo una red de seguridad.
 */
export default function Home() {
  redirect("/login");
}

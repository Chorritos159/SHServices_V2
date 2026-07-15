import Link from "next/link";
import InventarioForm from "@/components/InventarioForm";

export default function IngresarProductoPage() {
  return (
    <div className="flex flex-col gap-6">
      <header>
        <h2 className="text-2xl font-bold text-white">Ingresar Producto</h2>
        <p className="mt-1 text-slate-400">
          El código (REP-XXX) se autogenera. ¿Buscas el inventario?{" "}
          <Link href="/admin/inventario" className="text-sky-400 hover:text-sky-300">
            Ver Listado de Almacén
          </Link>
          .
        </p>
      </header>

      <InventarioForm />
    </div>
  );
}

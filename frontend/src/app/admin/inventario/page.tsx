import Link from "next/link";
import ProductosTable from "@/components/ProductosTable";

export default function ListadoAlmacenPage() {
  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-white">Listado de Almacén</h2>
          <p className="mt-1 text-slate-400">Stock actual por sede (vía Gateway → almacen-service).</p>
        </div>
        <Link
          href="/admin/inventario/nuevo"
          className="shrink-0 rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-500"
        >
          + Ingresar producto
        </Link>
      </header>

      <ProductosTable />
    </div>
  );
}

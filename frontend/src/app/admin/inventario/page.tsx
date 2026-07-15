import ProductosTable from "@/components/ProductosTable";
import InventarioForm from "@/components/InventarioForm";

export default function InventarioPage() {
  return (
    <div className="flex flex-col gap-8">
      <header>
        <h2 className="text-2xl font-bold text-white">Gestión de Inventario</h2>
        <p className="mt-1 text-slate-400">
          Listado en vivo e ingreso de stock. El descuento de repuestos lo realiza el técnico.
        </p>
      </header>

      <ProductosTable />

      <div>
        <h3 className="mb-4 text-lg font-semibold text-white">Ingresar producto</h3>
        <InventarioForm />
      </div>
    </div>
  );
}

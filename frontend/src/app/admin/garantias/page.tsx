import GarantiasView from "@/components/GarantiasView";

export default function AdminGarantiasPage() {
  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-bold text-white">Consulta de Garantías y Facturas</h2>
        <p className="mt-1 text-slate-400">
          Busca por DNI/RUC o N° de serie para ver si un equipo tiene garantía vigente.
        </p>
      </header>
      <GarantiasView />
    </div>
  );
}

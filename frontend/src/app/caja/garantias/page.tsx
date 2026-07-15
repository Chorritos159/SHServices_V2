import GarantiasView from "@/components/GarantiasView";

export default function CajaGarantiasPage() {
  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-bold text-white">Consulta de Garantías</h2>
        <p className="mt-1 text-slate-400">
          Antes de recibir un equipo, verifica si vuelve con garantía vigente por una reparación previa.
        </p>
      </header>
      <GarantiasView />
    </div>
  );
}

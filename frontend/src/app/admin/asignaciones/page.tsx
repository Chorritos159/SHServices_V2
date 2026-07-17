import AsignacionesView from "@/components/AsignacionesView";

export default function AsignacionesPage() {
  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-bold text-white">Asignaciones de Tickets</h2>
        <p className="mt-1 text-slate-400">
          Todos los tickets tomados y <b className="text-sky-300">quién los atiende</b>. Los datos los
          sirve el <b>servicio de diagnóstico</b>, así que esta vista sigue disponible aunque el
          servicio de tickets esté caído.
        </p>
      </header>
      <AsignacionesView />
    </div>
  );
}

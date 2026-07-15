import EventosTable from "@/components/EventosTable";

export default function AuditoriaPage() {
  return (
    <div className="flex flex-col gap-6">
      <header>
        <h2 className="text-2xl font-bold text-white">Auditoría</h2>
        <p className="mt-1 text-slate-400">
          Traza de eventos consumidos desde RabbitMQ por el auditoria-service.
        </p>
      </header>

      <EventosTable />

      <p className="text-xs text-slate-600">
        Nota: el auditoria-service guarda los eventos en memoria (se reinician al
        reiniciar el contenedor). Para historial permanente, persístelos en PostgreSQL.
      </p>
    </div>
  );
}

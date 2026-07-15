import TicketForm from "@/components/TicketForm";

export default function TicketsPage() {
  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-bold text-white">Registro de Tickets</h2>
        <p className="mt-1 text-slate-400">
          La <b>sede</b> se toma automáticamente de tu sesión (token JWT). El ID se genera como{" "}
          <code className="text-amber-300">TICK-XXX-XXXX</code>.
        </p>
      </header>
      <TicketForm />
    </div>
  );
}

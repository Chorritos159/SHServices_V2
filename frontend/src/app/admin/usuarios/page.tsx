import UsuariosView from "@/components/UsuariosView";

export default function UsuariosPage() {
  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-bold text-white">Gestión de Usuarios</h2>
        <p className="mt-1 text-slate-400">
          Da de alta empleados con su rol (ADMIN, CAJA, TECNICO) y sede. Solo el ADMIN puede hacerlo.
        </p>
      </header>
      <UsuariosView />
    </div>
  );
}

import FacturaForm from "@/components/FacturaForm";

export default function FacturacionPage() {
  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-bold text-white">Facturación</h2>
        <p className="mt-1 text-slate-400">
          Emite el comprobante de un ticket. El total lo calcula el backend y devuelve un{" "}
          <code className="text-amber-300">FAC-XXX-XXXX</code>.
        </p>
      </header>
      <FacturaForm />
    </div>
  );
}

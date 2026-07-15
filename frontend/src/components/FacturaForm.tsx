"use client";

import { useState } from "react";
import { api } from "@/lib/api/client";
import { Boton, Campo, Feedback, Select, extraerError, type Estado } from "@/components/ui/FormControls";

/**
 * Formulario de emisión de comprobantes (rol OPERADOR).
 * Navegador → Axios BFF (/api/facturas) → Gateway → facturacion_service.
 * El total lo calcula el backend (manoObra + repuestos).
 */
export default function FacturaForm() {
  const [estado, setEstado] = useState<Estado>({ tipo: "idle" });
  const [cargando, setCargando] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    setCargando(true);
    setEstado({ tipo: "idle" });

    const fd = new FormData(form);
    try {
      const { data } = await api.post("/facturas", {
        idTicket: String(fd.get("idTicket")),
        montoManoObra: Number(fd.get("montoManoObra")),
        montoRepuestos: Number(fd.get("montoRepuestos") || 0),
        metodoPago: String(fd.get("metodoPago")),
        sede: String(fd.get("sede")),
      });
      setEstado({
        tipo: "ok",
        mensaje: `✅ Comprobante ${data.idFactura} · total S/. ${data.montoTotal} · ${data.estadoPago}`,
      });
      form.reset();
    } catch (err) {
      setEstado({ tipo: "error", mensaje: extraerError(err) });
    } finally {
      setCargando(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex max-w-xl flex-col gap-4">
      <Campo name="idTicket" label="ID del ticket a cobrar" placeholder="TICK-PIU-XXXX" />

      <div className="grid grid-cols-2 gap-4">
        <Campo name="montoManoObra" label="Mano de obra (S/.)" type="number" min={0} step="0.01" placeholder="120.00" />
        <Campo name="montoRepuestos" label="Repuestos (S/.)" type="number" min={0} step="0.01" defaultValue={0} required={false} />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Select name="metodoPago" label="Método de pago" options={["EFECTIVO", "TARJETA", "YAPE"]} defaultValue="EFECTIVO" />
        <Select name="sede" label="Sede" options={["PIURA", "LIMA"]} defaultValue="PIURA" />
      </div>

      <Boton cargando={cargando}>Emitir comprobante</Boton>
      <Feedback estado={estado} />
    </form>
  );
}

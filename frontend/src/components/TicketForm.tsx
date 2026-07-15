"use client";

import { useState } from "react";
import { api } from "@/lib/api/client";
import { Boton, Campo, Feedback, Select, extraerError, type Estado } from "@/components/ui/FormControls";

/**
 * Formulario de creación de tickets (rol CAJA).
 * La SEDE ya NO se pide: la pone el Gateway desde el token. Si es VENTA se
 * ocultan los campos del equipo (solo aplican a SOPORTE).
 */
export default function TicketForm() {
  const [estado, setEstado] = useState<Estado>({ tipo: "idle" });
  const [cargando, setCargando] = useState(false);
  const [tipoOperacion, setTipoOperacion] = useState("SOPORTE");
  const esSoporte = tipoOperacion === "SOPORTE";

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    setCargando(true);
    setEstado({ tipo: "idle" });

    const fd = new FormData(form);
    try {
      const { data } = await api.post("/tickets", {
        datosCliente: String(fd.get("datosCliente")),
        tipoOperacion: String(fd.get("tipoOperacion")),
        datosEquipo: esSoporte ? String(fd.get("datosEquipo") ?? "") : null,
        prioridad: String(fd.get("prioridad")),
      });
      setEstado({
        tipo: "ok",
        mensaje: `✅ Ticket ${data.idTicket} creado · estado: ${data.estadoInicial} · ${data.tipoOperacionRegistrada}`,
      });
      form.reset();
      setTipoOperacion("SOPORTE");
    } catch (err) {
      setEstado({ tipo: "error", mensaje: extraerError(err) });
    } finally {
      setCargando(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex max-w-xl flex-col gap-4">
      <Campo name="datosCliente" label="Datos del cliente" placeholder="DNI, RUC o nombre" />

      <div className="grid grid-cols-2 gap-4">
        <Select
          name="tipoOperacion"
          label="Tipo de operación"
          options={["SOPORTE", "VENTA"]}
          defaultValue="SOPORTE"
          onChange={setTipoOperacion}
        />
        <Select
          name="prioridad"
          label="Prioridad"
          options={["ALTA", "MEDIA", "BAJA"]}
          defaultValue="MEDIA"
        />
      </div>

      {/* Los datos del equipo solo aplican a SOPORTE. */}
      {esSoporte && (
        <Campo name="datosEquipo" label="Datos del equipo" placeholder="Lenovo ThinkPad P15 Gen 1" />
      )}

      <Boton cargando={cargando}>Registrar ticket</Boton>
      <Feedback estado={estado} />
    </form>
  );
}

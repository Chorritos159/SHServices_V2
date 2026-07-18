"use client";

import { useState } from "react";
import { api } from "@/lib/api/client";
import { Boton, Campo, Feedback, Select, esEncolado, extraerError, type Estado } from "@/components/ui/FormControls";
import ReciboModal, { type ReciboData } from "@/components/print/ReciboModal";

/**
 * Registro de tickets (rol CAJA) — estilo Help Desk.
 * Datos del cliente y del equipo en secciones. En SOPORTE, al registrar con
 * éxito se abre el "Ticket de Recojo" imprimible.
 */
export default function TicketForm() {
  const [estado, setEstado] = useState<Estado>({ tipo: "idle" });
  const [cargando, setCargando] = useState(false);
  const [tipoOperacion, setTipoOperacion] = useState("SOPORTE");
  const [recibo, setRecibo] = useState<ReciboData | null>(null);
  const esSoporte = tipoOperacion === "SOPORTE";

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    setCargando(true);
    setEstado({ tipo: "idle" });

    const fd = new FormData(form);
    const datosCliente = String(fd.get("datosCliente"));
    const documento = String(fd.get("documento_cliente"));
    const telefono = String(fd.get("telefono_cliente"));
    const equipo = String(fd.get("equipo") ?? "");
    const serie = String(fd.get("numero_serie") ?? "");
    const falla = String(fd.get("caracteristicas_falla") ?? "");

    try {
      const { data } = await api.post("/tickets", {
        datosCliente,
        documento_cliente: documento,
        telefono_cliente: telefono,
        tipoOperacion: String(fd.get("tipoOperacion")),
        equipo: esSoporte ? equipo : null,
        numero_serie: esSoporte ? serie || null : null,
        caracteristicas_falla: esSoporte ? falla : null,
        precio_estimado: esSoporte ? Number(fd.get("precio_estimado") || 0) : null,
        prioridad: String(fd.get("prioridad")),
      });

      // Servicio de tickets caído: el Gateway lo encoló y lo registrará solo.
      if (esEncolado(data)) {
        setEstado({
          tipo: "encolado",
          mensaje:
            data.mensaje ??
            "⏳ El servicio de tickets no está disponible ahora mismo, pero tu ticket quedó en cola y se registrará automáticamente cuando vuelva. No lo vuelvas a enviar.",
        });
        form.reset();
        setTipoOperacion("SOPORTE");
        return;
      }

      if (esSoporte) {
        // Abrimos el Ticket de Recojo imprimible con los datos capturados.
        setRecibo({
          idTicket: data.idTicket,
          fecha: data.fechaRegistro ?? new Date().toISOString(),
          cliente: datosCliente,
          documento,
          telefono,
          equipo,
          serie,
          falla,
        });
        setEstado({ tipo: "idle" });
      } else {
        setEstado({ tipo: "ok", mensaje: `✅ Venta ${data.idTicket} registrada (${data.estadoInicial}).` });
      }
      form.reset();
      setTipoOperacion("SOPORTE");
    } catch (err) {
      setEstado({ tipo: "error", mensaje: extraerError(err) });
    } finally {
      setCargando(false);
    }
  }

  return (
    <>
      <form onSubmit={onSubmit} className="flex max-w-xl flex-col gap-5">
        {/* Sección: datos del cliente */}
        <fieldset className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
          <legend className="px-2 text-sm font-semibold text-amber-300">Datos del cliente</legend>
          <div className="flex flex-col gap-3">
            <Campo name="datosCliente" label="Nombre" placeholder="Juan Pérez / Empresa SAC" />
            <div className="grid grid-cols-2 gap-3">
              <Campo name="documento_cliente" label="DNI / RUC" placeholder="12345678" />
              <Campo name="telefono_cliente" label="Teléfono" placeholder="987654321" />
            </div>
          </div>
        </fieldset>

        {/* Sección: operación */}
        <div className="grid grid-cols-2 gap-4">
          <Select
            name="tipoOperacion"
            label="Tipo de operación"
            options={["SOPORTE", "VENTA"]}
            defaultValue="SOPORTE"
            onChange={setTipoOperacion}
          />
          <Select name="prioridad" label="Prioridad" options={["ALTA", "MEDIA", "BAJA"]} defaultValue="MEDIA" />
        </div>

        {/* Sección: datos del equipo (solo SOPORTE) */}
        {esSoporte && (
          <fieldset className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
            <legend className="px-2 text-sm font-semibold text-amber-300">Datos del equipo</legend>
            <div className="flex flex-col gap-3">
              <div className="grid grid-cols-2 gap-3">
                <Campo name="equipo" label="Equipo" placeholder="Lenovo ThinkPad P15 Gen 1" />
                <Campo name="numero_serie" label="N° de serie (opcional)" placeholder="SN-XXXXXX" required={false} />
              </div>
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-slate-300">Falla / características</span>
                <textarea
                  name="caracteristicas_falla"
                  required
                  rows={3}
                  placeholder="No enciende, huele a quemado, pantalla con líneas…"
                  className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 placeholder:text-slate-600 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/30"
                />
              </label>
              <Campo
                name="precio_estimado"
                label="Precio estimado (S/.) — opcional"
                type="number"
                min={0}
                required={false}
                placeholder="0.00"
              />
            </div>
          </fieldset>
        )}

        <Boton cargando={cargando}>Registrar ticket</Boton>
        <Feedback estado={estado} />
      </form>

      {recibo && <ReciboModal data={recibo} onClose={() => setRecibo(null)} />}
    </>
  );
}

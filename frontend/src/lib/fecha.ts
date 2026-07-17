// Formateo de fechas SIEMPRE en hora de Peru (America/Lima, UTC-5).
//
// El backend emite las fechas en UTC con marcador de zona (Z / +00:00). Si se
// formatean con toLocaleString() sin fijar timeZone, se muestran en la zona
// del navegador de quien mira -> en otra zona saldria una hora equivocada.
// Fijando timeZone: "America/Lima" siempre se ve la hora de Peru, sin importar
// el navegador. La locale es-PE da el formato dd/mm/aaaa y "p. m." local.

const ZONA = "America/Lima";
const LOCALE = "es-PE";

/** Fecha + hora en Peru, ej. "17/07/2026, 12:54 p. m.". */
export function fechaHora(valor: string | number | Date): string {
  if (!valor) return "";
  return new Date(valor).toLocaleString(LOCALE, {
    timeZone: ZONA,
    dateStyle: "short",
    timeStyle: "short",
  });
}

/** Solo fecha en Peru, ej. "17/07/2026". */
export function soloFecha(valor: string | number | Date): string {
  if (!valor) return "";
  return new Date(valor).toLocaleDateString(LOCALE, { timeZone: ZONA });
}

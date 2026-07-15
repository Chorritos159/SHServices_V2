import { NextResponse, type NextRequest } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: registro de diagnóstico técnico.
 * Ruta DOBLADA → /diagnosticos/diagnosticos/ → diagnostico-service:80/api/v1/diagnosticos/.
 *
 * Orquesta 2 pasos (patrón BFF):
 *   1. POST del diagnóstico (si pide repuesto, el diagnostico-service reserva stock;
 *      si el almacén rechaza, devuelve 400 y NO seguimos).
 *   2. Best-effort: mueve el ticket EN_COLA → DIAGNOSTICADO para sacarlo de la bandeja.
 *      Si el PATCH falla, el diagnóstico YA se guardó, así que no rompemos el éxito.
 */
export async function POST(request: NextRequest) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "No autenticado." }, { status: 401 });
  }

  const body = await request.json();
  // Fase 3: precio + ARRAY de repuestos. La `sede` la inyecta el Gateway (X-User-Sede).
  const payload = {
    idTicket: body.idTicket,
    fallaDetectada: body.fallaDetectada,
    precio_reparacion: Number(body.precio_reparacion ?? 0),
    repuestos: Array.isArray(body.repuestos) ? body.repuestos : [],
  };

  let data: unknown;
  try {
    const res = await gateway.post("/diagnosticos/diagnosticos/", payload);
    data = res.data;
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }

  // Paso 2 (best-effort): cerrar el ticket para que salga de la bandeja de pendientes.
  try {
    await gateway.patch(`/tickets/tickets/${encodeURIComponent(payload.idTicket)}`, {
      estado: "DIAGNOSTICADO",
    });
  } catch {
    // El diagnóstico ya se registró; no bloqueamos el éxito por el cambio de estado.
  }

  return NextResponse.json(data, { status: 201 });
}

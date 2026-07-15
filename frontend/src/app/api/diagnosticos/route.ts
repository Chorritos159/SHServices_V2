import { NextResponse, type NextRequest } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: registro de diagnóstico técnico.
 * Ruta DOBLADA → /diagnosticos/diagnosticos/ → diagnostico-service:80/api/v1/diagnosticos/.
 *
 * Orquesta 2 pasos (patrón BFF):
 *   1. POST del diagnóstico (el diagnostico-service RESERVA el stock de repuestos).
 *   2. Transición gobernada en el backend: POST /{id}/diagnosticar, que registra los
 *      repuestos reservados en el ticket (para confirmar/liberar luego) y lo mueve a
 *      DIAGNOSTICADO. La máquina de estados vive en el ticket_service, no aquí.
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

  // Paso 2: transición gobernada → DIAGNOSTICADO (registra los repuestos en el ticket).
  try {
    await gateway.post(`/tickets/tickets/${encodeURIComponent(payload.idTicket)}/diagnosticar`, {
      repuestos: payload.repuestos.map((r: { codigo_repuesto: string; cantidad: number }) => ({
        codigo_producto: r.codigo_repuesto,
        cantidad: r.cantidad,
      })),
    });
  } catch {
    // El diagnóstico ya se registró; no bloqueamos el éxito por el cambio de estado.
  }

  return NextResponse.json(data, { status: 201 });
}

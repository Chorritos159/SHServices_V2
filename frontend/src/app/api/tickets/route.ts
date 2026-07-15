import { NextResponse, type NextRequest } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: creación de tickets.
 * Navegador → (POST /api/tickets) → aquí → Gateway → ticket_service.
 * Mapea a POST /api/v1/tickets/tickets/ (service=tickets, path=tickets/).
 *
 * Fase 2: `sede` y `usuarioRegistro` YA NO se envían aquí — el Gateway los
 * inyecta al backend desde el JWT (cabeceras X-User-Sede / X-User-Sub).
 */
export async function POST(request: NextRequest) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "No autenticado." }, { status: 401 });
  }

  const body = await request.json();

  const payload = {
    datosCliente: body.datosCliente,
    documento_cliente: body.documento_cliente,
    telefono_cliente: body.telefono_cliente,
    tipoOperacion: body.tipoOperacion,
    equipo: body.equipo || null,
    caracteristicas_falla: body.caracteristicas_falla || null,
    precio_estimado: body.precio_estimado ?? null,
    prioridad: body.prioridad,
  };

  try {
    // La barra final importa: el POST del ticket_service está montado en "/".
    const { data } = await gateway.post("/tickets/tickets/", payload);
    return NextResponse.json(data, { status: 201 });
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }
}

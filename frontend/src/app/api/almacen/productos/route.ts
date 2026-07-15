import { NextResponse, type NextRequest } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF de inventario. Navegador → aquí → Gateway (Bearer inyectado) → almacen-service.
 *
 * OJO con la ruta hacia el Gateway: por la convención /api/v1/{service}/{path},
 * para alcanzar el router montado en /api/v1/almacen/... el path va DOBLADO:
 *   gateway.get("/almacen/almacen/productos")
 *     → http://localhost:8000/api/v1/almacen/almacen/productos
 *     → almacen-service:80/api/v1/almacen/productos  ✅
 * (igual que los tickets usan /tickets/tickets/).
 */

// GET: listado completo del inventario (para la tabla del Admin).
export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "No autenticado." }, { status: 401 });
  }

  try {
    const { data } = await gateway.get("/almacen/almacen/productos");
    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }
}

// POST: alta / reabastecimiento de producto.
export async function POST(request: NextRequest) {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "No autenticado." }, { status: 401 });
  }

  const body = await request.json();

  try {
    const { data } = await gateway.post("/almacen/almacen/productos", body);
    return NextResponse.json(data, { status: 201 });
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }
}

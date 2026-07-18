import { NextResponse } from "next/server";
import { getSession } from "@/lib/auth/session";
import { gateway } from "@/lib/api/gateway";

/**
 * BFF: catálogo vendible del POS de Caja.
 *
 * No recibe `sede` por parámetro a propósito: almacen-service la lee del token
 * (cabecera `X-User-Sede` que inyecta el Gateway), así que una cajera solo
 * puede listar —y por tanto vender— el stock que tiene físicamente delante.
 *
 * Ruta hacia el Gateway doblada por la convención /api/v1/{service}/{path}:
 *   /almacen/almacen/productos/venta → almacen-service:80/api/v1/almacen/productos/venta
 */
export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ error: "No autenticado." }, { status: 401 });
  }

  try {
    const { data } = await gateway.get("/almacen/almacen/productos/venta");
    return NextResponse.json(data, { status: 200 });
  } catch (err) {
    const e = err as { status?: number; data?: unknown };
    // El catálogo es una LECTURA: si el almacén está caído devolvemos lista
    // vacía con el aviso, para que la pantalla de venta cargue igual y la
    // cajera vea por qué no hay productos, en vez de una pantalla rota.
    if (e.status === 503 || e.status === 504) {
      return NextResponse.json(
        {
          productos: [],
          degradado: true,
          mensaje:
            "El almacén no está disponible; no se puede cargar el catálogo. Reintenta en unos segundos.",
        },
        { status: 200 },
      );
    }
    return NextResponse.json(e.data ?? { error: "Fallo en el Gateway." }, {
      status: e.status ?? 500,
    });
  }
}

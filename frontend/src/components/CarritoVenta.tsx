"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";

/**
 * Carrito del POS de mostrador (rol CAJA).
 *
 * El catálogo lo sirve el BFF desde `almacen-service`, que filtra por la SEDE
 * del token: la cajera solo ve —y solo puede vender— el stock que tiene
 * físicamente delante. Por eso aquí no hay ningún selector de sede.
 */

export interface ProductoVenta {
  codigo: string;
  nombre: string;
  sede: string;
  stock_disponible: number;
  precio_unitario: number;
}

export interface LineaCarrito {
  codigo_producto: string;
  descripcion: string;
  cantidad: number;
  precio_unitario: number;
}

interface Props {
  lineas: LineaCarrito[];
  onCambio: (lineas: LineaCarrito[]) => void;
}

export default function CarritoVenta({ lineas, onCambio }: Props) {
  const [catalogo, setCatalogo] = useState<ProductoVenta[]>([]);
  const [aviso, setAviso] = useState<string | null>(null);
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const { data } = await api.get("/almacen/venta");
        if (!vivo) return;
        // El BFF degrada a { productos: [], degradado: true } si el almacén
        // está caído: la pantalla carga igual y explica por qué está vacía.
        if (Array.isArray(data)) {
          setCatalogo(data);
        } else {
          setCatalogo([]);
          setAviso(data?.mensaje ?? "No se pudo cargar el catálogo.");
        }
      } catch {
        if (vivo) setAviso("No se pudo cargar el catálogo de productos.");
      } finally {
        if (vivo) setCargando(false);
      }
    })();
    return () => {
      vivo = false;
    };
  }, []);

  /** Stock que queda de un producto descontando lo ya puesto en el carrito. */
  function disponible(p: ProductoVenta): number {
    const enCarrito = lineas.find((l) => l.codigo_producto === p.codigo)?.cantidad ?? 0;
    return p.stock_disponible - enCarrito;
  }

  function agregar(p: ProductoVenta) {
    if (disponible(p) <= 0) return;
    const existente = lineas.find((l) => l.codigo_producto === p.codigo);
    if (existente) {
      onCambio(
        lineas.map((l) =>
          l.codigo_producto === p.codigo ? { ...l, cantidad: l.cantidad + 1 } : l,
        ),
      );
    } else {
      onCambio([
        ...lineas,
        {
          codigo_producto: p.codigo,
          descripcion: p.nombre,
          cantidad: 1,
          precio_unitario: p.precio_unitario,
        },
      ]);
    }
  }

  function cambiarCantidad(codigo: string, delta: number) {
    const producto = catalogo.find((p) => p.codigo === codigo);
    onCambio(
      lineas
        .map((l) => {
          if (l.codigo_producto !== codigo) return l;
          const tope = producto?.stock_disponible ?? l.cantidad;
          return { ...l, cantidad: Math.min(Math.max(l.cantidad + delta, 0), tope) };
        })
        .filter((l) => l.cantidad > 0),
    );
  }

  const total = lineas.reduce((acc, l) => acc + l.cantidad * l.precio_unitario, 0);

  return (
    <fieldset className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
      <legend className="px-2 text-sm font-semibold text-amber-300">
        Productos de la venta
      </legend>

      {cargando && <p className="text-sm text-slate-400">Cargando catálogo…</p>}

      {aviso && (
        <p className="rounded-lg border border-amber-700/50 bg-amber-950/30 px-3 py-2 text-sm text-amber-300">
          {aviso}
        </p>
      )}

      {!cargando && !aviso && catalogo.length === 0 && (
        <p className="text-sm text-slate-400">
          No hay productos con stock en tu sede.
        </p>
      )}

      {catalogo.length > 0 && (
        <div className="mb-4 max-h-56 overflow-y-auto rounded-lg border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-slate-900 text-slate-400">
              <tr>
                <th className="px-3 py-2 font-medium">Producto</th>
                <th className="px-3 py-2 font-medium">Precio</th>
                <th className="px-3 py-2 font-medium">Stock</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {catalogo.map((p) => {
                const quedan = disponible(p);
                return (
                  <tr key={p.codigo} className="border-t border-slate-800">
                    <td className="px-3 py-2 text-slate-200">
                      {p.nombre}
                      <span className="ml-2 text-xs text-slate-500">{p.codigo}</span>
                    </td>
                    <td className="px-3 py-2 text-slate-300">
                      S/. {p.precio_unitario.toFixed(2)}
                    </td>
                    <td className="px-3 py-2 text-slate-400">{quedan}</td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => agregar(p)}
                        disabled={quedan <= 0}
                        className="rounded-md bg-amber-600 px-3 py-1 text-xs font-semibold text-white transition hover:bg-amber-500 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-500"
                      >
                        Agregar
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {lineas.length > 0 && (
        <div className="flex flex-col gap-2">
          {lineas.map((l) => (
            <div
              key={l.codigo_producto}
              className="flex items-center justify-between rounded-lg bg-slate-950/60 px-3 py-2 text-sm"
            >
              <span className="text-slate-200">{l.descripcion}</span>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  aria-label={`Quitar una unidad de ${l.descripcion}`}
                  onClick={() => cambiarCantidad(l.codigo_producto, -1)}
                  className="h-6 w-6 rounded bg-slate-800 text-slate-200 hover:bg-slate-700"
                >
                  −
                </button>
                <span className="w-6 text-center text-slate-100">{l.cantidad}</span>
                <button
                  type="button"
                  aria-label={`Agregar una unidad de ${l.descripcion}`}
                  onClick={() => cambiarCantidad(l.codigo_producto, 1)}
                  className="h-6 w-6 rounded bg-slate-800 text-slate-200 hover:bg-slate-700"
                >
                  +
                </button>
                <span className="w-20 text-right text-slate-300">
                  S/. {(l.cantidad * l.precio_unitario).toFixed(2)}
                </span>
              </div>
            </div>
          ))}
          <div className="flex justify-between border-t border-slate-800 pt-2 text-base font-semibold">
            <span className="text-slate-300">Total</span>
            <span className="text-amber-300">S/. {total.toFixed(2)}</span>
          </div>
        </div>
      )}
    </fieldset>
  );
}

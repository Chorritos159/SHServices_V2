"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api/client";
import type { Notificacion } from "@/lib/types/backend";

const POLL_MS = 10_000;

/**
 * Campanita de notificaciones internas. Hace polling ligero (cada 10s) al BFF y
 * muestra un globo rojo con el número de alertas nuevas. Al abrir, las marca leídas.
 */
export default function NotificationBell() {
  const [alertas, setAlertas] = useState<Notificacion[]>([]);
  const [abierto, setAbierto] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const cargar = useCallback(async () => {
    try {
      const { data } = await api.get<Notificacion[]>("/notificaciones/mis-alertas");
      setAlertas(data);
    } catch {
      /* silencioso: no rompemos la UI por el polling */
    }
  }, []);

  useEffect(() => {
    cargar();
    const id = setInterval(cargar, POLL_MS);
    return () => clearInterval(id);
  }, [cargar]);

  // Cerrar al hacer clic fuera.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setAbierto(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  async function toggle() {
    const nuevo = !abierto;
    setAbierto(nuevo);
    if (nuevo && alertas.length > 0) {
      // Marca leídas al abrir; el globo se limpiará en el próximo poll.
      try {
        await api.post("/notificaciones/marcar-leidas");
      } catch {
        /* noop */
      }
    }
  }

  const count = alertas.length;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={toggle}
        className="relative flex h-9 w-9 items-center justify-center rounded-lg border border-slate-700 text-slate-300 transition hover:border-slate-500 hover:text-white"
        aria-label="Notificaciones"
      >
        <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" stroke="currentColor" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 0 0 5.454-1.31A8.967 8.967 0 0 1 18 9.75V9A6 6 0 0 0 6 9v.75a8.967 8.967 0 0 1-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 0 1-5.714 0m5.714 0a3 3 0 1 1-5.714 0" />
        </svg>
        {count > 0 && (
          <span className="absolute -right-1 -top-1 flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>

      {abierto && (
        <div className="absolute right-0 z-50 mt-2 w-80 overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
          <header className="border-b border-slate-800 px-4 py-2.5 text-sm font-semibold text-slate-200">
            Notificaciones {count > 0 && `· ${count}`}
          </header>
          <div className="max-h-80 overflow-y-auto">
            {count === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-slate-500">Sin alertas nuevas 🎉</p>
            ) : (
              <ul className="divide-y divide-slate-800">
                {alertas.map((a) => (
                  <li key={a.id} className="px-4 py-3">
                    <p className="text-sm text-slate-200">{a.mensaje}</p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {new Date(a.created_at).toLocaleString()}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

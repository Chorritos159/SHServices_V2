/** Tipos de lectura devueltos por el backend (endpoints GET). */

/** GET /api/v1/almacen/productos → almacen-service. */
export interface ProductoInventario {
  codigo: string;
  nombre: string;
  categoria: string;
  sede: string;
  stock_disponible: number;
  stock_reservado: number;
}

/** GET /api/v1/auditoria/eventos → auditoria-service. */
export interface EventoAuditoria {
  evento: string | null;
  trace_id: string | null;
  sede: string | null;
  idTicket: string | null;
  recibido_en: string;
  datos: Record<string, unknown>;
}

/** GET /api/v1/tickets/pendientes → ticket-service (bandeja del técnico). */
export interface TicketPendiente {
  id: string;
  datos_cliente: string;
  tipo_operacion: string;
  datos_equipo: string | null;
  sede: string;
  prioridad: string;
  estado: string;
  fecha_registro: string;
}

/** POST /api/v1/diagnosticos/ → diagnostico-service. */
export interface DiagnosticoResponse {
  idDiagnostico: string;
  idTicket: string;
  estadoReserva: string;
  precioReparacion: number;
  repuestosDescontados: number;
  fecha: string;
}

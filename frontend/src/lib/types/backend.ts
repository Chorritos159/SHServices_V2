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

/** Ticket devuelto por el ticket-service (bandeja del técnico y de entregas). */
export interface TicketPendiente {
  id: string;
  datos_cliente: string;
  documento_cliente: string | null;
  telefono_cliente: string | null;
  tipo_operacion: string;
  datos_equipo: string | null;
  equipo: string | null;
  numero_serie: string | null;
  caracteristicas_falla: string | null;
  precio_estimado: number | null;
  sede: string;
  prioridad: string;
  estado: string;
  fecha_registro: string;
}

/** GET /api/v1/tickets/garantias → ticket-service. */
export interface Garantia {
  id: string;
  id_ticket: string;
  documento_cliente: string | null;
  equipo: string | null;
  numero_serie: string | null;
  descripcion: string | null;
  fecha_entrega: string;
  fecha_vencimiento: string;
  dias: number;
  vigente: boolean;
  dias_restantes: number;
}

/** Usuario/empleado gestionado por el auth-service. */
export interface Usuario {
  usuario: string;
  rol: "ADMIN" | "CAJA" | "TECNICO";
  sede: string;
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

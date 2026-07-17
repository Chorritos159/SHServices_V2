/** Tipos de lectura devueltos por el backend (endpoints GET). */

/** GET /api/v1/almacen/productos → almacen-service. */
export interface ProductoInventario {
  codigo: string;
  nombre: string;
  categoria: string;
  sede: string;
  stock_disponible: number;
  stock_reservado: number;
  precio_unitario: number;
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
  monto_total: number | null;
  vigente: boolean;
  dias_restantes: number;
}

/** GET /api/v1/notificaciones/mis-alertas → notificacion-service. */
export interface Notificacion {
  id: number;
  mensaje: string;
  referencia: string | null;
  evento: string | null;
  created_at: string;
}

/** Usuario/empleado gestionado por el auth-service. */
export interface Usuario {
  usuario: string;
  rol: "ADMIN" | "CAJA" | "TECNICO";
  sede: string;
}

/** Detalle de un repuesto usado en un diagnóstico. */
export interface RepuestoDetalle {
  codigo_repuesto: string;
  descripcion: string;
  cantidad: number;
  precio_unitario: number;
  subtotal: number;
}

/** GET /api/v1/diagnosticos/por-ticket/{id} → desglose para Caja. */
export interface DiagnosticoDetalle {
  idDiagnostico: string;
  idTicket: string;
  fallaDetectada: string;
  manoObra: number;
  totalRepuestos: number;
  precioReparacion: number;
  repuestos: RepuestoDetalle[];
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

/**
 * Asignación de un ticket a un técnico (¿quién atiende qué?).
 * La sirve el diagnostico-service (GET /diagnosticos/asignaciones/...), NO el
 * ticket-service: por eso "Mis Tickets" del técnico sigue funcionando aunque
 * el ticket-service esté caído.
 */
export interface Asignacion {
  id_ticket: string;
  tecnico: string;
  sede: string;
  estado: string; // TOMADO | DIAGNOSTICADO
  datos_cliente: string | null;
  documento_cliente: string | null;
  telefono_cliente: string | null;
  tipo_operacion: string | null;
  equipo: string | null;
  numero_serie: string | null;
  caracteristicas_falla: string | null;
  prioridad: string | null;
  fecha_tomado: string;
}

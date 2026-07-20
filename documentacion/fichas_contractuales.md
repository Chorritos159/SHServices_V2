# Fichas contractuales — endpoints principales

Contrato de las operaciones que sostienen el negocio. Todas se consumen **a
través del API Gateway**, con la convención de path doblado
`/api/v1/{servicio}/{ruta-interna}` (el proxy genérico reenvía
`/api/v1/{svc}/{path}` como `{svc}/api/v1/{path}`).

---

## 1. Autenticación

- **Servicio:** `auth-service`
- **Operación principal:** `POST /api/v1/auth/login`
- **Propósito:** Canjear credenciales por un JWT que lleva rol y sede, que son
  los que gobiernan todo el resto del sistema.
- **Entrada(s):** `{ usuario, password }`
- **Salida(s):** `{ access_token, token_type, expires_in }`
- **Regla(s) relevantes:** El token incluye `rol` (ADMIN/CAJA/TECNICO) y `sede`;
  ningún servicio acepta la sede por el cuerpo de la petición, siempre la lee
  del token. Es la única ruta pública del Gateway y **no** usa path doblado.
- **Error(es) esperables:** `401` credenciales inválidas · `429` demasiados
  intentos (bloqueo por usuario: 5 fallos en 5 min) · `503` auth no disponible.
- **Consumidor(es) probables:** BFF del frontend (guarda el JWT en cookie
  HttpOnly), generadores de carga k6.

---

## 2. Alta de usuarios

- **Servicio:** `auth-service`
- **Operación principal:** `POST /api/v1/auth/auth/usuarios` · `GET` para listar
- **Propósito:** Que el ADMIN dé de alta empleados con su rol y sede.
- **Entrada(s):** `{ usuario, password, rol, sede }`
- **Salida(s):** `{ usuario, rol, sede }`
- **Regla(s) relevantes:** Solo ADMIN. El BFF valida el rol y el auth-service lo
  **revalida** (nunca se confía en que el frontend oculte el botón).
- **Error(es) esperables:** `403` no eres ADMIN · `409` el usuario ya existe ·
  `422` payload inválido.
- **Consumidor(es) probables:** Panel de administración.

---

## 3. Registro de ticket

- **Servicio:** `ticket-service`
- **Operación principal:** `POST /api/v1/tickets/tickets/`
- **Propósito:** Abrir la orden de servicio (SOPORTE) o dejar constancia de una
  venta (VENTA); es la raíz de la trazabilidad de todo el flujo.
- **Entrada(s):** `{ datosCliente, documento_cliente, telefono_cliente,
  tipoOperacion, prioridad, equipo?, numero_serie?, caracteristicas_falla?,
  precio_estimado? }` + cabecera `Idempotency-Key`
- **Salida(s):** `{ idTicket, estado, ... }` (`201`), o `202` si el Gateway lo
  encoló en el outbox.
- **Regla(s) relevantes:** Estados `EN_COLA  EN_DIAGNOSTICO  DIAGNOSTICADO 
  ENTREGADO` (o `RECHAZADO`). Publica `ticket.creado`. Con `Idempotency-Key`, un
  reintento devuelve el ticket original en vez de crear otro.
- **Error(es) esperables:** `422` datos incompletos · `503` servicio no
  disponible · `202` aceptado pero encolado.
- **Consumidor(es) probables:** BFF de recepción, BFF de ventas, k6.

---

## 4. Registro de producto

- **Servicio:** `almacen-service`
- **Operación principal:** `POST /api/v1/almacen/almacen/productos`
- **Propósito:** Dar de alta un repuesto o un producto vendible, con su stock y
  precio, en la sede que corresponde.
- **Entrada(s):** `{ nombre, categoria, sede, stock_inicial, precio_unitario }`
  + cabecera `Idempotency-Key`
- **Salida(s):** `{ codigo, nombre, categoria, sede, stock_disponible,
  stock_reservado, precio_unitario }` (`201`)
- **Regla(s) relevantes:** El código se autogenera con una **secuencia de
  PostgreSQL** (`REP-001`, `PRD-001`) — con `MAX(codigo)+1` había carreras que
  producían 500 bajo concurrencia. Con la misma `Idempotency-Key` **no se crea un
  segundo producto**. Publica `producto.registrado`.
- **Error(es) esperables:** `409` código en uso · `422` payload inválido ·
  `503` pool de conexiones agotado.
- **Consumidor(es) probables:** Panel de almacén, k6.

---

## 5. Reserva de stock

- **Servicio:** `almacen-service`
- **Operación principal:** `POST /api/v1/almacen/almacen/reservar`
- **Propósito:** Apartar repuestos para una reparación sin llegar a sacarlos
  físicamente del inventario todavía.
- **Entrada(s):** `{ codigo_producto, sede, cantidad }` + `Idempotency-Key`
- **Salida(s):** `{ status: "RESERVA_CONFIRMADA", producto, sede,
  stock_disponible, stock_reservado }`
- **Regla(s) relevantes:** Bloqueo pesimista (`SELECT ... FOR UPDATE`) para
  serializar reservas concurrentes y evitar sobreventa. Mueve del disponible al
  reservado (no lo descuenta: eso ocurre al confirmar la entrega). Idempotente:
  varios clics con la misma clave reservan **una sola vez**.
- **Error(es) esperables:** `404` el repuesto no existe en esa sede · `409`
  stock insuficiente · `503` almacén no disponible.
- **Consumidor(es) probables:** `diagnostico-service` (con clave derivada
  `diag-{idTicket}-{codigo}`).

---

## 6. Registro de diagnóstico

- **Servicio:** `diagnostico-service`
- **Operación principal:** `POST /api/v1/diagnosticos/diagnosticos/`
- **Propósito:** Que el técnico deje la falla detectada, el precio y los
  repuestos que va a usar, reservándolos en el mismo acto.
- **Entrada(s):** `{ idTicket, fallaDetectada, mano_obra, precio_reparacion,
  repuestos: [{ codigo_repuesto, cantidad }] }` + `Idempotency-Key`
- **Salida(s):** `{ idDiagnostico, idTicket, estadoReserva, manoObra,
  precioReparacion }` (`201`)
- **Regla(s) relevantes:** La sede sale del token, no del cuerpo. Reserva stock
  **antes** de guardar; si almacén no responde, no se guarda nada (503 honesto).
  `id_ticket` es UNIQUE: un segundo diagnóstico da 409, no un 500 opaco. Publica
  `ticket.diagnosticado`, que es lo que mueve el ticket a DIAGNOSTICADO.
- **Error(es) esperables:** `409` el ticket ya tiene diagnóstico o falta stock ·
  `422` payload inválido · `503` almacén caído.
- **Consumidor(es) probables:** Panel del técnico.

---

## 7. Emisión de comprobante

- **Servicio:** `facturacion-service`
- **Operación principal:** `POST /api/v1/facturas/facturas/` · `GET` para listar
- **Propósito:** Cobrar y emitir el comprobante; en SOPORTE, emitir además la
  garantía de 90 días.
- **Entrada(s):** `{ idTicket, montoManoObra, montoRepuestos, lineas[],
  metodoPago, sede, tipoOperacion, documentoCliente? }` + `Idempotency-Key`
- **Salida(s):** `{ idFactura, idTicket, montoTotal, lineas[], fechaEmision,
  estadoPago, idGarantia }` (`201`)
- **Regla(s) relevantes:** `id_ticket` es UNIQUE — un segundo cobro del mismo
  ticket devuelve **409**, nunca duplica. La garantía **solo se emite en
  SOPORTE**: una venta de mostrador no genera garantía por diseño (por eso el
  listado de facturas hacía falta para que las ventas fueran visibles). Publica
  `ticket.facturado`.
- **Error(es) esperables:** `409` ya facturado · `422` importes inválidos ·
  `503`/`202` facturación no disponible (queda en el outbox).
- **Consumidor(es) probables:** POS de caja, BFF de ventas.

---

## 8. Venta de mostrador (stock atómico)

- **Servicio:** `almacen-service`
- **Operación principal:** `POST /api/v1/almacen/almacen/venta`
- **Propósito:** Descontar de golpe todas las líneas del carrito, o ninguna.
- **Entrada(s):** `{ lineas: [{ codigo_producto, cantidad }] }` +
  `Idempotency-Key`; la sede va en `X-User-Sede`
- **Salida(s):** `{ status: "STOCK_DESCONTADO", sede, lineas[] }`
- **Regla(s) relevantes:** Bloquea las N filas **ordenadas por código** (mismo
  orden en todas las transacciones  no hay deadlocks), valida todas y hace un
  único commit: si la tercera línea no tiene stock, las dos primeras nunca
  salieron y no hay nada que compensar. Solo productos `PRODUCTO_VENTA`.
- **Error(es) esperables:** `401` token sin sede · `404` producto inexistente ·
  `409` sin stock o no vendible en mostrador.
- **Consumidor(es) probables:** BFF de ventas (`/api/ventas`).

---

## 9. Consulta de garantías

- **Servicio:** `facturacion-service`
- **Operación principal:** `GET /api/v1/facturas/garantias/`
- **Propósito:** Que caja compruebe si un equipo sigue en garantía.
- **Entrada(s):** ninguna (o `documento` en `/por-documento/{documento}`)
- **Salida(s):** Lista con `{ id, id_ticket, documento_cliente, equipo,
  numero_serie, fecha_entrega, fecha_vencimiento, vigente, dias_restantes,
  monto_total }`
- **Regla(s) relevantes:** 90 días desde la entrega. `vigente` y
  `dias_restantes` se calculan al vuelo, no se guardan (así no se quedan
  obsoletos). Solo existen garantías de SOPORTE.
- **Error(es) esperables:** `503` facturación no disponible.
- **Consumidor(es) probables:** Vista "Consulta de Garantías y Facturas".

---

## 10. Traza de auditoría

- **Servicio:** `auditoria-service`
- **Operación principal:** `GET /api/v1/auditoria/auditoria/eventos`
- **Propósito:** Reconstruir qué pasó y en qué orden, para soporte y para la
  defensa de la trazabilidad.
- **Entrada(s):** filtros opcionales (ticket, tipo de evento, rango)
- **Salida(s):** Lista de eventos con `{ evento, id_ticket, trace_id,
  timestamp, datos }`
- **Regla(s) relevantes:** Se alimenta por **cola**, no por llamada directa: si
  auditoría está caída, el resto del sistema sigue y los eventos se procesan al
  volver. El `trace_id` es el hilo que une toda una operación entre servicios.
- **Error(es) esperables:** `503` auditoría no disponible.
- **Consumidor(es) probables:** Panel de auditoría, soporte técnico.

---

## 11. Bandeja de notificaciones

- **Servicio:** `notificacion-service`
- **Operación principal:** `GET /api/v1/notificaciones/notificaciones/mis-alertas`
- **Propósito:** Avisar a cada rol de lo que le toca hacer.
- **Entrada(s):** ninguna (el rol sale del token)
- **Salida(s):** Lista de `{ id, rol_destino, mensaje, referencia, leida,
  created_at }`
- **Regla(s) relevantes:** Consume `ticket.*` y `producto.*` con comodines, para
  que un evento nuevo entre sin tocar el binding. **El ADMIN recibe copia de
  todo**; los demás roles, solo lo suyo. Índice compuesto
  `(rol_destino, leida, created_at)` porque la consulta siempre filtra y ordena
  por esos tres campos.
- **Error(es) esperables:** `503` notificaciones no disponible.
- **Consumidor(es) probables:** Campana del panel, todos los roles.

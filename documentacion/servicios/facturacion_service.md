# Servicio: facturacion_service

## Contratos (API Síncrona)
El contrato es la frontera pública del servicio.

| Contrato / Endpoint | Propósito | Notas de gobierno |
| :--- | :--- | :--- |
| `POST /api/v1/facturas/` | Emitir comprobante de pago por mano de obra y repuestos | Genera ID único de factura |

## Menú de Eventos (Asíncronos)
Eventos que el servicio produce o consume.

| Evento | Tipo | Versión | Semántica / Propósito |
| :--- | :--- | :--- | :--- |
| `FacturaGenerada.v1` | Productor | `v1` | Notifica que se cobró un servicio exitosamente, permite cerrar tickets |
| `PagoRechazado.v1` | Productor | `v1` | Notifica un fallo en pasarela de pago o fondos insuficientes |
| `ReparacionCompletada.v1` | Consumidor | `v1` | Permite generar pre-facturas automáticamente cuando el técnico termina |

## Runbook Básico
Qué hacer cuando este servicio falla. Es operativo, breve y accionable.

| Sección | Pregunta | Acción/Detalle Específico |
| :--- | :--- | :--- |
| **Incidente cubierto** | ¿Qué problema atiende? | Facturas no se emiten, clientes no pueden pagar sus equipos reparados. |
| **Detección** | ¿Cómo sé que ocurre? | Alarmas de transacciones fallidas, quejas en caja. |
| **Primeras revisiones** | ¿Qué miro primero? | Integración con pasarela externa de cobro o la base de datos de facturación PostgreSQL. |
| **Acción** | ¿Qué puedo ejecutar? | Si la DB local falla, reiniciar. Si falla pasarela externa, activar "modo manual/offline" para cobrar en efectivo y asentar luego. |
| **Escalamiento** | ¿A quién llamo? | Owner Técnico (Finanzas) / Proveedor Pasarela Externa. |
| **Comunicación** | ¿A quién informo? | Área de Cajas, Contabilidad, Soporte de TI. |

## Changelog Técnico
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa, es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v1.0` | Extracción y creación del servicio de facturación en V2 | Release | Consumir API de emisión de comprobantes |
| `v1.1` | feat(resiliencia S34, Fase 3): idempotencia en `POST /facturas` por clave natural `id_ticket` (ya era `unique` en BD, pero un reintento devolvía un error 500 crudo en vez de la factura existente) — un ticket tiene, a lo sumo, una factura; un reintento del cliente o del Gateway devuelve la MISMA factura, nunca duplica el cobro. Logs migrados al formato mínimo S34 | Compatible | Ninguna (un reintento ahora es seguro) |
| `v1.2` | refactor(logs): el endpoint usa el helper `logger.operacion()` como el resto de servicios (mide `durationMs` solo, una línea por operación, `result=ok`/`duplicado`); se elimina el `logger.info` suelto sin campos S34 y el cronometraje manual | Compatible | Ninguna |
| `v1.3` | feat(dominio): **facturacion pasa a ser dueno de las GARANTIAS** (ADR-0013). La garantia de 90 dias se emite junto con el COBRO (antes la creaba ticket-service al entregar) y se consulta aqui: `GET /garantias/`, `/garantias/por-documento/{doc}` y `/garantias/factura-de/{idTicket}` (comprobante que respalda la garantia). `POST /facturas` acepta los datos del equipo (tipoOperacion, documentoCliente, equipo, numeroSerie, descripcion) y devuelve `idGarantia` + `garantiaVence`. Misma tabla `garantias`: sin migracion de datos | **Aditivo** (los campos nuevos son opcionales) | Consultar garantias en `/api/v1/facturas/garantias/`, ya no en tickets |

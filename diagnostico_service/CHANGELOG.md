# Changelog Técnico - diagnostico_service
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa: es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v0.4` | Prototipo: diagnóstico con un solo repuesto por ticket | Release | Uso interno, no consumible |
| `v2.0` | Creación del servicio para aislar la lógica de diagnósticos | Release | Consumir nuevo contrato de diagnósticos |
| `v2.1` | feat(diagnostico): precio y `repuestos` como array (antes un único repuesto) con descuento de stock | Breaking | Migrar de `repuestoNecesario`/`cantidad` a `repuestos: [{codigo_repuesto, cantidad}]` |
| `v2.2` | feat(diagnostico): campo `mano_obra` independiente del `precio_reparacion` total | Compatible | Nuevo campo opcional en el `POST` |
| `v2.3` | feat(diagnostico): `GET /por-ticket/{idTicket}` con desglose de repuestos y subtotales | Compatible | Nuevo endpoint de solo lectura para mostrar el detalle antes de cobrar |

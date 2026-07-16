# Changelog Técnico - facturacion_service
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa: es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v0.3` | Prototipo: cálculo de total sin persistencia | Release | Uso interno, no consumible |
| `v2.0` | Extracción y creación del servicio de facturación en V2 | Release | Consumir API de emisión de comprobantes |
| `v2.1` | feat(facturacion): health check avanzado con verificación real de PostgreSQL | Compatible | Ninguna |
| `v2.2` | feat(facturacion): `lineas[]` de detalle para ventas POS (además de mano de obra/repuestos) | Compatible | Nuevo campo opcional `lineas` en el `POST /facturas/` |

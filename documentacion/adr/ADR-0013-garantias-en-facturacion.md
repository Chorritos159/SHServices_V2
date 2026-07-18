# ADR-0013 — Las garantías las gestiona facturacion-service, no ticket-service

**Estado:** Aceptada · **Fecha:** 2026-07-18 · **Fase:** S34, Fase 8

## Contexto

La garantía de 90 días se creaba en `ticket-service`, al marcar el ticket como `ENTREGADO`, y se
consultaba desde ahí. Dos problemas:

1. **Disponibilidad**: con `ticket-service` caído, la Consulta de Garantías quedaba vacía. Un
   cliente que viene a reclamar su garantía no puede depender de que el servicio de tickets esté
   sano — es una consulta de negocio crítica y de cara al cliente.
2. **Cohesión de dominio**: la garantía respalda **lo que se cobró** (monto, comprobante,
   vigencia). Pertenece al ciclo económico, no al ciclo de vida operativo del ticket. Tenerla en
   tickets obligaba a pasarle el monto facturado "hacia atrás" desde el BFF.

## Decisión

`facturacion-service` pasa a ser el dueño de las garantías:

- La garantía se **emite junto con el cobro** (`POST /facturas`), no al entregar. Es idempotente:
  si el ticket ya tenía garantía, no crea otra.
- Los datos del equipo (documento, equipo, serie, descripción) **viajan en la petición de cobro**,
  que es quien los tiene en pantalla. Así facturación **no depende** de `ticket-service` para
  emitir la garantía.
- La consulta vive en facturación: `GET /facturas/garantias/`, `…/por-documento/{doc}` y
  `…/factura-de/{idTicket}` (el comprobante que respalda la garantía, para verlo al hacer clic).
- La respuesta del cobro devuelve `idGarantia` y `garantiaVence`, que el comprobante imprime.
- `ticket-service` conserva `/entregar` solo para **confirmar el stock** y cerrar el ticket.

**No hubo migración de datos**: todos los servicios comparten la base `shservices_db`, así que
mover el modelo a facturación apunta a la **misma tabla `garantias`** y las garantías existentes
se siguen viendo igual.

## Consecuencias

**A favor**
- La consulta de garantías (y su comprobante) funciona con `ticket-service` caído — verificado.
- Cohesión: quien cobra es quien respalda lo cobrado; el monto ya no viaja de vuelta al ticket.
- Al abrir una garantía se ve su comprobante sin salir del mismo servicio.

**En contra / límites**
- La garantía nace al **cobrar**, no al **entregar**. En este negocio se cobra y se entrega en el
  mismo acto, así que la diferencia práctica es nula; si algún día se separaran, habría que
  decidir cuál de los dos hitos inicia la vigencia.
- `facturacion-service` gana responsabilidad (cobro + garantía). Se acepta: es el mismo dominio.
- Compartir la tabla entre servicios es un acoplamiento por datos, heredado de la decisión previa
  de usar una sola base. Documentado como brecha en `documentacion/brechas_finales.md`.

## Verificación

`pruebas/08_flujo_completo.py`, paso 5b: la factura devuelve `idGarantia`, la garantía se lista
desde `/facturas/garantias/` y se obtiene su comprobante. Con `docker pause ticket-service`, ambas
consultas siguen respondiendo 200.

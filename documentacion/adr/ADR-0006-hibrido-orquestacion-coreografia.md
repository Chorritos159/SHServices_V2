# ADR-0006 — Enfoque híbrido entre orquestación y coreografía

**Estado:** Aceptada · **Fecha:** 2026-07-18 · **Fase:** Diseño (S34)

## Contexto

Hay dos formas de coordinar servicios y las dos tienen un modo de fallar feo:

- **Orquestación pura:** un coordinador central decide cada paso. Se entiende y
  se depura bien, pero acaba sabiéndolo todo del negocio y se vuelve el
  componente que hay que tocar para cualquier cambio.
- **Coreografía pura:** cada servicio reacciona a eventos. Es flexible y
  desacoplada, pero nadie tiene la foto completa: para saber por qué un ticket
  se quedó a medias hay que reconstruir el flujo leyendo colas.

En SHServices hay operaciones de los dos tipos. Cobrar una venta necesita
control: si el stock no sale, no se cobra. Avisar al técnico no necesita
control ninguno.

## Decisión

Aplicar un **enfoque híbrido**: orquestar el camino crítico y dejar lo
secundario a la coreografía por eventos.

**Se orquesta** (llamadas explícitas, con orden y manejo de error):

- **Venta de mostrador** (`BFF /api/ventas`): ticket → stock → factura. El orden
  no es negociable: el stock se descuenta antes de cobrar, porque cobrar algo
  que no se puede entregar es el error caro.
- **Cobro de un soporte** (`BFF /api/facturas`): factura → cierre del ticket.
- **Diagnóstico** (`diagnostico-service`): reserva de repuestos → guardado.

**Se coreografía** (el productor publica y se desentiende): auditoría,
notificaciones internas y webhooks salientes, sobre los 6 eventos de ADR-0005.

**Dónde vive la orquestación.** En el **BFF del frontend**, no en el Gateway. El
Gateway se mantiene sin lógica de negocio (ADR-0002), y el BFF es el sitio
natural: es el backend de una pantalla concreta y ya tiene el token del usuario.

## Alternativas consideradas

| Alternativa | Por qué no |
| :-- | :-- |
| Orquestador dedicado (motor de sagas) | La herramienta correcta para flujos largos con compensaciones complejas; aquí el flujo más largo tiene 3 pasos y añadiría una pieza de infraestructura sin ganancia |
| Coreografía pura, también para la venta | La cajera necesita una respuesta ahora: "¿cobré o no cobré?". Con eventos tendría que consultar el estado después, y eso en mostrador no funciona |
| Orquestar también las notificaciones | Acopla el negocio a un servicio secundario, justo lo que ADR-0005 evita |

## Consecuencias

- **Positivas:** el flujo principal es legible de arriba abajo en un solo
  archivo y devuelve errores concretos; lo secundario no acopla ni bloquea.
- **Negativas:** hay dos modelos mentales conviviendo. Se compensa con la regla
  explícita de abajo, que dice cuál toca en cada caso.

## Riesgo identificado y mitigación

**Riesgo:** orquestación excesiva, o coreografía difícil de rastrear.

**Mitigación aplicada.**

*Contra la orquestación excesiva* — una regla que se puede aplicar sin discutir:

> Si el usuario **necesita saber el resultado antes de irse**, se orquesta. Si
> el resultado **no cambia lo que el usuario hace ahora**, es un evento.

Por eso la venta se orquesta y la notificación al técnico no. Y por eso incluso
dentro de la venta, el paso que **no** es imprescindible —crear el ticket— es
best-effort: si `ticket-service` está caído la venta se completa igual con su
comprobante y una referencia propia. Verificado en vivo con el servicio pausado.

*Contra la coreografía difícil de rastrear* — cuatro cosas concretas:

1. **`correlationId` único** que nace en el Gateway, viaja en la llamada HTTP,
   se copia al evento como `trace_id` y aparece en los logs de los 8 servicios.
   Un identificador, toda la operación.
2. **Eventos versionados** con contrato escrito (`matriz-auditoria.md`).
3. **Auditoría suscrita a todo** (`ticket.*`, `producto.*`): existe un registro
   central de qué pasó y cuándo, sin tener que leer colas.
4. **ADMIN recibe una copia de toda notificación**, así que hay una vista
   humana del ciclo completo además de la técnica.

La prueba de que esto funciona es `pruebas/08_flujo_completo.py`: recorre los 8
servicios y verifica que los 6 eventos quedaron registrados con su trazabilidad.

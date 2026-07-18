# ADR-0004 — Comunicación síncrona solo en operaciones críticas

**Estado:** Aceptada · **Fecha:** 2026-07-18 · **Fase:** Diseño (S34)

## Contexto

Algunas operaciones no pueden continuar sin saber el resultado de otra: no se
puede registrar un diagnóstico si el almacén no confirmó que hay repuestos, ni
entregar un equipo sin confirmar el stock reservado. Otras, en cambio, no
condicionan nada: que se genere la notificación del técnico o la línea de
auditoría no cambia si el ticket se creó bien.

Tratar ambos casos igual tiene un coste: si todo fuera síncrono, el usuario
esperaría por trabajo que no le importa, y cada servicio en la cadena sumaría su
latencia y su probabilidad de fallo.

## Decisión

Usar **HTTP síncrono solo cuando la respuesta condiciona el flujo**, y eventos
para todo lo demás (ADR-0005).

Llamadas síncronas que existen hoy, y por qué cada una lo es:

| Llamada | Por qué tiene que ser síncrona |
| :-- | :-- |
| `diagnostico → almacen /reservar` | Si no hay repuesto, el diagnóstico **no** debe guardarse |
| `BFF venta → almacen /venta` | Si no hay stock, **no** se puede cobrar |
| `BFF venta → facturacion` | El cliente se va con su comprobante en la mano |
| `BFF cobro → ticket /entregar` | Cierra el ticket y confirma el stock reservado |
| `frontend → auth /login` | Sin token no hay nada que hacer después |

## Alternativas consideradas

| Alternativa | Por qué no |
| :-- | :-- |
| Todo síncrono | Encadena latencias y hace que la caída de un servicio secundario (notificaciones) tumbe una operación principal (crear un ticket) |
| Todo asíncrono | El usuario no sabría si su venta se cobró. Para una operación de mostrador, "te aviso luego" no es una respuesta aceptable |

## Consecuencias

- **Positivas:** el camino crítico es corto y explicable; una caída de auditoría
  o notificaciones **no** impide operar; el usuario recibe confirmación real de
  lo que sí le importa.
- **Negativas:** las operaciones síncronas heredan la disponibilidad de sus
  dependencias. Se compensa con los mecanismos de ADR-0002 y ADR-0011.

## Riesgo identificado y mitigación

**Riesgo:** acumulación de latencia si se encadenan demasiadas llamadas.

**Mitigación aplicada.**

1. **Timeouts explícitos en cada salto**, nunca infinitos: 5s del diagnóstico
   hacia almacén, 8s del Gateway hacia cada servicio, 8s de la entrega del
   outbox. Una llamada lenta se corta, no se acumula.
2. **Cadenas cortas por diseño.** La más larga del sistema tiene 3 saltos
   (BFF → Gateway → servicio → almacén). No hay ninguna de 5 o 6.
3. **Tareas secundarias fuera del camino crítico.** Los eventos se publican con
   `BackgroundTasks` de FastAPI: la respuesta sale al usuario y la publicación
   ocurre después. El usuario no espera por RabbitMQ.
4. **Circuit breaker por servicio**, para que una dependencia enferma haga
   fail-fast en vez de gastar el timeout completo en cada petición.
5. **Presupuesto de latencia medido y publicado** en `documentacion/sla.md`
   (p95 por operación), para que "está lento" sea una afirmación con número.

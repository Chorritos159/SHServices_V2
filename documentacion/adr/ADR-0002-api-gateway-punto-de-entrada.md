# ADR-0002 — API Gateway como único punto de entrada

**Estado:** Aceptada · **Fecha:** 2026-07-18 · **Fase:** Diseño (S34)

## Contexto

Con siete servicios de negocio, cada uno tendría que resolver por su cuenta lo
mismo: validar el JWT, aplicar RBAC, limitar el tráfico, propagar el
`correlationId` y protegerse de dependencias caídas. Repetir eso siete veces
garantiza que se implemente de siete formas distintas y que la séptima tenga el
agujero.

El frontend, además, no debería conocer la topología interna: si mañana el
diagnóstico se parte en dos servicios, la interfaz no tiene por qué enterarse.

## Decisión

Poner un **API Gateway como único punto de entrada** al sistema, responsable de:

1. **Seguridad:** validar el JWT una vez y traducir la identidad ya verificada a
   cabeceras internas (`X-User-Sub`, `X-User-Rol`, `X-User-Sede`).
2. **Enrutamiento:** mapa fijo `MICROSERVICIOS` con la convención
   `/api/v1/{servicio}/{path}`. Un servicio no registrado devuelve 404 y la URL
   destino nunca se arma con texto del usuario (esto es lo que cierra A10/SSRF).
3. **Resiliencia:** circuit breaker por servicio, bulkhead, rate limit, timeouts,
   reintentos con backoff 3s/5s/8s + jitter y outbox de escrituras (ADR-0011).
4. **Adaptación básica:** propagación del `X-Correlation-ID` y normalización de
   errores.

## Alternativas consideradas

| Alternativa | Por qué no |
| :-- | :-- |
| Que el frontend llame directo a cada servicio | El navegador tendría que conocer 7 URLs y guardar el JWT en un sitio accesible por JavaScript. Además, la resiliencia habría que implementarla en el cliente, donde no se puede garantizar |
| Un gateway comercial (Kong, Traefik) | Resuelve enrutamiento y auth, pero el objetivo de la S34 es **demostrar** los mecanismos de resiliencia; con un producto de caja quedarían ocultos tras configuración y no se podrían explicar línea por línea |
| Gateway que además orqueste el negocio | Es justo el riesgo que se quiere evitar (ver abajo) |

## Consecuencias

- **Positivas:** un solo sitio donde se valida identidad y se aplica resiliencia;
  el frontend habla con una sola URL; el `correlationId` nace aquí y por eso una
  operación se puede seguir de punta a punta.
- **Negativas:** es un **punto único de fallo** y, con 1 worker (ADR-0008), el
  primer cuello de botella de throughput. Ambas cosas están registradas en
  `documentacion/brechas_finales.md` con su plan (réplicas detrás de un
  balanceador, con el estado del breaker en Redis).
- Los microservicios **confían** en las cabeceras `X-User-*` sin revalidar el
  JWT. Es una consecuencia directa de esta decisión y está registrada como
  hallazgo A01 abierto en `seguridad/OWASP_Top10.md`.

## Riesgo identificado y mitigación

**Riesgo:** que el Gateway concentre lógica de negocio y se vuelva un cuello de
botella.

**Mitigación aplicada.** El Gateway está limitado a seguridad, enrutamiento,
resiliencia y adaptación: **no conoce ninguna regla de negocio**. No sabe qué es
una garantía, ni cuándo un ticket puede pasar a ENTREGADO, ni cómo se calcula un
total. Cuando un flujo necesitó orquestación real —la venta de mostrador, que
encadena ticket, stock y factura— se puso en el **BFF** del frontend
(`/api/ventas`), no aquí (ADR-0006).

La regla práctica: si para escribir el código hay que preguntarle algo al
negocio, ese código no va en el Gateway.

Sobre el cuello de botella: está **medido**, no supuesto (~85-90 rps sostenidos,
ver `documentacion/registro_de_carga.md`), y el camino de salida está escrito en
ADR-0008.

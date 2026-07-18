# ADR-0003 — Exponer contratos REST/JSON

**Estado:** Aceptada · **Fecha:** 2026-07-18 · **Fase:** Diseño (S34)

## Contexto

Los servicios tienen que hablar entre sí y con el frontend, y el sistema debe
quedar preparado para integraciones futuras (un ERP, una app móvil, el sistema
de un proveedor). Hacía falta un estilo de contrato que fuera legible sin
herramientas especiales y verificable durante la sustentación.

## Decisión

Exponer **contratos REST sobre JSON**, documentados con OpenAPI generado
automáticamente por FastAPI a partir de los modelos Pydantic.

Cada servicio publica su `/docs` (Swagger UI) y su `/openapi.json`. Los modelos
Pydantic **son** el contrato: no hay un documento aparte que se pueda quedar
desactualizado respecto al código, porque el documento se genera del código.

## Alternativas consideradas

| Alternativa | Por qué no |
| :-- | :-- |
| gRPC / Protobuf | Más eficiente y con contrato fuerte, pero no se consume desde un navegador sin una capa extra, y en la sustentación no se puede "abrir y leer" una llamada como se hace con JSON |
| GraphQL | Resuelve el over-fetching del frontend, pero añade una capa de resolvers y complica el rate limiting y la auditoría por operación, que aquí son requisitos de la S34 |
| REST documentado a mano | Es exactamente el riesgo que se quiere evitar: el documento y el código divergen a la primera semana |

## Consecuencias

- **Positivas:** cualquiera puede probar un endpoint desde el navegador; el
  contrato no puede mentir porque se deriva de los modelos; la validación de
  entrada es automática y produce un 422 con el detalle del campo que falta.
- **Negativas:** JSON sobre HTTP es más verboso que un binario; para el volumen
  de este sistema es irrelevante.

## Riesgo identificado y mitigación

**Riesgo:** contratos ambiguos o endpoints mal definidos.

**Mitigación aplicada.** Cada endpoint documenta método, recurso, parámetros,
respuesta, reglas y errores esperables:

- **Modelos Pydantic con `Field(..., description=...)`** en cada campo, de modo
  que el Swagger explica qué es cada cosa y no solo su tipo.
- **Errores homogéneos en los 8 servicios.** Todos responden con la misma forma
  `{error, detalle, trace_id}` gracias a los tres exception handlers de
  `app/core/exceptions.py`. El `detalle` está escrito para una persona ("el
  campo 'documento_cliente' es obligatorio y no llegó"), no para una librería.
- **Códigos con significado acordado y documentado:** 409 para conflicto de
  negocio (stock insuficiente, ticket ya diagnosticado), 422 para payload
  inválido, 503 para dependencia caída, 202 cuando una escritura quedó encolada
  en el outbox.
- **Catálogo de servicios y fichas** (`catalogo-servicios.md`,
  `documentacion/<servicio>.md`) con los contratos y el catálogo de eventos.

Queda pendiente un punto único que agregue los OpenAPI de los 8 servicios; hoy
cada uno publica el suyo.

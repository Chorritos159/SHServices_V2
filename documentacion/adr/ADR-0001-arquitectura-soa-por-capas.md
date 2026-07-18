# ADR-0001 — Arquitectura SOA por capas

**Estado:** Aceptada · **Fecha:** 2026-07-18 · **Fase:** Diseño (S34)

## Contexto

SHServices necesita cubrir un negocio con capacidades claramente distintas:
recepción de equipos, diagnóstico técnico, inventario, cobro, auditoría,
notificaciones e identidad. En la primera versión del proyecto todo eso vivía
junto, y cualquier cambio en una capacidad obligaba a volver a probar y a
desplegar el resto.

El encargo de la S34 exige, además, poder demostrar resiliencia por servicio:
que uno se caiga y el resto siga atendiendo. Eso es imposible si todo comparte
el mismo proceso.

## Decisión

Organizar el sistema como una **arquitectura SOA por capas**, con un servicio
por capacidad de negocio y una separación explícita entre capa de presentación,
capa de acceso (Gateway) y capa de servicios.

El reparto quedó así:

| Capa | Componente | Capacidad de negocio |
| :-- | :-- | :-- |
| Presentación | `frontend` (Next.js + BFF) | Interfaz por rol (Caja, Técnico, Admin) |
| Acceso | `api-gateway` | Seguridad, enrutamiento, resiliencia (ADR-0002) |
| Servicios | `auth-service` | Identidad, roles y sedes |
| | `ticket-service` | Ciclo de vida del ticket |
| | `diagnostico-service` | Diagnóstico y asignación al técnico |
| | `almacen-service` | Inventario, reservas y ventas de mostrador |
| | `facturacion-service` | Cobro y garantías |
| | `auditoria-service` | Registro inmutable de eventos |
| | `notificacion-service` | Alertas internas y webhooks salientes |

## Alternativas consideradas

| Alternativa | Por qué no |
| :-- | :-- |
| Monolito modular | Más simple de operar, pero hace indemostrable el objetivo central de la S34: no se puede "tirar el servicio de almacén" y ver que el resto aguanta, porque no existe como unidad desplegable |
| Microservicios con base de datos por servicio | Es el destino natural, pero multiplica la complejidad operativa (7 motores, consistencia eventual en todas las lecturas) más allá del alcance de esta entrega. Se optó por base central con separación lógica (ADR-0007) |
| Servicios por entidad (un servicio por tabla) | Produce servicios anémicos que se llaman entre sí para cualquier operación útil, justo el "monolito distribuido" que encarece la latencia sin dar independencia real |

## Consecuencias

- **Positivas:** cada capacidad se despliega, escala y falla por separado; la
  demostración de resiliencia es real (se pausa `ticket-service` y una venta de
  mostrador se completa igual, ver ADR-0006); los límites de responsabilidad
  quedan escritos y se pueden auditar.
- **Negativas:** hay duplicación deliberada de código transversal (`app/core/`
  con logging, manejo de errores y salud se repite en cada servicio). SonarQube
  la reporta como deuda; se acepta porque compartir una librería crearía un
  acoplamiento de despliegue que anularía la independencia buscada. Registrado
  en `documentacion/brechas_finales.md`.

## Riesgo identificado y mitigación

**Riesgo:** que los servicios terminen mezclando responsabilidades y se
conviertan en componentes demasiado amplios.

**Mitigación aplicada.** Cada servicio tiene una ficha con su responsabilidad y
sus límites (`documentacion/<servicio>.md`), y cuando una responsabilidad se
detectó en el lugar equivocado se movió con su propia ADR en vez de dejarla
crecer donde estaba:

- Las **asignaciones** salieron de `ticket-service` a `diagnostico-service`
  (ADR-0012): son parte del trabajo del técnico, no del ciclo del ticket.
- Las **garantías** salieron de `ticket-service` a `facturacion-service`
  (ADR-0013): la garantía nace del cobro, no de la entrega.

Ese es el control que evita el servicio-cajón: cuando algo no encaja, se mueve
y se documenta por qué.

# ADR-0007 — Base de datos central organizada por capacidades funcionales

**Estado:** Aceptada con deuda declarada · **Fecha:** 2026-07-18 · **Fase:** Diseño (S34)

## Contexto

El manual dice "base de datos por servicio". Es lo correcto y no se hizo, así
que conviene decir por qué antes que justificarlo después.

Siete motores PostgreSQL significan siete contenedores, siete backups, siete
juegos de credenciales y consistencia eventual en cualquier lectura que cruce
dos capacidades. Para un proyecto que se levanta con `docker compose up` en la
máquina de quien lo sustenta, ese coste operativo se come el tiempo que hace
falta para lo que la S34 realmente evalúa: los mecanismos de resiliencia.

## Decisión

Usar **una base de datos central** (`shservices_db`) con la propiedad de las
tablas repartida por capacidad, y **ninguna** consulta cruzada entre servicios.

| Servicio | Tablas que le pertenecen |
| :-- | :-- |
| auth-service | `usuarios` |
| ticket-service | `tickets`, `idempotencia` |
| diagnostico-service | `diagnosticos`, `asignaciones`, `idempotencia_diagnostico` |
| almacen-service | `inventario` |
| facturacion-service | `facturas`, `garantias` |
| auditoria-service | `auditoria_eventos` |
| notificacion-service | `notificaciones`, `webhook_suscripciones`, `webhook_entregas` |
| api-gateway | `gateway_outbox` |

Cada servicio tiene además su propia tabla de idempotencia (`idempotencia`,
`idempotencia_diagnostico`) en vez de una compartida: la clave de idempotencia
solo tiene sentido dentro del servicio que la procesa, y una tabla común
volvería a acoplar lo que se acaba de separar.

La regla que sostiene la separación: **un servicio solo lee y escribe sus
propias tablas.** Si necesita un dato de otro, lo pide por su API o lo recibe
en un evento. No hay un solo `JOIN` entre tablas de servicios distintos, y eso
es verificable leyendo los modelos: cada servicio declara únicamente los suyos.

## Alternativas consideradas

| Alternativa | Por qué no |
| :-- | :-- |
| Una base por servicio (7 motores) | Es el destino correcto, pero multiplica la operación por 7 y obliga a consistencia eventual en lecturas que hoy son triviales. Fuera del alcance de esta entrega |
| Una base, un esquema PostgreSQL por servicio | **Es la mitigación que corresponde y no está aplicada** (ver abajo). Da separación real con un solo motor: cada servicio con su usuario y permisos solo sobre su esquema |
| Base compartida sin reglas de propiedad | Es el "monolito con pasos extra": cualquier servicio tocando cualquier tabla, y la separación se pierde el primer día |

## Consecuencias

- **Positivas:** un solo motor que levantar, respaldar y observar; las lecturas
  son inmediatas y consistentes; el proyecto arranca con un comando.
- **Negativas:** la separación es **una convención, no una barrera**. Nada en la
  base impide hoy que un servicio consulte la tabla de otro: todos usan las
  mismas credenciales. Se sostiene por disciplina y revisión de código, no por
  permisos.
- Un fallo del motor afecta a todos los servicios a la vez. Registrado en
  `documentacion/brechas_finales.md` junto con la falta de réplica y backup.

## Riesgo identificado y mitigación

**Riesgo:** mezcla de datos entre servicios, o dependencia excesiva de una sola
estructura.

**Mitigación propuesta:** separar por esquemas funcionales (`usuarios`,
`tickets`, `diagnostico`, `almacen`, `facturacion`, `auditoria`), con un usuario
de base de datos por servicio y permisos únicamente sobre su esquema.

**Estado real: NO aplicada.** Las 14 tablas viven hoy en el esquema `public` y
todos los servicios comparten el mismo usuario. Se deja escrito tal cual porque
un documento de arquitectura que describe la mitigación deseada como si
estuviera implementada no sirve para decidir nada.

**Lo que sí está aplicado** y contiene el riesgo mientras tanto:

1. **Propiedad declarada** de cada tabla (la tabla de arriba), revisable.
2. **Cero consultas cruzadas** en el código: cada servicio declara solo sus
   modelos SQLAlchemy y no puede consultar lo que no ha declarado.
3. **Los datos que un servicio necesita de otro viajan en el contrato**, no se
   leen de su tabla. El caso claro: `facturacion-service` recibe los datos del
   equipo en el cuerpo del cobro para emitir la garantía, en vez de ir a buscar
   la fila a `tickets` (ADR-0013). Por eso puede emitir garantías aunque
   `ticket-service` esté caído.

El punto 3 es el que importa: el sistema ya está escrito **como si** las bases
estuvieran separadas. Migrar a esquemas —o a un motor por servicio— es un
cambio de despliegue y permisos, no una reescritura, precisamente porque no hay
ningún `JOIN` que desenredar.

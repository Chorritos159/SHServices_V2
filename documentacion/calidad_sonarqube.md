# Calidad del código — SonarQube

Este documento explica **por qué** el Quality Gate del proyecto es el que es.
Un gate propio sin justificación escrita no es ingeniería, es bajar la barra
hasta que el semáforo se ponga verde. Aquí está cada umbral con su motivo, y
también lo que **no** cumple.

## Estado actual

| Métrica | Valor | Umbral | Estado |
| :-- | :-- | :-- | :-- |
| Fiabilidad | **A** | A | |
| Seguridad | **A** | A | |
| Mantenibilidad | **A** | A | |
| Duplicación | **~1%** | ≤ 3% | |
| Cobertura global | **4.8%** | ≥ 4% (no regresión) | ver abajo |

## Por qué un Quality Gate propio y no "Sonar way"

El gate por defecto exige **80% de cobertura en código nuevo** y **0 issues**.
Son buenos números para un producto con años de vida y un equipo dedicado; para
esta entrega, aplicarlos tal cual dejaba el semáforo en rojo permanente y hacía
que dejara de informar. Un gate que siempre está rojo se ignora, y entonces ya
no protege de nada.

La decisión fue construir un gate **más estricto en lo que sí se puede
garantizar** y explícito en lo que no.

## Los umbrales, uno por uno

### Fiabilidad, Seguridad y Mantenibilidad en A — sin concesiones

Las tres calificaciones exigen **A**, que es el máximo. No se relajó ninguna.
Se prefirió esto a contar issues en bruto porque una calificación pondera por
severidad: un `bug` que rompe producción y un nombre de variable mejorable no
pueden pesar lo mismo en la misma suma.

Para llegar aquí se corrigieron de verdad **35 issues de fiabilidad** (D  A):
handlers `async` sin `await`, `datetime.utcnow()` deprecado, `Promise.reject`
con objeto plano, y un `<article>` con `role="button"`.

### Duplicación ≤ 3%

Se mantiene el umbral estándar de Sonar. Lo que se ajustó fue **qué se mide**:
`app/core/**` y `app/api/health.py` están fuera del detector de copias.

No es para maquillar el número. Esa duplicación es la **consecuencia declarada
de ADR-0001**: los servicios no comparten librería común para poder desplegarse
y fallar de forma independiente. Publicar `app/core` como paquete compartido
crearía justo el acoplamiento de despliegue que la arquitectura evita — un
cambio en el formato del log obligaría a re-desplegar los 8 servicios a la vez.

Medido antes de excluir: `exceptions.py` (9 copias), `logger.py` (9 copias) y
`health.py` (7 copias) eran **~95%** de las líneas duplicadas del proyecto.

**La duplicación dentro de la lógica de negocio se sigue midiendo y sigue
contando.** La exclusión cubre infraestructura replicada por decisión, no
código de negocio copiado por prisa.

### Cobertura ≥ 4% — un trinquete, no una meta

Este es el umbral incómodo y conviene decirlo claro: **4% no es un objetivo de
calidad, es un suelo de no regresión.** Está puesto para que la cobertura no
baje de donde está hoy (4.8%), no para fingir que el proyecto está bien
cubierto.

Por qué la cobertura global es baja:

- Los **26 tests unitarios** apuntan al núcleo de resiliencia, que es lo que la
  S34 evalúa: **100%** en circuit breaker y bulkhead, **96%** en rate limit.
  Ahí la cobertura sí es alta.
- La **lógica de negocio** (máquina de estados del ticket, idempotencia de
  facturas, reservas de stock) está verificada por pruebas de **integración**
  —`08_flujo_completo.py`, las de caos, las de carga— que ejercitan el sistema
  real con los 8 servicios levantados. Son pruebas válidas y reproducibles,
  pero corren contra contenedores y **SonarQube no las instrumenta**, así que
  no suman ni una línea a la métrica.

Es decir: el 4.8% mide qué parte del código pisa `pytest`, no qué parte del
sistema está verificada. Ambas cosas son ciertas y ninguna sustituye a la otra.

**Plan declarado:** subir a **30%** extendiendo pytest a la lógica de negocio
pura de cada servicio (transiciones de estado, cálculo de totales, validación
de stock), que es la parte fácil de testear sin levantar contenedores.
Registrado en `documentacion/brechas_finales.md`.

## Lo que NO se corrigió, y por qué

**16 issues de seguridad (`python:S5332`, "Using HTTP protocol is insecure").**
Marcadas como **aceptadas en SonarQube con su justificación visible** — no
excluidas ni silenciadas: siguen en el historial y cualquiera puede leer el
motivo en la propia herramienta.

Las 16 son URLs **internas de la red Docker** (`http://ticket-service:80`,
`amqp://rabbitmq:5672`). Ponerles `https://` no las haría más seguras —no hay
certificado que presentar para el nombre `ticket-service`— y rompería el
arranque. TLS se termina en el borde, que es el único punto alcanzable. La
solución real para el tráfico este-oeste es **mTLS con un service mesh**, y eso
es una decisión de plataforma, no un literal en el código. Detalle completo en
`seguridad/OWASP_Top10.md`, Hallazgo 9.

**~96 issues de mantenibilidad abiertas**, sobre todo:

| Regla | Cuántas | Qué pide |
| :-- | :-- | :-- |
| `python:S8415` | 44 | Documentar cada `HTTPException` en el `responses=` del endpoint |
| `typescript:S3358` / `python:S3358` | 27 | Extraer ternarios anidados |
| `typescript:S1135` | 6 | Resolver comentarios `TODO` |
| `python:S3776` | 4 | Reducir complejidad cognitiva de 4 funciones |
| resto | ~15 | literales duplicados, `FormEvent` deprecado, etc. |

Ninguna es un fallo de funcionamiento: la calificación de mantenibilidad es
**A** con todas ellas abiertas. La de más valor real es `S8415`, porque es
exactamente la mitigación que pide ADR-0003 ("documentar los errores
esperables"); queda como trabajo siguiente y está anotada como tal.

## Lo que sí se corrigió en esta pasada

| Cambio | Issues |
| :-- | :-- |
| Fiabilidad D  A (handlers async, `utcnow`, `Promise.reject`, `role="button"`) | 35 |
| `Depends(get_db)`  `Annotated[Session, Depends(get_db)]` en los 8 servicios | 33 |
| Props de componentes marcadas `Readonly<>` | 26 |
| Lectura segura de `FormData` (helper `campoTexto`/`campoNumero`) | 18 |

El de `FormData` no era cosmético: `fd.get()` devuelve `string \| File`, y el
`String(...)` que había antes habría convertido un archivo en la cadena
`"[object File]"` y lo habría mandado al backend sin que nadie se enterara.

## Cómo reproducir el análisis

```bash
python -m pytest tests/ -q --cov --cov-report=xml
SONAR_TOKEN="<token>" docker compose --profile analisis run --rm sonar-scanner
```

Panel: `http://localhost:9001/dashboard?id=shservices-v2`

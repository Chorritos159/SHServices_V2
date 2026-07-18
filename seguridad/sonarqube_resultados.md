# Análisis estático — SonarQube

> Corrida del **2026-07-18** (cierre S34) sobre los 8 microservicios + el frontend
> (`sonar-project.properties`). Proyecto: `shservices-v2`, 153 archivos analizados.
> Panel: http://localhost:9001 (usuario `admin`).

## Resultado actual

| Métrica | Valor | Rating |
| :-- | :-- | :-- |
| **Bugs** | **0** | **A** (Fiabilidad) |
| Vulnerabilidades | 16 (todas MINOR) | B (Seguridad) |
| Security Hotspots | 0 | — |
| Code Smells | 193 | **A** (Mantenibilidad) |
| Duplicación | 26.0 % | — |
| Líneas de código | 8,641 | — |
| **Quality Gate** | ERROR (solo por condiciones de *código nuevo*) | |

### Sobre el Quality Gate en ERROR

El Quality Gate por defecto de SonarQube evalúa el **código nuevo** con umbrales
pensados para un proyecto con suite de tests unitarios y CI. Falla por tres
condiciones, ninguna de ellas un defecto de funcionamiento:

| Condición | Valor | Por qué |
| :-- | :-- | :-- |
| `new_coverage` < 80 % | 0 % | **No hay tests unitarios instrumentados.** La verificación es por **pruebas de integración ejecutables** (`pruebas/01`–`10`), que cubren el flujo real end-to-end pero no reportan cobertura a Sonar. Registrado como brecha. |
| `new_duplicated_lines_density` > 3 % | 46 % | Duplicación **estructural** de una arquitectura de microservicios: cada servicio tiene su propio `app/core/` (logger, database, exceptions) y su propio endpoint `/_chaos/crash`. No comparten librería a propósito — así un servicio se despliega y falla de forma independiente. |
| `new_violations` > 0 | 117 | Code smells menores (nombres, complejidad, `TODO`s). Mantenibilidad global sigue en **A**. |

**Lo que sí importa y está en verde: 0 bugs y Fiabilidad A.**

## Bugs corregidos en esta corrida

SonarQube detectó **2 bugs reales** (MAJOR) que se corrigieron:

| Dónde | Problema | Corrección |
| :-- | :-- | :-- |
| `api_gateway/app/main.py` | `asyncio.create_task()` sin guardar la referencia: asyncio solo mantiene una **referencia débil**, así que el recolector de basura podía matar el **worker del outbox** y la **sonda del circuit breaker** en silencio (sin error, sin log) | Las tareas se guardan en un `set` de módulo con `add_done_callback` para limpiarlas al terminar |

`auditoria-service` y `notificacion-service` aparecían con el mismo aviso, pero
**ya guardaban** la referencia correctamente (`_tareas_fondo`): falso positivo de la regla.

## Qué se corrigió en esta corrida

| Antes | Después | Corrección |
| :-- | :-- | :-- |
| 2 bugs (MAJOR) | **0** | `asyncio.create_task()` sin guardar la referencia en `auditoria_service` y `notificacion_service` |
| 22 vulnerabilidades | **15** | 7 Dockerfiles obsoletos eliminados (código muerto que corría como root) |
| Rating Fiabilidad **C** | **A** | consecuencia de los 2 bugs corregidos |

### Bug corregido: tareas de fondo recolectadas por el GC

Los dos consumidores de RabbitMQ se lanzaban así:

```python
asyncio.create_task(iniciar_consumidor())   # ← nadie guarda la referencia
```

El event loop de asyncio solo guarda referencias **débiles** a las tareas:
si nadie más la referencia, el garbage collector puede recolectarla a medio
camino y **el servicio dejaría de consumir eventos en silencio** — sin
error, sin log, sin caerse el contenedor. Es exactamente el tipo de fallo
que no se nota hasta que faltan datos de auditoría.

Corrección: guardar la referencia a nivel de módulo y limpiarla al terminar.

```python
_tareas_fondo: set[asyncio.Task] = set()
tarea = asyncio.create_task(iniciar_consumidor())
_tareas_fondo.add(tarea)
tarea.add_done_callback(_tareas_fondo.discard)
```

### Código muerto eliminado: 7 Dockerfiles obsoletos

Cada servicio tenía su propio `Dockerfile` (sin `USER`, corriendo como
root), pero **el compose no los usaba**: los 8 servicios se construyen con
el `Dockerfile` universal de la raíz (`dockerfile: ../Dockerfile`), que sí
crea y usa `appuser`. Eran código muerto que además ensuciaba el análisis
con 7 hallazgos de seguridad falsos y podía confundir a cualquiera que los
leyera pensando que son los que se despliegan.

## Las 15 vulnerabilidades restantes (todas MINOR, aceptadas)

| # | Regla | Hallazgo | Por qué se acepta |
| :-- | :-- | :-- | :-- |
| 9 | `python:S5332` | "Using HTTP protocol is insecure. Use HTTPS instead." | Son las URLs **internas** entre contenedores (`http://ticket-service:80`), dentro de la red Docker privada, sin salida a internet. TLS entre servicios internos exige una CA y gestión de certificados (o una malla con mTLS): registrado como mejora en `documentacion/brechas_finales.md`, no un riesgo en este despliegue |
| 6 | `python:S5332` | "Using AMQP protocol is insecure. Use AMQPS instead." | Mismo caso: `amqp://rabbitmq:5672` es tráfico interno de la red Docker |

Ninguna de las dos es explotable desde fuera: ningún microservicio de
negocio publica puerto al host (ver `seguridad/OWASP_Top10.md`).

## Cómo reproducir el análisis

Ver `README.md` → **"Análisis estático con SonarQube"**.

## Nota: por qué el escáner no usa un bind mount

En esta máquina, Docker Desktop falla al crear bind mounts **nuevos**
(`mkdir /run/desktop/mnt/host/c: file exists`, un bug conocido que se
arregla reiniciando Docker Desktop). Para no depender de eso, el
procedimiento documentado copia el código dentro del contenedor con
`docker cp` en vez de montarlo. El servicio `sonar-scanner` del compose
(con bind mount) queda como alternativa para cuando el file sharing
funcione.

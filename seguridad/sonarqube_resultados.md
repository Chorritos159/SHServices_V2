# Análisis estático — SonarQube

> Corrida del 2026-07-17 sobre los 8 microservicios + el frontend
> (`sonar-project.properties`). Proyecto: `shservices-v2`.
> Panel: http://localhost:9001 (`admin` / `admin`).

## Resultado actual

| Métrica | Valor | Rating |
| :-- | :-- | :-- |
| **Bugs** | **0** | **A** (Fiabilidad) |
| Vulnerabilidades | 15 (todas MINOR) | B (Seguridad) |
| Security Hotspots | 0 | — |
| Code Smells | 101 | A (Mantenibilidad) |
| Duplicación | 10.4 % | — |
| Líneas de código | 5,766 | — |
| **Quality Gate** | **OK** ✅ | |

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

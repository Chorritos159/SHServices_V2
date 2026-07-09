# Runbook General

Un runbook no explica toda la arquitectura; explica qué hacer cuando algo falla. Es operativo, breve y accionable.

| Sección | Pregunta | Acción/Detalle General |
| :--- | :--- | :--- |
| **Incidente cubierto** | ¿Qué problema atiende? | [Describir falla general, ej. Servicio 503, timeout, base de datos inalcanzable] |
| **Detección** | ¿Cómo sé que ocurre? | [Métricas, revisión de logs, alertas de sistema] |
| **Primeras revisiones** | ¿Qué miro primero? | [Health checks de dependencias, CPU/RAM, correlationId en logs] |
| **Acción** | ¿Qué puedo ejecutar? | [Reintentar, reiniciar servicio, pausar consumo de colas, rollback de despliegue] |
| **Escalamiento** | ¿A quién llamo? | [Owner técnico del servicio / Proveedor de infraestructura] |
| **Comunicación** | ¿A quién informo? | [Soporte nivel 1, negocio, equipos consumidores del servicio] |

---
*Nota: Este runbook provee lineamientos generales. Cada servicio debe escalar incidentes siguiendo esta estructura básica de respuesta.*

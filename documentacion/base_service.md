# Servicio: base_service

## Contratos (API Síncrona)
El contrato es la frontera pública del servicio.

| Contrato / Endpoint | Propósito | Notas de gobierno |
| :--- | :--- | :--- |
| `GET /api/v1/health` | Verificar estado de salud del servicio | Plantilla base, no contiene lógica de negocio |

## Menú de Eventos (Asíncronos)
Eventos que el servicio produce o consume.

| Evento | Tipo | Versión | Semántica / Propósito |
| :--- | :--- | :--- | :--- |
| `ServicioIniciado.v1` | Productor | `v1` | (Plantilla) Emitido al arrancar el contenedor |

## Runbook Básico
Qué hacer cuando este servicio falla. Es operativo, breve y accionable.

| Sección | Pregunta | Acción/Detalle Específico |
| :--- | :--- | :--- |
| **Incidente cubierto** | ¿Qué problema atiende? | (Plantilla) Fallo general de inicio o de liveness probe. |
| **Detección** | ¿Cómo sé que ocurre? | El pod reinicia cíclicamente (CrashLoopBackOff). |
| **Primeras revisiones** | ¿Qué miro primero? | Logs de inicio (startup_event) para ver dependencias faltantes (ej. BD inalcanzable). |
| **Acción** | ¿Qué puedo ejecutar? | Revisar variables de entorno inyectadas, reiniciar despliegue. |
| **Escalamiento** | ¿A quién llamo? | Owner del servicio derivado. |
| **Comunicación** | ¿A quién informo? | DevOps o Infraestructura local. |

## Changelog Técnico
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa, es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v2.0` | Plantilla inicial generada para la arquitectura V2 | Release | Usar como base para nuevos servicios |

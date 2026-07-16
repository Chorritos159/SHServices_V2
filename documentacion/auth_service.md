# Servicio: auth_service

## Contratos (API Síncrona)
El contrato es la frontera pública del servicio.

| Contrato / Endpoint | Propósito | Notas de gobierno |
| :--- | :--- | :--- |
| `POST /api/v1/login` | Validar credenciales de usuario | Emite JWT token (Bearer) con expiración |

## Menú de Eventos (Asíncronos)
Eventos que el servicio produce o consume.

| Evento | Tipo | Versión | Semántica / Propósito |
| :--- | :--- | :--- | :--- |
| `UsuarioBloqueado.v1` | Productor | `v1` | Se dispara tras 5 intentos fallidos de login para prevención de fuerza bruta |
| `SesionIniciada.v1` | Productor | `v1` | Informa que un usuario ha ingresado (útil para invalidar sesiones concurrentes o auditar) |
| `LlaveRotada.v1` | Productor | `v1` | Evento emitido al forzar cambio del SECRET_KEY general |

## Runbook Básico
Qué hacer cuando este servicio falla. Es operativo, breve y accionable.

| Sección | Pregunta | Acción/Detalle Específico |
| :--- | :--- | :--- |
| **Incidente cubierto** | ¿Qué problema atiende? | Fallos HTTP 401/500 al hacer login, bloqueando el acceso a toda la aplicación. |
| **Detección** | ¿Cómo sé que ocurre? | Reportes inmediatos de usuarios, pico de errores en métricas de login. |
| **Primeras revisiones** | ¿Qué miro primero? | Conectividad con la base de datos de usuarios y carga de variables de entorno (SECRET_KEY). |
| **Acción** | ¿Qué puedo ejecutar? | Desplegar versión anterior si el release fue reciente. Verificar expiración de base de datos/creds. Inyectar secretos manualmente si se corrompieron. |
| **Escalamiento** | ¿A quién llamo? | Owner Técnico / DevSecOps. |
| **Comunicación** | ¿A quién informo? | Todo el negocio (impacto P0, nadie puede entrar al sistema). |

## Changelog Técnico
El changelog explica qué cambió y a quién afecta. No es una bitácora extensa, es una señal de evolución controlada.

| Versión | Cambio | Tipo | Acción para consumidores |
| :--- | :--- | :--- | :--- |
| `v1.0` | feat: implementar autenticacion JWT, IAM y configuracion | Release | Integrar API de login |
| `v2.0` | Integración y compatibilidad con V2 | Compatible | Ninguna |
| `v2.1` | feat(observabilidad S34, Fase 3): logs migrados al formato mínimo S34 (`service, correlationId, operation, event, result, durationMs`), consistente con el resto de servicios | Compatible | Ninguna |

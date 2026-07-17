# Brechas finales — SHServices V2 (S34, Fase 6)

Tabla consolidada para el dictamen técnico. Cada fila es una brecha real,
identificada durante la integración (Fases 1-5), no una lista genérica de
"posibles mejoras" — todas tienen evidencia o razonamiento concreto detrás
(ver el documento referenciado en cada una).

| # | Brecha | Riesgo | Acción recomendada | Responsable |
|---|---|---|---|---|
| 1 | Gateway con 1 solo worker Gunicorn (ADR-0001) | Throughput acotado a ~85-90 rps (1 núcleo de CPU); es el primer cuello de botella bajo carga sostenida | Si el throughput lo exige: mover el estado del circuit breaker a Redis (operaciones atómicas) y recién ahí escalar a varios workers/réplicas — nunca volver a varios workers en memoria sin ese cambio | Owner técnico del Gateway |
| 2 | Gateway como punto único de fallo | Si el proceso completo cae, cae todo el tráfico de negocio (no hay redundancia/réplicas en esta entrega) | Desplegar ≥2 réplicas detrás de un balanceador, con el estado de resiliencia ya compartido (depende de la acción #1) | DevOps / Owner de infraestructura |
| 3 | `producto.registrado` no queda auditado | El binding de la cola de auditoría es `ticket.*`; los eventos de inventario no matchean el patrón y no se persisten en `auditoria_eventos` | Agregar un binding adicional `producto.*` en `auditoria-service`, o decidir explícitamente que el inventario no requiere traza de auditoría | Owner técnico de Auditoría/Almacén |
| 4 | Fallas de la S34 no cubiertas por fichas de caos: consumidor lento, base de datos lenta, error de contrato, fallo parcial explícito | Sin verificación en vivo de estos escenarios (ver `documentacion/fichas_falla_controlada.md`, tabla final) | Diseñar fichas dedicadas: mock/proxy delante de PostgreSQL para latencia simulada; contrato inválido explícito en un endpoint; fallo parcial multi-repuesto en diagnóstico | Owner técnico de Resiliencia |
| 5 | Corridas de carga 100k/500k/1M (nivel completo, ventana de 10-15 min) no ejecutadas todavía | El "Registro de carga" (`documentacion/registro_de_carga.md`) está pendiente de llenar con la corrida real conjunta | Ejecutar `python pruebas/03_carga_100k.py` / `04_carga_500k.py` / `05_carga_1M.py` y completar la tabla | Equipo (corrida planificada, no bloqueante para el resto del dictamen) |
| 6 | `.env` con valores de demo, sin rotar | Los secretos usados durante todo el desarrollo (contraseñas, `JWT_SECRET_KEY`) no son aptos para un despliegue real | Rotar todos los secretos antes de cualquier despliegue fuera de la demo/sustentación | Owner de Seguridad |
| 7 | Sin gestor de secretos externo (Vault, AWS Secrets Manager, etc.) | `.env` es un archivo plano en disco (gitignored, pero no cifrado ni auditado) | Aceptable para un proyecto académico de sustentación; evaluar un gestor real antes de producción | Owner de Seguridad |
| 8 | PostgreSQL y RabbitMQ sin réplica ni backup automatizado | Pérdida de datos o indisponibilidad si el contenedor de datos falla (más allá de lo que cubre `restart: always`) | Definir política de backup (`pg_dump` programado) y evaluar réplica de RabbitMQ para un entorno no-demo | DevOps / Owner de infraestructura |
| 9 | Frontend (Next.js) no está dockerizado — corre con `npm run dev` local, fuera de `docker-compose.yml` | El levantamiento del sistema no es 100% "un solo comando"; requiere un paso manual adicional documentado en el README | Agregar un servicio `frontend` a `docker-compose.yml` con build multi-stage para producción | Owner técnico de Frontend |

## Cómo se usa esta tabla

Cada brecha es honesta y verificable — no oculta nada que se haya
encontrado durante el trabajo de las Fases 1-5. Ninguna bloquea la
demostración de los mecanismos de resiliencia exigidos por la S34 (todos
están implementados y verificados en vivo, ver `matriz-resiliencia.md` y
`documentacion/matriz_revision_resiliencia.md`); son limitaciones de
alcance y decisiones explícitas de priorización, documentadas para que el
dictamen las evalúe con la información completa.

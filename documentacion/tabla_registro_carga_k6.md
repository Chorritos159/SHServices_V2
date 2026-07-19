# Registro de carga — corridas con k6

> Generado por `python pruebas_k6/correr.py --fase X`. Cada corrida
> añade una fila; ninguna columna se escribe a mano.

| Fase | Throughput | p95 | p99 | Error rate | CPU/Mem | Queue depth | Resultado |
| :-- | --: | --: | --: | --: | :-- | --: | :-- |
| **humo** | 158 rps | 293 ms | 401 ms | 0.00% | 356% / 521 MiB | 19 | cero errores 500. |  <!-- 20260718_233836 -->
| **100k** | 198 rps | 2386 ms | 3388 ms | 0.00% | 520% / 597 MiB | 21960 | cero errores 500. 3207 respuestas 503/504/429 (3.2%): degradación con contrato, no caídas. 5 escrituras salvadas por el outbox. cola RabbitMQ hasta 21960 mensajes: los consumidores se quedaron atrás. |  <!-- 20260719_001538 -->
| **100k** | 203 rps | 2199 ms | 3053 ms | 0.00% | 518% / 595 MiB | 20620 | cero errores 500. 1409 respuestas 503/504/429 (1.4%): degradación con contrato, no caídas. 1 escrituras salvadas por el outbox. cola RabbitMQ hasta 20620 mensajes: los consumidores se quedaron atrás. |  <!-- 20260719_011438 -->

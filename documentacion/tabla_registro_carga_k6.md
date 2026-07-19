# Registro de carga — corridas con k6

> Generado por `python pruebas_k6/correr.py --fase X`. Cada corrida
> añade una fila; ninguna columna se escribe a mano.

| Fase | Throughput | p95 | p99 | Error rate | CPU/Mem | Queue depth | Resultado |
| :-- | --: | --: | --: | --: | :-- | --: | :-- |
| **500k** | 237 rps | 1503 ms | 1999 ms | 0.00% | 539% / 608 MiB | 85271 | cero errores 500. 29 escrituras salvadas por el outbox. cola RabbitMQ hasta 85271 mensajes: los consumidores se quedaron atrás. |  <!-- 20260719_101025 -->
| **humo** | 150 rps | 272 ms | 375 ms | 0.00% | 392% / 522 MiB | 201 | cero errores 500. cola RabbitMQ hasta 201 mensajes: los consumidores se quedaron atrás. |  <!-- 20260719_105831 -->
| **humo** | 137 rps | 286 ms | 382 ms | 0.00% | 290% / 522 MiB | 80 | cero errores 500. |  <!-- 20260719_110126 -->
| **humo** | 125 rps | 325 ms | 493 ms | 0.00% | 425% / 572 MiB | 90 | cero errores 500. 236 respuestas 503/504/429 (8.5%): degradación con contrato, no caídas. 193 escrituras salvadas por el outbox. |  <!-- 20260719_121905 -->
| **500k** | 230 rps | 1929 ms | 2667 ms | 0.00% | 626% / 697 MiB | 96964 | cero errores 500. 92612 respuestas 503/504/429 (15.0%): degradación con contrato, no caídas. 79450 escrituras salvadas por el outbox. cola RabbitMQ hasta 96964 mensajes: los consumidores se quedaron atrás. |  <!-- 20260719_122045 -->
| **humo** | 88 rps | 452 ms | 654 ms | 0.00% | 369% / 581 MiB | 4 | cero errores 500. 230 respuestas 503/504/429 (8.2%): degradación con contrato, no caídas. 205 escrituras salvadas por el outbox. |  <!-- 20260719_134354 -->
| **humo** | 142 rps | 299 ms | 501 ms | 0.00% | 336% / 522 MiB | 417 | cero errores 500. cola RabbitMQ hasta 417 mensajes: los consumidores se quedaron atrás. |  <!-- 20260719_141053 -->

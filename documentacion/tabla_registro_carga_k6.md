# Registro de carga — corridas con k6

> Generado por `python pruebas_k6/correr.py --fase X`. Cada corrida
> añade una fila; ninguna columna se escribe a mano.

| Fase | Throughput | p95 | p99 | Error rate | CPU/Mem | Queue depth | Resultado |
| :-- | --: | --: | --: | --: | :-- | --: | :-- |
| **humo** | 166 rps | 284 ms | 401 ms | 0.00% | 315% / 518 MiB | 101 | cero errores 500. cola RabbitMQ hasta 101 mensajes: los consumidores se quedaron atrás. |  <!-- 20260718_231245 -->

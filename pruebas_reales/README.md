# Pruebas reales — carga de alto volumen

Carpeta **aparte** de `pruebas/`. Nada de aquí sustituye a lo de allí: las de
`pruebas/` son la suite oficial del proyecto (funcionales, caos, resiliencia)
y siguen siendo la evidencia principal. Esto es para responder **una sola
pregunta**: cuántas peticiones aguanta el sistema cuando se le pide volumen.

## Por qué existe esta carpeta

Comparando con otra implementación que reportó **1.190 rps y 1.000.000 de
peticiones en 14 minutos**, nuestra corrida de 1M dio **28,9 rps**. La
diferencia es de 41×, y antes de tocar nada conviene entender de dónde sale.

### La comparación NO es entre iguales

| | Esa implementación | `pruebas/05_carga_1M.py` |
| :-- | :-- | :-- |
| Operaciones | **Solo lecturas** (GET) | **Mixto: ~70% lecturas + ~30% ESCRITURAS** |
| Qué toca una petición | Consulta y responde | Escribe en PostgreSQL con locks, publica evento en RabbitMQ, dispara consumidores de auditoría y notificaciones |
| Cadena de negocio | — | Incluye crear ticket → tomarlo → diagnosticar (reserva stock) → cobrar |

Una lectura toca un `SELECT` y devuelve JSON. Una escritura de nuestra cadena
abre transacción, bloquea filas de inventario, hace `commit`, publica a
RabbitMQ y despierta a dos consumidores. **No son la misma unidad de trabajo,
así que sus "peticiones por segundo" no son la misma magnitud.**

Comparar ambos números sin decir esto es como comparar la velocidad de dos
coches sin mencionar que uno va vacío y el otro arrastra un remolque.

## Qué hay aquí

| Script | Qué mide |
| :-- | :-- |
| `carga_lecturas.py` | **Solo GET**, sin escrituras. Es la comparación justa con una prueba de lecturas: mide el techo de servicio del sistema en su caso más favorable |

## Cómo se presenta el resultado

Los dos números son verdad y **hay que dar los dos**:

- *"En **lecturas** el sistema sostiene X rps."*
- *"En **carga mixta con escrituras reales** —crear ticket, reservar stock,
  cobrar, emitir eventos— sostiene 29-42 rps, porque cada petición hace un
  trabajo muy distinto."*

Dar solo el primero sería inflar el dato; dar solo el segundo, venderse corto.

## Antes de correr

```bash
docker compose stop sonarqube dozzle          # liberan CPU
python pruebas/limpiar_datos_carga.py --borrar
```

Lo segundo importa **especialmente aquí**: los endpoints de listado devuelven
la tabla entera sin paginar, así que con la base llena de corridas anteriores
cada lectura se vuelve más cara y se mide el volumen de datos, no la carga.

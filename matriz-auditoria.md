# Matriz de Auditoría — SHServices V2

> Gate **G8 · FF-DEP-08** · Trazabilidad de eventos (FF-DEP-05 correlationId · FF-DEP-07 persistencia)
> Última actualización: 2026-07-15

## 1. Modelo de eventos

Coreografía basada en RabbitMQ. Todos los servicios publican al mismo exchange y el
`auditoria-service` los consume y persiste.

- **Exchange:** `tickets.eventos` — tipo `topic`, `durable=True`
- **Cola de auditoría:** `auditoria_tickets_queue` — `durable=True`
- **Binding:** `ticket.*` (captura cualquier evento de ticket)

## 2. Catálogo de eventos auditados

| Evento | Routing key | Publicado por | Datos clave |
|---|---|---|---|
| `TicketCreado.v1` | `ticket.creado` | ticket-service | `idTicket`, `sede` |
| `DiagnosticoRegistrado.v1` | `ticket.diagnosticado` | diagnostico-service | `idDiagnostico`, `idTicket`, `sede`, `estadoReserva`, `precioReparacion` |
| `FacturaGenerada.v1` | `ticket.facturado` | facturacion-service | `idFactura`, `idTicket`, `montoTotal`, `sede` |

## 3. Propagación del `correlationId` (FF-DEP-05)

El identificador de correlación acompaña a la petición de extremo a extremo:

```
Cliente → Gateway (genera/propaga X-Correlation-ID)
        → microservicio (lo lee de la cabecera)
        → evento RabbitMQ (message.correlation_id = trace_id)
        → auditoria-service (lo persiste como trace_id)
```

Cada fila de la traza **siempre** incluye el `trace_id`, lo que permite reconstruir el recorrido
completo de una operación a través de todos los servicios y correlacionarlo con Prometheus/Grafana.

## 4. Persistencia (FF-DEP-07)

Los eventos se guardan en PostgreSQL (tabla `auditoria_eventos`), **no** en memoria. Sobreviven
a reinicios del contenedor.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | Integer (PK) | Autoincremental |
| `evento` | String | Nombre del evento (ej. `TicketCreado.v1`) |
| `trace_id` | String (index) | **correlationId** — siempre presente |
| `sede` | String | Sede asociada |
| `id_ticket` | String | Ticket relacionado |
| `datos_json` | Text | Payload completo del evento (JSON) |
| `recibido_en` | DateTime (UTC) | Momento de consumo |

## 5. Consulta de la traza

- **API:** `GET /api/v1/auditoria/auditoria/eventos` (vía Gateway, rol ADMIN) — devuelve los más recientes primero.
- **Frontend:** Panel **Admin → Auditoría** (tabla con evento, fecha, sede, ticket y trace_id).
- **SQL directo (demostración):**
  ```sql
  SELECT evento, trace_id, sede, id_ticket, recibido_en
  FROM auditoria_eventos ORDER BY id DESC;
  ```

## 6. Ejemplo real (verificado)

```json
{
  "evento": "TicketCreado.v1",
  "trace_id": "1243e495-968e-405a-a97d-8a2150e5860d",
  "sede": "PIURA",
  "idTicket": "TICK-PIU-EA1A",
  "recibido_en": "2026-07-15T17:00:29.737711+00:00",
  "datos": { "idTicket": "TICK-PIU-EA1A", "sede": "PIURA" }
}
```

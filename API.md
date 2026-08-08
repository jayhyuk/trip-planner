# Travel Planner API

## Running the server

The server needs Python 3. It uses only the Python standard library.

```sh
python3 app.py
```

By default, the server listens at `http://127.0.0.1:8000` and connects to the
existing `travel_planner.db` beside `app.py`. Create this database with
`schema.sql` before starting the server. Set `TRAVEL_PLANNER_DB`,
`TRAVEL_PLANNER_HOST`, or `TRAVEL_PLANNER_PORT` to override those defaults.

All responses are JSON. The server permits cross-origin calls, including from
`https://trip-planner-psi-ruby.vercel.app`, for frontend development.

## Interactive API documentation

After starting the server, open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
to use the Swagger UI page. It includes request forms and **Try it out** buttons.
The raw OpenAPI document is also available at `/openapi.json`.

Open `/docs` through the running server, not by double-clicking `swagger.html`;
opening the HTML file directly uses a `file://` URL and cannot make API requests.

## Models

### Trip

```json
{
  "trip_key": "japan-2026",
  "trip_name": "Japan 2026",
  "start_date": "2026-10-01",
  "end_date": "2026-10-10"
}
```

Dates use `YYYY-MM-DD`. `trip_key` is the stable primary key.

### Trip day

```json
{
  "trip_day_id": 1,
  "trip_key": "japan-2026",
  "day_date": "2026-10-01"
}
```

`day_date` must be within the trip's start and end dates.

### Schedule

Every schedule entry has `schedule_id`, `trip_day_id`, `scheduled_time`, and
`schedule_type`. `scheduled_time` uses `HH:MM` or `HH:MM:SS`.

Schedule types and their fields:

| `schedule_type` | Required fields | Optional fields |
| --- | --- | --- |
| `travel_location` | `travel_location_name`, `is_free` | `ticket_purchased`, `detail_link`, `description` |
| `transportation` | `transportation_name` | `is_booked` |
| `accommodation` | `accommodation_name` | `detail_link`, `is_booked` |

All booking and ticket fields are JSON booleans. A free travel location cannot
have `ticket_purchased: true`.

## Endpoints

| Method | URL | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Server health check |
| `GET` | `/api/trips` | List trips |
| `POST` | `/api/trips` | Create a trip |
| `GET` | `/api/trips/{trip_key}` | Get one trip |
| `PUT` | `/api/trips/{trip_key}` | Replace a trip's name and dates |
| `DELETE` | `/api/trips/{trip_key}` | Delete a trip and all child data |
| `GET` | `/api/trips/{trip_key}/days` | List trip days |
| `POST` | `/api/trips/{trip_key}/days` | Add a trip day |
| `PUT` | `/api/days/{trip_day_id}` | Change a trip day date |
| `DELETE` | `/api/days/{trip_day_id}` | Delete a trip day and its schedules |
| `GET` | `/api/days/{trip_day_id}/schedules` | List schedules, ordered by time |
| `POST` | `/api/days/{trip_day_id}/schedules` | Create a schedule |
| `GET` | `/api/schedules/{schedule_id}` | Get a schedule |
| `PUT` | `/api/schedules/{schedule_id}` | Update time and type-specific fields |
| `DELETE` | `/api/schedules/{schedule_id}` | Delete a schedule |

## Request examples

Create a trip:

```http
POST /api/trips
Content-Type: application/json

{
  "trip_key": "japan-2026",
  "trip_name": "Japan 2026",
  "start_date": "2026-10-01",
  "end_date": "2026-10-10"
}
```

Add a day:

```http
POST /api/trips/japan-2026/days
Content-Type: application/json

{
  "day_date": "2026-10-01"
}
```

Add a paid travel location:

```http
POST /api/days/1/schedules
Content-Type: application/json

{
  "scheduled_time": "09:30",
  "schedule_type": "travel_location",
  "travel_location_name": "Senso-ji",
  "is_free": false,
  "ticket_purchased": true,
  "detail_link": "https://example.com/sensoji",
  "description": "Visit the temple."
}
```

Add transportation:

```http
POST /api/days/1/schedules
Content-Type: application/json

{
  "scheduled_time": "13:00",
  "schedule_type": "transportation",
  "transportation_name": "Airport Express",
  "is_booked": false
}
```

Add accommodation:

```http
POST /api/days/1/schedules
Content-Type: application/json

{
  "scheduled_time": "15:00",
  "schedule_type": "accommodation",
  "accommodation_name": "Hotel Sakura",
  "detail_link": "https://example.com/hotel-sakura",
  "is_booked": true
}
```

Update only fields that need to change. For example:

```http
PUT /api/schedules/3
Content-Type: application/json

{
  "is_booked": true
}
```

Schedule type cannot be changed after creation; delete and recreate the entry
when it needs a different type.

## Error responses

Invalid requests return a JSON object such as:

```json
{
  "error": "scheduled_time must use HH:MM or HH:MM:SS format"
}
```

The API uses `400` for invalid data, `404` for missing resources, and `409`
for duplicate keys or other database constraint conflicts.

# Calendar & Data API Service

The `ecu_hockey_calendar.api` package provides a high-performance, asynchronous FastAPI service that exposes public calendar subscriptions, master schedule data feeds, interactive OpenAPI documentation, and administrative diagnostics endpoints.

## 1. Architecture Overview

The API service integrates the calendar generation, data normalization, database persistence, and reconciliation modules into an ASGI application:

```text
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI API Service                      │
├──────────────────────────────┬──────────────────────────────┤
│       Public Endpoints       │   Administrative Endpoints   │
├──────────────────────────────┼──────────────────────────────┤
│ • GET /                      │ • POST /api/v1/sync/trigger  │
│ • GET /calendar.ics (webcal) │ • GET  /api/v1/conflicts     │
│ • GET /api/schedule.json     │                              │
│ • GET /api/schedule.csv      │ Auth: Bearer / X-API-Key     │
│ • GET /health                │                              │
│ • GET /api/v1/sync/status    │                              │
│ • GET /docs & /redoc         │                              │
└──────────────┬───────────────┴──────────────┬───────────────┘
               │                              │
               ▼                              ▼
┌──────────────────────────────┐┌──────────────────────────────┐
│  CalendarFeedService         ││  Database Engine             │
│  ScheduleDataService         ││  SQLAlchemy 2.0 (Sync/Async) │
└──────────────────────────────┘└──────────────────────────────┘
```

### 1.1. Key Characteristics

- **RFC 5545 Compliant**: Valid iCalendar feeds with standard component definitions, deterministic UIDs, Eastern Time (`America/New_York`) `VTIMEZONE` blocks, and customizable alarms.
- **Webcal Protocol**: Seamless subscription URL scheme generation (`webcal://`) and browser redirection support.
- **HTTP Caching**: Robust caching with `Cache-Control: public, max-age=300, stale-while-revalidate=600`, deterministic `ETag` generation, `Last-Modified` timestamps, and `304 Not Modified` conditional response handling (`If-None-Match`, `If-Modified-Since`).
- **Interactive Documentation**: Auto-generated interactive Swagger UI (`/docs`) and ReDoc (`/redoc`) documentation backed by OpenAPI 3.1.
- **Role-Based Protection**: Protected administrative actions secured via HTTP Bearer token or `X-API-Key` headers.

### 1.2. Public Live Production Service

A public, always-on production instance of the API service is hosted on Render at [`https://ecu-hockey-api.onrender.com/`](https://ecu-hockey-api.onrender.com/). You can query the live service immediately without installing or running a local server:

```bash
# Query the live production schedule JSON
curl -fsSL "https://ecu-hockey-api.onrender.com/api/schedule.json?home_only=true" | jq .

# Subscribe directly to the live iCalendar feed
open "webcal://ecu-hockey-api.onrender.com/calendar.ics"

# Check production service diagnostics
curl -fsSL https://ecu-hockey-api.onrender.com/health | jq .
```

For comprehensive details on production topology, see [Live Production Deployment](deployment.md#6-live-production-deployment).

## 2. Running the API Service Locally

### 2.1. Local Development via Uvicorn

Run the service using the Uvicorn ASGI server:

```bash
uv run uvicorn ecu_hockey_calendar.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

### 2.2. Programmatic Execution

Start the server programmatically via the Python API:

```python
from ecu_hockey_calendar.api import run_server

# Start server on localhost port 8000
run_server(host="127.0.0.1", port=8000, reload=True)
```

### 2.3. Application Factory Configuration

Configure the application instance directly using `create_app`:

```python
from ecu_hockey_calendar.api import create_app

app = create_app(
    database_url="sqlite:///ecu_hockey.db",
    admin_token="secret-admin-token-12345",
    enable_cors=True,
)
```

### 2.4. Environment Variables

- `ECU_HOCKEY_ADMIN_TOKEN` or `ADMIN_TOKEN`: Secret administrative token used to authorize protected management routes.
- `DATABASE_URL`: Connection string for PostgreSQL or SQLite storage.

## 3. RFC 5545 iCalendar Feed & webcal Subscriptions

The `/calendar.ics` endpoint provides a standard iCalendar feed compatible with Apple Calendar, Google Calendar, Microsoft Outlook, and Mozilla Thunderbird.

### 3.1. Endpoint Specification

- **Method**: `GET`, `HEAD`
- **Path**: `/calendar.ics`
- **Content-Type**: `text/calendar; charset=utf-8`
- **Content-Disposition**: `inline; filename="ecu-hockey-schedule.ics"`

### 3.2. Query Parameters

| Parameter       | Type      | Default | Description                                                                        |
| :-------------- | :-------- | :------ | :--------------------------------------------------------------------------------- |
| `season`        | `string`  | `None`  | Filter games by season (e.g. `2026-2027`). Defaults to current active season.      |
| `include_past`  | `boolean` | `true`  | When `false`, excludes matches scheduled before the current timestamp.             |
| `alarm_minutes` | `integer` | `60`    | Lead time in minutes for reminder alarms (`VALARM`). Set to `0` to disable alarms. |
| `webcal`        | `boolean` | `false` | When `true`, returns a `307 Temporary Redirect` to the `webcal://` URL.            |

### 3.3. Calendar Client Subscription Instructions

#### 3.3.1. Apple Calendar (macOS & iOS)

1. Open **Calendar** on macOS or iOS.

2. Select **File > New Calendar Subscription...** (or tap **Calendars > Add Calendar > Add Subscription Calendar** on iOS).

3. Enter the subscription URL:

   ```text
   webcal://your-domain.com/calendar.ics
   ```

4. Set the auto-refresh interval (recommended: **Every day** or **Every hour**).

#### 3.3.2. Google Calendar

1. Open [Google Calendar](https://calendar.google.com/).

2. On the left sidebar, click the **+** button next to **Other calendars**.

3. Select **From URL**.

4. Enter the public HTTPS subscription URL:

   ```text
   https://your-domain.com/calendar.ics
   ```

5. Click **Add calendar**.

#### 3.3.3. Microsoft Outlook

1. Open **Outlook on the Web** or desktop Outlook.

2. Navigate to Calendar view and select **Add calendar > Subscribe from web**.

3. Paste the URL:

   ```text
   https://your-domain.com/calendar.ics
   ```

4. Enter a calendar name (e.g., "ECU Ice Hockey") and click **Import**.

### 3.4. iCalendar Features

- **Deterministic UIDs**: Unique identifiers follow the scheme `ECU-HOCKEY-{season}-{hash}@ecuhockey.com`, ensuring calendar clients update existing events without creating duplicates.
- **Timezone Support**: Full `VTIMEZONE` definition for `America/New_York`, handling Daylight Saving Time transitions automatically.
- **Geo Coordinates**: Known rinks (such as The Factory Ice House and Polar Ice Raleigh) include exact latitude and longitude coordinates.
- **Rich Details**: Each event incorporates match status, venue address, and direct ticketing links in the `DESCRIPTION` and `LOCATION` fields.

## 4. Public Master Schedule Data Feeds

Public data feeds provide machine-readable access to canonical schedules in JSON and CSV formats.

### 4.1. JSON Data Feed (`/api/schedule.json`)

- **Method**: `GET`, `HEAD`
- **Path**: `/api/schedule.json`
- **Content-Type**: `application/json`

#### 4.1.1. Query Parameters

| Parameter   | Type      | Default | Description                                                                 |
| :---------- | :-------- | :------ | :-------------------------------------------------------------------------- |
| `season`    | `string`  | `None`  | Filter by season label (e.g. `2026-2027`).                                  |
| `opponent`  | `string`  | `None`  | Case-insensitive substring match on opponent team name.                     |
| `home_only` | `boolean` | `false` | When `true`, returns only home games played at home rinks.                  |
| `status`    | `string`  | `None`  | Filter by game status (`SCHEDULED`, `COMPLETED`, `CANCELLED`, `POSTPONED`). |

#### 4.1.2. Example Request & Response

```bash
curl -s "http://localhost:8000/api/schedule.json?home_only=true" | jq .
```

```json
{
  "meta": {
    "title": "ECU Men's Ice Hockey Master Schedule",
    "season": "2026-2027",
    "total_games": 1,
    "timestamp": "2026-09-08T18:00:00Z",
    "query": {
      "season": null,
      "opponent": null,
      "home_only": true,
      "status": null
    }
  },
  "games": [
    {
      "game_id": "ECU-20261015-UNC",
      "season": "2026-2027",
      "start_time": "2026-10-15T19:00:00-04:00",
      "start_time_utc": "2026-10-15T23:00:00Z",
      "is_time_tbd": false,
      "opponent": "UNC Chapel Hill",
      "opponent_division": "ACHA M2",
      "opponent_conference": "ACCHL",
      "is_home": true,
      "venue": "The Factory Ice House",
      "city": "Wake Forest",
      "state": "NC",
      "result": "SCHEDULED",
      "tickets_url": "https://www.etix.com/ticket/v/13768",
      "theme": "Military Appreciation Night"
    }
  ]
}
```

### 4.2. CSV Data Feed (`/api/schedule.csv`)

- **Method**: `GET`, `HEAD`
- **Path**: `/api/schedule.csv`
- **Content-Type**: `text/csv; charset=utf-8`
- **Content-Disposition**: `attachment; filename="ecu-hockey-schedule.csv"`

Supports identical query filters (`season`, `opponent`, `home_only`, `status`).

#### 4.2.1. Example Request

```bash
curl -s "http://localhost:8000/api/schedule.csv?status=SCHEDULED"
```

Output:

```text
game_id,season,date,time_et,opponent,is_home,venue,city,state,status,result,tickets_url
ECU-20261015-UNC,2026-2027,2026-10-15,19:00,UNC Chapel Hill,True,The Factory Ice House,Wake Forest,NC,SCHEDULED,,https://www.etix.com/ticket/v/13768
```

## 5. Interactive API Documentation

The service exposes self-documenting OpenAPI specifications:

- **Swagger UI**: Accessible at `/docs` for testing endpoints in an interactive browser interface.
- **ReDoc UI**: Accessible at `/redoc` for clean, publication-ready documentation.
- **OpenAPI JSON**: Available at `/openapi.json` for client SDK code generation.
- **Service Index**: `GET /` returns API versioning and endpoint discovery links.

## 6. Health & Diagnostics Telemetry

### 6.1. System Health Check (`/health`)

- **Method**: `GET`, `HEAD`
- **Path**: `/health`

Verifies database connectivity (`SELECT 1`) and data source scraper operational status.

```bash
curl -s http://localhost:8000/health | jq .
```

Response (HTTP 200 OK):

```json
{
  "status": "ok",
  "service": "ecu-hockey-calendar",
  "version": "0.4.0",
  "timestamp": "2026-09-08T18:00:00Z",
  "uptime_seconds": 124.5,
  "database": {
    "status": "connected",
    "connected": true,
    "dialect": "postgresql"
  },
  "scrapers": {
    "status": "operational",
    "sources": [
      {
        "source_code": "ecuhockey",
        "name": "ECU Club Hockey Official Schedule",
        "source_type": "primary_sot",
        "is_active": true,
        "last_scraped_at": "2026-09-08T17:30:00Z"
      }
    ]
  }
}
```

If database connectivity fails, `/health` returns HTTP 503 Service Unavailable with sanitized diagnostic output.

### 6.2. Synchronization Telemetry (`/api/v1/sync/status`)

- **Method**: `GET`
- **Path**: `/api/v1/sync/status`

Reports metrics from recent sync cycles including elapsed execution duration, games created/updated/deleted, and conflict counters:

```bash
curl -s http://localhost:8000/api/v1/sync/status | jq .
```

```json
{
  "current_status": "idle",
  "last_sync": {
    "sync_cycle_id": "sync-20260908173000-abcd1234",
    "status": "SUCCESS",
    "started_at": "2026-09-08T17:30:00Z",
    "completed_at": "2026-09-08T17:30:04Z",
    "duration_ms": 4200,
    "games_created": 2,
    "games_updated": 1,
    "games_deleted": 0,
    "conflicts_detected": 0,
    "error_message": null
  },
  "last_success_at": "2026-09-08T17:30:04Z",
  "total_sync_cycles": 18,
  "sources": [
    {
      "source_code": "ecuhockey",
      "name": "ECU Club Hockey Official Schedule",
      "source_type": "primary_sot",
      "is_active": true,
      "last_scraped_at": "2026-09-08T17:30:00Z"
    }
  ]
}
```

## 7. Administration & Conflict Review

Administrative operations require authentication via HTTP Bearer token or `X-API-Key` header matching the server's configured admin token.

### 7.1. Authentication Methods

Pass the secret token using either method:

```bash
# Method 1: Authorization Bearer header
curl -H "Authorization: Bearer secret-admin-token-12345" ...

# Method 2: X-API-Key header
curl -H "X-API-Key: secret-admin-token-12345" ...
```

Requests without credentials or with invalid tokens receive HTTP 401 Unauthorized.

### 7.2. Trigger On-Demand Synchronization (`POST /api/v1/sync/trigger`)

Initiates an immediate crawl and reconciliation cycle across all or specified data sources:

```bash
curl -X POST "http://localhost:8000/api/v1/sync/trigger?source=ecuhockey" \
  -H "Authorization: Bearer secret-admin-token-12345"
```

Response (HTTP 202 Accepted):

```json
{
  "status": "accepted",
  "message": "Synchronization task initiated.",
  "cycle_id": "sync-20260908180500-e9a1b2c3",
  "source": "ecuhockey"
}
```

### 7.3. Cross-Source Conflict Review (`GET /api/v1/conflicts`)

Inspects unresolved multi-source schedule discrepancies and change history:

```bash
curl -s "http://localhost:8000/api/v1/conflicts?severity=high&requires_review=true" \
  -H "Authorization: Bearer secret-admin-token-12345" | jq .
```

#### 7.3.1. Query Parameters

| Parameter         | Type      | Default | Description                                                     |
| :---------------- | :-------- | :------ | :-------------------------------------------------------------- |
| `severity`        | `string`  | `None`  | Filter by severity (`low`, `medium`, `high`, `critical`).       |
| `game_id`         | `string`  | `None`  | Filter by canonical game identifier.                            |
| `field`           | `string`  | `None`  | Filter by conflicting field name (e.g., `venue`, `start_time`). |
| `requires_review` | `boolean` | `None`  | Filter by whether human review is needed.                       |
| `limit`           | `integer` | `50`    | Maximum number of records to return (1-500).                    |
| `offset`          | `integer` | `0`     | Number of records to skip for pagination.                       |

#### 7.3.2. Example Response

```json
{
  "total_conflicts": 1,
  "filtered_count": 1,
  "limit": 50,
  "offset": 0,
  "conflicts": [
    {
      "conflict_id": "change-101",
      "game_id": "ECU-20261015-UNC",
      "field": "venue",
      "severity": "high",
      "requires_review": true,
      "resolved": false,
      "summary": "Venue discrepancy between primary SOT and conference league portal",
      "field_diffs": [
        {
          "field": "venue",
          "severity": "high",
          "source_a": "The Factory Ice House",
          "source_b": "Orange County Sportsplex"
        }
      ],
      "snapshot_before": { "venue": "The Factory Ice House" },
      "snapshot_after": { "venue": "Orange County Sportsplex" },
      "recorded_at": "2026-09-08T17:30:02Z"
    }
  ]
}
```

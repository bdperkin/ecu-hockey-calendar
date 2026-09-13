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
│ • GET /schedule (HTML View)  │ • GET  /api/v1/conflicts     │
│ • GET /schedule/embed        │                              │
│ • GET /schedule.pdf          │ Auth: Bearer / X-API-Key     │
│ • GET /calendar.ics (webcal) │                              │
│ • GET /api/schedule.json     │                              │
│ • GET /api/schedule.csv      │                              │
│ • GET /feed.rss & .atom      │                              │
│ • GET /site.webmanifest      │                              │
│ • GET /favicon.ico           │                              │
│ • GET /health                │                              │
│ • GET /api/v1/sync/status    │                              │
│ • GET /docs & /redoc         │                              │
└──────────────┬───────────────┴──────────────┬───────────────┘
               │                              │
               ▼                              ▼
┌──────────────────────────────┐┌──────────────────────────────┐
│  CalendarFeedService         ││  Database Engine             │
│  ScheduleDataService         ││  SQLAlchemy 2.0 (Sync/Async) │
│  SyndicationFeedService      ││                              │
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

## 3. Service Status & Landing Directory (/)

The root endpoint (`/`) acts as the front door to the API, serving both a responsive HTML portal for web browsers and structured JSON metadata for API clients via HTTP content negotiation.

### 3.1. Endpoint Specification

- **Method**: `GET`, `HEAD`
- **Path**: `/`
- **Content-Type**: `text/html; charset=utf-8` or `application/json` (negotiated)
- **Header**: `Vary: Accept`

### 3.2. Content Negotiation Rules

Dual-format endpoints follow a deterministic negotiation contract:

| Request Signal                                                     | Resolved Response                                      |
| :----------------------------------------------------------------- | :----------------------------------------------------- |
| `Accept` ranks `text/html` above `application/json` (web browsers) | `text/html; charset=utf-8`                             |
| `Accept: application/json`                                         | `application/json`                                     |
| `Accept: */*` (curl default, HTTP client libraries)                | `application/json` (preserves deploy health gates)     |
| Missing / empty `Accept` header                                    | `application/json`                                     |
| `?format=html` or `?format=json`                                   | Explicit query parameter override (wins over `Accept`) |

Every response includes the `Vary: Accept` HTTP header to prevent reverse proxies and CDNs from poisoning caches across different client types.

### 3.3. HTML Browser View

When visited from a browser, the endpoint renders:

- Service title, status indicator (`ONLINE`), and installed package version.
- Quick action buttons to view the schedule, subscribe to iCal, or open API documentation.
- Prominent calendar subscription box with webcal and HTTP `.ics` URLs and cross-links to the [Calendar Sync Guide](calendar_sync.md).
- Interactive service endpoint directory with direct clickable links to all public and administrative routes.
- Collapsible Developer Data View featuring syntax-highlighted, 2-space indented raw JSON and a "View as JSON" control.

### 3.4. JSON Client Example

```bash
# Query JSON format directly via curl or Accept header
curl -s "http://localhost:8000/" | jq .
```

```json
{
  "name": "ECU Men's Ice Hockey Calendar & Data API",
  "version": "0.7.2",
  "status": "online",
  "endpoints": {
    "calendar_ics": "/calendar.ics",
    "conflicts": "/api/v1/conflicts",
    "docs": "/docs",
    "favicon": "/favicon.ico",
    "feed_atom": "/feed.atom",
    "feed_rss": "/feed.rss",
    "health": "/health",
    "logo_svg": "/static/ecu_hockey_logo.svg",
    "manifest": "/site.webmanifest",
    "openapi": "/openapi.json",
    "redoc": "/redoc",
    "schedule_atom": "/api/schedule.atom",
    "schedule_csv": "/api/schedule.csv",
    "schedule_embed": "/schedule/embed",
    "schedule_html": "/schedule",
    "schedule_json": "/api/schedule.json",
    "schedule_pdf": "/schedule.pdf",
    "schedule_rss": "/api/schedule.rss",
    "sync_status": "/api/v1/sync/status"
  }
}
```

## 4. RFC 5545 iCalendar Feed & webcal Subscriptions

The `/calendar.ics` endpoint provides a standard iCalendar feed compatible with Apple Calendar, Google Calendar, Microsoft Outlook, and Mozilla Thunderbird.

### 4.1. Endpoint Specification

- **Method**: `GET`, `HEAD`
- **Path**: `/calendar.ics`
- **Content-Type**: `text/calendar; charset=utf-8`
- **Content-Disposition**: `inline; filename="ecu-hockey-schedule.ics"`

### 4.2. Query Parameters

| Parameter       | Type      | Default | Description                                                                        |
| :-------------- | :-------- | :------ | :--------------------------------------------------------------------------------- |
| `season`        | `string`  | `None`  | Filter games by season (e.g. `2026-2027`). Defaults to current active season.      |
| `include_past`  | `boolean` | `true`  | When `false`, excludes matches scheduled before the current timestamp.             |
| `alarm_minutes` | `integer` | `60`    | Lead time in minutes for reminder alarms (`VALARM`). Set to `0` to disable alarms. |
| `webcal`        | `boolean` | `false` | When `true`, returns a `307 Temporary Redirect` to the `webcal://` URL.            |

### 4.3. Calendar Client Subscription Instructions

For non-technical, step-by-step instructions, one-click setup, custom reminders, and troubleshooting advice, see the comprehensive [ECU Hockey Calendar Sync Guide](calendar_sync.md).

#### 4.3.1. Apple Calendar (macOS & iOS)

1. Open **Calendar** on macOS or iOS.

2. Select **File > New Calendar Subscription...** (or tap **Calendars > Add Calendar > Add Subscription Calendar** on iOS).

3. Enter the subscription URL:

   ```text
   webcal://ecu-hockey-api.onrender.com/calendar.ics
   ```

4. Set the auto-refresh interval (recommended: **Every day** or **Every hour**).

#### 4.3.2. Google Calendar

1. Open [Google Calendar](https://calendar.google.com/).

2. On the left sidebar, click the **+** button next to **Other calendars**.

3. Select **From URL**.

4. Enter the public HTTPS subscription URL:

   ```text
   https://ecu-hockey-api.onrender.com/calendar.ics
   ```

5. Click **Add calendar**.

#### 4.3.3. Microsoft Outlook

1. Open **Outlook on the Web** or desktop Outlook.

2. Navigate to Calendar view and select **Add calendar > Subscribe from web**.

3. Paste the URL:

   ```text
   https://ecu-hockey-api.onrender.com/calendar.ics
   ```

4. Enter a calendar name (e.g., "ECU Ice Hockey") and click **Import**.

### 4.4. iCalendar Features

- **Deterministic UIDs**: Unique identifiers follow the scheme `ECU-HOCKEY-{season}-{hash}@ecuhockey.com`, ensuring calendar clients update existing events without creating duplicates.
- **Timezone Support**: Full `VTIMEZONE` definition for `America/New_York`, handling Daylight Saving Time transitions automatically.
- **Geo Coordinates**: Known rinks (such as The Factory Ice House and Polar Ice Raleigh) include exact latitude and longitude coordinates.
- **Rich Details**: Each event incorporates match status, venue address, and direct ticketing links in the `DESCRIPTION` and `LOCATION` fields.

## 5. Master Schedule Views & Data Feeds

Public interfaces provide human-readable web schedules and machine-readable data feeds in HTML, JSON, CSV, and PDF formats.

### 5.1. Responsive HTML Schedule View (`/schedule`)

- **Method**: `GET`, `HEAD`
- **Path**: `/schedule`
- **Content-Type**: `text/html; charset=utf-8`

Renders a mobile-first, ECU-branded web interface (`#592a8a` purple and `#fec923` gold) displaying:

- Game date and puck drop time converted to US Eastern Time (`America/New_York`).
- Home vs. Away designation badges.
- Opponent university name, city, state, competition division (e.g., ACHA M2), and conference (ACCHL).
- Venue name, full address, and direct Google Maps directions links.
- Official ticket purchase button for home matches.
- Live match status badges (Scheduled, Final, Cancelled, Postponed) and score results.
- Interactive filter form (`season`, `opponent`, `home_only`, `status`).
- Built-in `@media print` stylesheet for refrigerator printouts and coach clipboards.

### 5.2. Lightweight Embeddable iFrame Widget (`/schedule/embed`)

- **Method**: `GET`, `HEAD`
- **Path**: `/schedule/embed`
- **Content-Type**: `text/html; charset=utf-8`

A stripped-down schedule view specifically designed for embedding into external websites, local sports blogs, student news portals, and community rink pages without site navigation or footer clutter. Includes a one-click **Copy Embed Code** snippet generator:

```html
<iframe src="https://ecu-hockey-api.onrender.com/schedule/embed" width="100%" height="600" frameborder="0"></iframe>
```

### 5.3. JSON Data Feed (`/api/schedule.json`)

- **Method**: `GET`, `HEAD`
- **Path**: `/api/schedule.json`
- **Content-Type**: `application/json`

#### 5.3.1. Query Parameters

| Parameter   | Type      | Default | Description                                                                 |
| :---------- | :-------- | :------ | :-------------------------------------------------------------------------- |
| `season`    | `string`  | `None`  | Filter by season label (e.g. `2026-2027`).                                  |
| `opponent`  | `string`  | `None`  | Case-insensitive substring match on opponent team name.                     |
| `home_only` | `boolean` | `false` | When `true`, returns only home games played at home rinks.                  |
| `status`    | `string`  | `None`  | Filter by game status (`SCHEDULED`, `COMPLETED`, `CANCELLED`, `POSTPONED`). |

#### 5.3.2. Example Request & Response

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

### 5.4. CSV Data Feed (`/api/schedule.csv`)

- **Method**: `GET`, `HEAD`
- **Path**: `/api/schedule.csv`
- **Content-Type**: `text/csv; charset=utf-8`
- **Content-Disposition**: `attachment; filename="ecu-hockey-schedule.csv"`

Supports identical query filters (`season`, `opponent`, `home_only`, `status`).

#### 5.4.1. Example Request

```bash
curl -s "http://localhost:8000/api/schedule.csv?status=SCHEDULED"
```

Output:

```text
game_id,season,date,time_et,opponent,is_home,venue,city,state,status,result,tickets_url
ECU-20261015-UNC,2026-2027,2026-10-15,19:00,UNC Chapel Hill,True,The Factory Ice House,Wake Forest,NC,SCHEDULED,,https://www.etix.com/ticket/v/13768
```

### 5.5. Printable Schedule PDF Grid (`/schedule.pdf`, `/api/schedule.pdf`)

- **Method**: `GET`, `HEAD`
- **Paths**: `/schedule.pdf`, `/api/schedule.pdf`
- **Content-Type**: `application/pdf`
- **Content-Disposition**: `attachment; filename="ecu_hockey_schedule_<season>.pdf"`

Generates a high-contrast, ECU-branded printable schedule grid formatted specifically for parents, coaches, refrigerators, and bench clipboards on standard US Letter paper (`@page { size: letter; margin: 0.5in; }`).

#### 5.5.1. Features & Layout

- **Single / Two-Page Budget**: Compact CSS layout engineered to fit a full season cleanly across 1–2 pages without clipped rows or orphaned headers.
- **Header Banner**: Official ECU Men's Ice Hockey purple and gold banner displaying the active season, generation timestamp, ticket purchase URL, and total game count.
- **Printed Table Columns**:
  - **Date & Day**: Game date with 3-letter day abbreviation (e.g., `Fri, Oct 16, 2026`).
  - **Time (ET)**: Puck drop time in Eastern Time or `TBD`.
  - **Opponent**: Opponent name with division and conference labels (e.g., `UNC Chapel Hill (ACHA M2 - ACCHL)`).
  - **Designation**: High-contrast `HOME` or `AWAY` badge.
  - **Venue & City**: Arena name and city/state location.
  - **Result / Notes**: Final score and result for completed games (e.g., `W 4 - 2`), status annotations (e.g., `POSTPONED`), or blank `[  —  ]` score-tracking boxes for upcoming matches.
- **Print Optimization**: Repeated table headers on subsequent pages (`thead { display: table-header-group; }`), page numbers via CSS paged media counters (`Page X of Y`), and forced avoidance of row breaks (`tr { break-inside: avoid; }`).
- **HTTP Caching**: Full conditional caching support (`ETag`, `Last-Modified`, and `304 Not Modified` via `If-None-Match` and `If-Modified-Since`).

#### 5.5.2. Query Parameters

Supports the standard schedule query filters:

| Parameter   | Type      | Default | Description                                                                 |
| :---------- | :-------- | :------ | :-------------------------------------------------------------------------- |
| `season`    | `string`  | `None`  | Filter by season label (e.g. `2026-2027`). Defaults to all seasons.         |
| `opponent`  | `string`  | `None`  | Case-insensitive substring match on opponent team name.                     |
| `home_only` | `boolean` | `false` | When `true`, includes only home matches.                                    |
| `status`    | `string`  | `None`  | Filter by game status (`SCHEDULED`, `COMPLETED`, `CANCELLED`, `POSTPONED`). |

#### 5.5.3. Example Request

```bash
# Download printable PDF schedule for the 2026-2027 season
curl -fsSL -o schedule.pdf "http://localhost:8000/schedule.pdf?season=2026-2027"

# Inspect PDF cache headers without downloading payload
curl -I "http://localhost:8000/schedule.pdf"
```

### 5.6. RSS 2.0 Syndication Feed (`/feed.rss`, `/api/schedule.rss`)

- **Method**: `GET`, `HEAD`
- **Paths**: `/feed.rss`, `/api/schedule.rss`
- **Content-Type**: `application/rss+xml; charset=utf-8`
- **Content-Disposition**: `inline; filename="ecu-hockey-schedule.rss"`

Generates a standardized RSS 2.0 XML schedule syndication feed for sports media, student newspapers, fan RSS readers, and automated pipelines.

#### 5.6.1. Features & Schema

- **Standard RSS 2.0 Structure**: Clean channel metadata, item elements with `<title>`, `<link>`, `<description>`, `<content:encoded>`, `<pubDate>`, and deterministic non-permalink `<guid>` (`urn:ecu-hockey:game:<game_id>`).
- **Category Tags**: Tagged with `<category>ACCHL</category>`, `<category>ACHA M2</category>`, `<category>Hockey</category>`, and `<category>ECU</category>`.
- **Informative Titles**: Formatted with match outcome for completed matches (`Final: ECU 4, UNC Chapel Hill 2`), status annotations (`Postponed: ...`), or scheduled designation (`ECU Hockey vs NC State (Home Match)`).
- **Rich Descriptions**: Includes Eastern Time puck drop, venue name, address, designation, result status, ticketing URL, and opponent conference info.
- **HTTP Caching**: Full conditional caching support with `Cache-Control: public, max-age=300, stale-while-revalidate=600`, `ETag`, `Last-Modified`, and `304 Not Modified` responses.

#### 5.6.2. Query Parameters

| Parameter     | Type      | Default | Description                                                             |
| :------------ | :-------- | :------ | :---------------------------------------------------------------------- |
| `season`      | `string`  | `None`  | Filter by season label (e.g. `2026-2027`). Defaults to all seasons.     |
| `opponent`    | `string`  | `None`  | Case-insensitive substring match on opponent team name.                 |
| `home_only`   | `boolean` | `false` | When `true`, returns only home fixtures hosted by ECU.                  |
| `future_only` | `boolean` | `false` | When `true`, filters to only future upcoming fixtures.                  |
| `status`      | `string`  | `None`  | Filter by game status (`scheduled`, `final`, `cancelled`, `postponed`). |

#### 5.6.3. Example Request

```bash
# Retrieve RSS 2.0 schedule feed
curl -fsSL "http://localhost:8000/feed.rss?home_only=true"

# Inspect RSS caching headers
curl -I "http://localhost:8000/feed.rss"
```

### 5.7. Atom 1.0 Syndication Feed (`/feed.atom`, `/api/schedule.atom`)

- **Method**: `GET`, `HEAD`
- **Paths**: `/feed.atom`, `/api/schedule.atom`
- **Content-Type**: `application/atom+xml; charset=utf-8`
- **Content-Disposition**: `inline; filename="ecu-hockey-schedule.atom"`

Provides an Atom 1.0 XML schedule syndication feed conforming strictly to RFC 4287 for syndication platforms and feed readers. Supports the same filtering options and HTTP caching headers as the RSS 2.0 feed.

#### 5.7.1. Example Request

```bash
# Retrieve Atom 1.0 schedule feed
curl -fsSL "http://localhost:8000/feed.atom?future_only=true"

# Conditional request with ETag
curl -I -H 'If-None-Match: "3277839352210134707"' "http://localhost:8000/feed.atom"
```

### 5.8. Progressive Web App Manifest (`/site.webmanifest`)

- **Method**: `GET`, `HEAD`
- **Path**: `/site.webmanifest`
- **Content-Type**: `application/manifest+json`

Provides a standard W3C Web App Manifest enabling browsers and mobile operating systems to install the ECU Hockey web interface as a Progressive Web App (PWA).

Features:

- Application name: "ECU Men's Ice Hockey Calendar" (short name: "ECU Hockey").
- Theme color (`#592a8a`) and background color (`#ffffff`).
- Multi-resolution icon declarations (`192x192` and `512x512` PNGs, plus SVG any-resolution source).
- Standalone display mode with portrait-primary orientation.

```bash
curl -fsSL http://localhost:8000/site.webmanifest | jq .
```

### 5.9. Multi-Resolution Favicons (`/favicon.ico`)

- **Method**: `GET`, `HEAD`
- **Path**: `/favicon.ico`
- **Content-Type**: `image/x-icon`

Serves an embedded, multi-resolution binary ICO icon file containing standard 16x16, 32x32, and 48x48 icon payloads. Web browsers automatically request `/favicon.ico` by default for bookmarks, browser tabs, and history lists. Additional static PNG favicons (`favicon-16x16.png`, `favicon-32x32.png`) and touch icons (`apple-touch-icon.png`) are hosted under `/static/`.

```bash
# Verify favicon headers
curl -I http://localhost:8000/favicon.ico
```

## 6. Interactive API Documentation

The service exposes self-documenting OpenAPI specifications:

- **Swagger UI**: Accessible at `/docs` for testing endpoints in an interactive browser interface.
- **ReDoc UI**: Accessible at `/redoc` for clean, publication-ready documentation.
- **OpenAPI JSON**: Available at `/openapi.json` for client SDK code generation.
- **Service Index**: `GET /` returns API versioning and endpoint discovery links.

## 7. Health & Diagnostics Telemetry

### 7.1. System Health Check (`/health`)

- **Method**: `GET`, `HEAD`
- **Path**: `/health`
- **Content-Type**: `text/html; charset=utf-8` or `application/json` (negotiated)
- **Header**: `Vary: Accept`
- **Query Parameters**: `format` (`html` or `json`, optional override)

Verifies database connectivity (`SELECT 1`) and data source scraper operational status.

#### 7.1.1. Dual-Format Content Negotiation

- **Browser View (`text/html`)**: Renders a styled, responsive health dashboard with service status pills, uptime metrics, database dialect connectivity cards, scraper heartbeat timestamps, and a collapsible developer JSON drawer.
- **Machine Client View (`application/json`)**: Default format for `curl`, deployment readiness probes, and uptime monitoring tools (`Accept: */*` or `Accept: application/json`).
- **Format Override**: Appending `?format=html` or `?format=json` forces the respective serialization format.

```bash
# Query JSON telemetry directly
curl -s http://localhost:8000/health | jq .

# Render HTML dashboard
curl -s "http://localhost:8000/health?format=html"
```

Response (HTTP 200 OK):

```json
{
  "status": "ok",
  "service": "ecu-hockey-calendar",
  "version": "0.7.2",
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

If database connectivity fails, `/health` returns HTTP 503 Service Unavailable with sanitized diagnostic output in both HTML and JSON.

### 7.2. Synchronization Telemetry (`/api/v1/sync/status`)

- **Method**: `GET`
- **Path**: `/api/v1/sync/status`
- **Content-Type**: `text/html; charset=utf-8` or `application/json` (negotiated)
- **Header**: `Vary: Accept`
- **Query Parameters**: `format` (`html` or `json`, optional override)

Reports metrics from recent sync cycles including elapsed execution duration, games created/updated/deleted, and conflict counters:

#### 7.2.1. Dual-Format Content Negotiation

- **Browser View (`text/html`)**: Displays an interactive telemetry dashboard with sync cycle metrics, execution duration badges, records created/updated/deleted counters, scraper status cards, and raw JSON inspection.
- **Machine Client View (`application/json`)**: Default format for CLI and automated monitoring pipelines.

```bash
# Query sync status JSON
curl -s http://localhost:8000/api/v1/sync/status | jq .

# View sync status HTML portal
open "http://localhost:8000/api/v1/sync/status?format=html"
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

## 8. Administration & Conflict Review

Administrative operations require authentication via HTTP Bearer token or `X-API-Key` header matching the server's configured admin token.

### 8.1. Authentication Methods

Pass the secret token using either method:

```bash
# Method 1: Authorization Bearer header
curl -H "Authorization: Bearer secret-admin-token-12345" ...

# Method 2: X-API-Key header
curl -H "X-API-Key: secret-admin-token-12345" ...
```

Requests without credentials or with invalid tokens receive HTTP 401 Unauthorized.

### 8.2. Trigger On-Demand Synchronization (`POST /api/v1/sync/trigger`)

Initiates an immediate crawl and reconciliation cycle across all or specified data sources when an execution handler is configured:

```bash
curl -X POST "http://localhost:8000/api/v1/sync/trigger?source=ecuhockey" \
  -H "Authorization: Bearer secret-admin-token-12345"
```

Response when handler is wired (HTTP 202 Accepted):

```json
{
  "status": "accepted",
  "sync_cycle_id": "sync-20260908180500-e9a1b2c3",
  "target_source": "ecuhockey",
  "timestamp": "2026-09-08T18:05:00.000000+00:00",
  "message": "Synchronization cycle triggered successfully."
}
```

Response when unconfigured (HTTP 501 Not Implemented):

```json
{
  "detail": "On-demand synchronization trigger is not implemented or configured in this deployment environment. Scheduled synchronization runs via external cron."
}
```

### 8.3. Cross-Source Conflict Review (`GET /api/v1/conflicts`)

- **Method**: `GET`, `HEAD`
- **Path**: `/api/v1/conflicts`
- **Content-Type**: `text/html; charset=utf-8` or `application/json` (negotiated)
- **Header**: `Vary: Accept`
- **Authentication**: HTTP Bearer token or `X-API-Key` header

Inspects unresolved multi-source schedule discrepancies and change history.

#### 8.3.1. Dual-Format Content Negotiation

- **Browser View (`text/html`)**: Renders an administrative conflict resolution dashboard featuring interactive filter controls (`severity`, `game_id`, `field`, `requires_review`), paginated table rows with severity badges (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`), visual diff badges, and a developer JSON inspection modal.
- **Machine Client View (`application/json`)**: Standard JSON format for administrative automation scripts and auditing CLI commands.

```bash
# Query conflicts JSON
curl -s "http://localhost:8000/api/v1/conflicts?severity=high&requires_review=true" \
  -H "Authorization: Bearer secret-admin-token-12345" | jq .

# Render administrative conflict review dashboard in HTML
curl -s "http://localhost:8000/api/v1/conflicts?format=html" \
  -H "Authorization: Bearer secret-admin-token-12345"
```

#### 8.3.2. Query Parameters

| Parameter         | Type      | Default | Description                                                     |
| :---------------- | :-------- | :------ | :-------------------------------------------------------------- |
| `severity`        | `string`  | `None`  | Filter by severity (`low`, `medium`, `high`, `critical`).       |
| `game_id`         | `string`  | `None`  | Filter by canonical game identifier.                            |
| `field`           | `string`  | `None`  | Filter by conflicting field name (e.g., `venue`, `start_time`). |
| `requires_review` | `boolean` | `None`  | Filter by whether human review is needed.                       |
| `limit`           | `integer` | `50`    | Maximum number of records to return (1-500).                    |
| `offset`          | `integer` | `0`     | Number of records to skip for pagination.                       |
| `format`          | `string`  | `None`  | Explicit format override (`html` or `json`).                    |

#### 8.3.3. Example Response

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

## 9. Content-Negotiated Error Responses

The API implements deterministic HTTP content negotiation for client and server error responses, ensuring that interactive web browsers receive styled, helpful HTML error pages while automated API consumers, deployment health probes, and CLI tools continue to receive byte-for-byte identical JSON error payloads.

### 9.1. Error Negotiation Contract

Error responses adhere to the exact same negotiation rules as the root status endpoint:

| Client Request Signal                                              | Resolved Error Format                                  |
| :----------------------------------------------------------------- | :----------------------------------------------------- |
| `Accept` ranks `text/html` above `application/json` (web browsers) | `text/html; charset=utf-8`                             |
| `Accept: application/json`                                         | `application/json`                                     |
| `Accept: */*` (default `curl`, monitoring probes)                  | `application/json`                                     |
| Absent / missing `Accept` header                                   | `application/json`                                     |
| `?format=html` or `?format=json`                                   | Explicit query parameter override (wins over `Accept`) |

All negotiated error responses set `Vary: Accept` to guarantee reverse proxy and CDN caches do not serve HTML to automated clients or JSON to browsers.

### 9.2. Supported HTTP Status Codes

#### 9.2.1. 401 Unauthorized

- **JSON Body**: `{"detail": "Missing administrative authentication credentials."}`
- **HTML Page**: Explains authentication requirements and displays code examples for both `Authorization: Bearer <ADMIN_TOKEN>` and `X-API-Key: <ADMIN_TOKEN>` headers without disclosing internal secrets.
- **Header Preservation**: `WWW-Authenticate: Bearer` is preserved in both formats.

#### 9.2.2. 404 Not Found

- **JSON Body**: `{"detail": "Not Found"}`
- **HTML Page**: Plain-language explanation that the resource or page does not exist, with helpful navigation cards directing visitors to `/`, `/schedule`, `/health`, and `/docs`.

#### 9.2.3. 405 Method Not Allowed

- **JSON Body**: `{"detail": "Method Not Allowed"}`
- **HTML Page**: Informs the user that the HTTP method requested is not permitted on the target route.

#### 9.2.4. 422 Unprocessable Entity (Validation Error)

- **JSON Body**: `{"detail": [{"loc": ["query", "home_only"], "msg": "Input should be a valid boolean...", "type": "bool_parsing", "input": "maybe"}]}`
- **HTML Page**: Renders a clear, human-readable table detailing each failed field, the specific validation error message, the supplied invalid input value, and the underlying validation rule type.

#### 9.2.5. 500 Internal Server Error

- **JSON Body**: `{"detail": "Internal Server Error"}`
- **HTML Page**: Sanitized server error page stating that an unexpected error occurred and that the issue has been captured in server telemetry.
- **Security Invariant (CodeQL Alert #14)**: No exception class names, tracebacks, internal file paths, or sensitive credentials are ever transmitted to the client in either format. Full diagnostics are recorded strictly in server-side application logs.

### 9.3. Caching & Protocol Integrity

- **304 Not Modified**: Conditional caching responses generated via `If-None-Match` or `If-Modified-Since` on calendar and schedule endpoints are never routed through error handlers and always return an empty response body.
- **HEAD Requests**: Error responses to `HEAD` requests preserve identical HTTP status codes, `Content-Type`, and header sets while returning an empty response body.

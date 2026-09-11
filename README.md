# ecu-hockey-calendar

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Subscribe to the Schedule](#1-subscribe-to-the-schedule)
- [2. System Architecture](#2-system-architecture)
- [3. Features](#3-features)
- [4. Installation](#4-installation)
- [5. Quickstart](#5-quickstart)
  - [5.1. Managing and Exporting Schedules Manually](#51-managing-and-exporting-schedules-manually)
  - [5.2. Ingesting Feeds from Live Web Sources](#52-ingesting-feeds-from-live-web-sources)
  - [5.3. Reconciling Feeds & Resolving Conflicts](#53-reconciling-feeds--resolving-conflicts)
  - [5.4. Relational Persistence & Migrations](#54-relational-persistence--migrations)
  - [5.5. Detecting Schedule Changes & Alerting](#55-detecting-schedule-changes--alerting)
  - [5.6. Calendar Feeds & REST API Service](#56-calendar-feeds--rest-api-service)
    - [5.6.1. Calendar Subscription (Apple, Google, Outlook)](#561-calendar-subscription-apple-google-outlook)
    - [5.6.2. Querying Public Schedule Feeds](#562-querying-public-schedule-feeds)
    - [5.6.3. Health Probes & Administration](#563-health-probes--administration)
  - [5.7. Command-Line Interface (`ecu-hockey`)](#57-command-line-interface--ecu-hockey)
    - [5.7.1. Subcommand Reference Table](#571-subcommand-reference-table)
- [6. Database Schema Migrations](#6-database-schema-migrations)
- [7. Production Deployment & Containerization](#7-production-deployment--containerization)
  - [7.1. Live Production Deployment (`ecu-hockey-api.onrender.com`)](#71-live-production-deployment--ecu-hockey-apionrendercom)
  - [7.2. Published Container Images (`ghcr.io`)](#72-published-container-images--ghcrio)
  - [7.3. Local Container Orchestration with Docker Compose](#73-local-container-orchestration-with-docker-compose)
  - [7.4. Scheduled Ingestion & Static Feeds Automation](#74-scheduled-ingestion--static-feeds-automation)
  - [7.5. Automated Continuous Deployment](#75-automated-continuous-deployment)
- [8. Development and Contributing](#8-development-and-contributing)
  - [8.1. Quick Setup](#81-quick-setup)
- [9. Security](#9-security)
- [10. License](#10-license)

______________________________________________________________________

<!--TOC-->

[![CI](https://github.com/bdperkin/ecu-hockey-calendar/actions/workflows/ci.yml/badge.svg)](https://github.com/bdperkin/ecu-hockey-calendar/actions/workflows/ci.yml)
[![CodeQL](https://github.com/bdperkin/ecu-hockey-calendar/actions/workflows/codeql.yml/badge.svg)](https://github.com/bdperkin/ecu-hockey-calendar/actions/workflows/codeql.yml)
[![Dependency Review](https://github.com/bdperkin/ecu-hockey-calendar/actions/workflows/dependency-review.yml/badge.svg)](https://github.com/bdperkin/ecu-hockey-calendar/actions/workflows/dependency-review.yml)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/bdperkin/ecu-hockey-calendar/main.svg)](https://results.pre-commit.ci/latest/github/bdperkin/ecu-hockey-calendar/main)
[![Pages](https://github.com/bdperkin/ecu-hockey-calendar/actions/workflows/pages.yml/badge.svg)](https://bdperkin.github.io/ecu-hockey-calendar/)
[![codecov](https://codecov.io/gh/bdperkin/ecu-hockey-calendar/graph/badge.svg?token=)](https://codecov.io/gh/bdperkin/ecu-hockey-calendar)

[![GitHub Release](https://img.shields.io/github/v/release/bdperkin/ecu-hockey-calendar?logo=github)](https://github.com/bdperkin/ecu-hockey-calendar/releases)
[![GHCR Package](https://img.shields.io/badge/container-ghcr.io-blue?logo=docker&logoColor=white)](https://github.com/bdperkin/ecu-hockey-calendar/pkgs/container/ecu-hockey-calendar)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-%23FE5196?logo=conventionalcommits&logoColor=white)](https://www.conventionalcommits.org/)
[![Security Policy](https://img.shields.io/badge/security-SECURITY.md-red?logo=github)](https://github.com/bdperkin/ecu-hockey-calendar/blob/main/SECURITY.md)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](https://github.com/bdperkin/ecu-hockey-calendar/blob/main/CODE_OF_CONDUCT.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[![Python Version](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-d71e00?logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Type Checked with ty](https://img.shields.io/badge/type_checker-ty-blueviolet)](https://github.com/astral-sh/ty)
[![Documentation](https://img.shields.io/badge/docs-Sphinx-blue)](https://bdperkin.github.io/ecu-hockey-calendar/)

East Carolina University - Men's Ice Hockey Team - Calendar.

A modern, robust Python package for aggregating, reconciling, and distributing collegiate ice hockey schedules across web crawlers, relational persistence, conflict resolution, multi-channel webhook alerting, and calendar exports (RFC 5545 iCalendar, JSON, CSV).

## 1. Subscribe to the Schedule

Never miss an East Carolina University Men's Ice Hockey matchup! Subscribe to the live schedule feed in your calendar application for automated updates, rescheduled match notices, and puck drop reminders:

- **Apple Calendar (iPhone, iPad, Mac)**: [Instant One-Click Subscription](https://ecu-hockey-api.onrender.com/calendar.ics?webcal=true) or use `webcal://ecu-hockey-api.onrender.com/calendar.ics`
- **Google Calendar, Microsoft Outlook, and others**: Subscribe by URL using `https://ecu-hockey-api.onrender.com/calendar.ics`
- **High-Availability Static CDN Mirror (GitHub Pages)**: Subscribe by URL using `https://bdperkin.github.io/ecu-hockey-calendar/calendar.ics` (zero cold starts, refreshed every 6 hours via GitHub Actions)
- **Static Master Data Feeds**: [JSON Schedule](https://bdperkin.github.io/ecu-hockey-calendar/schedule.json) | [CSV Schedule](https://bdperkin.github.io/ecu-hockey-calendar/schedule.csv)

For complete, step-by-step instructions for every calendar client, custom alarm offsets, and troubleshooting, see the [ECU Hockey Calendar Sync Guide](docs/calendar_sync.md).

## 2. System Architecture

The platform aggregates data from disparate upstream sources, reconciles scheduling discrepancies, persists canonical records with audit history, and distributes notifications and calendar feeds:

```mermaid
flowchart TD
    subgraph SOT["Data Sources"]
        S1["ecuhockey.com/schedule (Primary SOT)"]
        S2["acchockey.com (League Schedule)"]
        S3["ecuhockey.com/tickets (Ticketing & Themes)"]
        S4["Instagram @ecuicehockey (Social Announcements)"]
        S5["Opponent Feeds (Reverse Verification)"]
    end

    subgraph WORKER["Ingestion & Crawlers"]
        W1["ResilientHttpClient"]
        W2["ECUHockeyCrawler"]
        W3["ACCHockeyCrawler"]
        W4["TicketsCrawler"]
        W5["InstagramCrawler"]
        W6["OpponentCrawler"]
    end

    subgraph REC["Reconciliation & Change Detection"]
        R1["Fuzzy Matcher (Mascots & Aliases)"]
        R2["Date & Timezone Aligner"]
        R3["ReconciliationEngine (Source Priority)"]
        R4["ChangeDetector (Atomic Transitions)"]
    end

    subgraph DB["Storage Layer"]
        D1["PostgreSQL / SQLite (SQLAlchemy 2.0 + Alembic)"]
        D2["Team & Game Master Records"]
        D3["Raw Snapshots & Sync Audit History"]
        D4["Game Change Audit Diffs"]
    end

    subgraph API["FastAPI Calendar & Data Service"]
        P1["RFC 5545 iCalendar & webcal (/calendar.ics)"]
        P2["Master Schedule Feeds (/api/schedule.json & .csv)"]
        P3["OpenAPI Docs (/docs & /redoc)"]
        P4["Health & Telemetry (/health & /api/v1/sync/status)"]
        P5["Admin Sync & Conflicts (/api/v1/conflicts)"]
    end

    subgraph CLI["Command-Line Interface (ecu-hockey)"]
        C1["sync (Ingestion & Reconciliation)"]
        C2["status (Health & Telemetry Tables)"]
        C3["export (ICS, JSON, CSV)"]
        C4["conflicts (Cross-Source Review)"]
        C5["serve (Uvicorn Web Server)"]
    end

    subgraph OUT["Alert Dispatch"]
        A1["Discord Webhook Embeds"]
        A2["Slack Block Kit Alerts"]
        A3["Telegram HTML Messages"]
    end

    SOT --> WORKER
    WORKER --> REC
    REC --> DB
    REC --> OUT
    DB --> API
    DB --> CLI
```

## 3. Features

- **Unified Command-Line Interface**: Terminal-first `ecu-hockey` CLI for running sync workflows, inspecting health/telemetry tables, reviewing discrepancies, exporting multi-format schedules, and hosting Uvicorn servers.
- **Production Containerization & Deployment**: Multi-stage `Dockerfile`, `docker-compose.yml` service orchestration (API, scheduled scraper worker, PostgreSQL), and comprehensive hosting analysis in [`DEPLOYMENT.md`](DEPLOYMENT.md).
- **Multi-Source Ingestion**: Robust web crawlers for primary schedule documents, ACCHL conference portals, ticketing tiers, social media announcements, and opponent feeds.
- **Resilient HTTP Client**: Connection pooling, exponential backoff, retry handling for transient errors (429/5xx), and SHA-256 payload caching.
- **Intelligent Reconciliation**: Transitive clustering, fuzzy opponent/venue matching with mascot stripping, and configurable source precedence hierarchies (Tier 1 SOT/League > Tier 2 Tickets/Social > Tier 3 Opponents).
- **Timezone-Aware Alignment**: Automatically normalizes game datetimes to Eastern Time (`America/New_York`), handling tolerance windows and tentative (TBD) times.
- **Relational Persistence**: SQLAlchemy 2.0 ORM models for SQLite and PostgreSQL with schema migrations managed by Alembic.
- **Change Detection & Audit Trail**: Real-time diffing of game schedule modifications, cancellations, and conflict flags with full sync cycle telemetry.
- **Multi-Channel Webhook Notifications**: Rich formatted alert dispatches to Discord, Slack, and Telegram.
- **RFC 5545 iCalendar & webcal Feeds**: Live calendar subscription feeds (`/calendar.ics`, `webcal://`) with deterministic UIDs, Eastern Time `VTIMEZONE`, and configurable reminder alarms.
- **Public Master Schedule Feeds**: Machine-readable JSON (`/api/schedule.json`) and downloadable CSV (`/api/schedule.csv`) feeds with query parameter filtering.
- **Operational Health & Conflict Administration**: Liveness and database connectivity probes (`/health`), sync cycle telemetry (`/api/v1/sync/status`), on-demand sync triggering (`POST /api/v1/sync/trigger`), and token-authenticated cross-source discrepancy review (`/api/v1/conflicts`).
- **Interactive Documentation**: Auto-generated interactive Swagger UI (`/docs`), ReDoc (`/redoc`), and OpenAPI 3.1 JSON specifications.
- **Strict Quality Standards**: 100% test coverage, strict `ty` static typing, and formatting via `ruff`.

## 4. Installation

Install the standalone CLI tool globally using `uv tool`:

```bash
uv tool install ecu-hockey-calendar
```

Or add `ecu-hockey-calendar` to an existing project with `uv`:

```bash
uv add ecu-hockey-calendar
```

Or install with standard `pip`:

```bash
pip install ecu-hockey-calendar
```

## 5. Quickstart

### 5.1. Managing and Exporting Schedules Manually

```python
from datetime import UTC, datetime
from ecu_hockey_calendar import ECUHockeyCalendar, Team

# Initialize calendar for 2026-2027 season
calendar = ECUHockeyCalendar(season="2026-2027")

# Define opponent
unc = Team(
    name="UNC Chapel Hill",
    city="Chapel Hill",
    state="NC",
    division="ACHA M2",
    conference="ACCHL",
)

# Add a match
game = calendar.add_match(
    opponent=unc,
    start_time=datetime(2026, 10, 15, 19, 0, tzinfo=UTC),
    venue="The Factory Ice House",
    is_home=True,
)

# Export RFC 5545 iCalendar string
ics_data = calendar.export_ics()
with open("ecu_hockey_schedule.ics", "w", encoding="utf-8") as f:
    f.write(ics_data)

# Export to JSON or CSV
json_data = calendar.export_json()
csv_data = calendar.export_csv()
```

### 5.2. Ingesting Feeds from Live Web Sources

```python
import asyncio
from ecu_hockey_calendar.ingestion import (
    ACCHockeyCrawler,
    ECUHockeyCrawler,
    ResilientHttpClient,
)


async def crawl_schedules() -> None:
    async with ResilientHttpClient() as client:
        # Crawl official primary schedule (Firestore API with HTML fallback)
        ecu_crawler = ECUHockeyCrawler(client=client)
        ecu_records, raw_text, content_hash, _ = await ecu_crawler.crawl()
        print(f"Crawled {len(ecu_records)} primary games (hash: {content_hash[:8]}).")

        # Crawl league conference schedule
        league_crawler = ACCHockeyCrawler(client=client)
        league_records, _, _, _ = await league_crawler.crawl()
        print(f"Crawled {len(league_records)} league games.")


asyncio.run(crawl_schedules())
```

### 5.3. Reconciling Feeds & Resolving Conflicts

```python
from datetime import UTC, datetime
from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.reconciliation import (
    ReconciliationEngine,
    SourceGameRecord,
)
from ecu_hockey_calendar.storage import DataSourceType

# Ingested records from different sources
ecu = Team(name="East Carolina University", city="Greenville", state="NC")
unc = Team(name="UNC Chapel Hill", city="Chapel Hill", state="NC")

primary_game = Game(
    game_id="ECU-2026-01",
    home_team=ecu,
    away_team=unc,
    start_time=datetime(2026, 10, 15, 23, 0, tzinfo=UTC),
    venue="The Factory Ice House",
    result=GameResult.SCHEDULED,
)

league_record = SourceGameRecord(
    source_type=DataSourceType.LEAGUE_ACCHL,
    source_code="acchockey",
    opponent_name="UNC",
    start_time=datetime(2026, 10, 15, 23, 0, tzinfo=UTC),
    venue="The Factory",
    is_home=True,
)

# Reconcile records into canonical games
engine = ReconciliationEngine()
records = [
    SourceGameRecord.from_game(primary_game, source_type=DataSourceType.PRIMARY_SOT),
    league_record,
]
result = engine.reconcile_games(records)

for game in result.reconciled_games:
    print(f"Reconciled: vs {game.opponent_name} at {game.venue}")
    print(
        f"Confidence: {game.confidence_score:.2f}, Sources: {game.contributing_sources}"
    )
```

### 5.4. Relational Persistence & Migrations

```python
from ecu_hockey_calendar.storage import (
    GameModel,
    GameStatus,
    create_sync_engine,
    get_sync_session,
    init_db,
)

# Initialize database schema
engine = create_sync_engine("sqlite:///ecu_hockey.db")
init_db(engine)

# Query scheduled games
with get_sync_session(engine) as session:
    games = session.query(GameModel).filter_by(status=GameStatus.SCHEDULED).all()
    print(f"Total scheduled games in database: {len(games)}")
```

### 5.5. Detecting Schedule Changes & Alerting

```python
from datetime import UTC, datetime
from ecu_hockey_calendar.notifications import (
    NotificationField,
    NotificationMessage,
    NotificationSeverity,
)
from ecu_hockey_calendar.reconciliation import ChangeDetector

# Detect differences between prior state and new reconciliation
detector = ChangeDetector()
changes = detector.detect_changes(
    previous_games=[],
    current_games=result.reconciled_games,
)

# Build notification message
for game in changes.created:
    message = NotificationMessage(
        title=f"New Game Scheduled: ECU vs {game.opponent_name}",
        description=f"Scheduled for {game.start_time.strftime('%b %d, %Y')}.",
        severity=NotificationSeverity.INFO,
        fields=[
            NotificationField(name="Venue", value=game.venue, inline=True),
        ],
        timestamp=datetime.now(UTC),
    )
```

### 5.6. Calendar Feeds & REST API Service

A live public production instance is available at [`https://ecu-hockey-api.onrender.com/`](https://ecu-hockey-api.onrender.com/) (see [§7.1. Live Production Deployment](#71-live-production-deployment-ecu-hockey-apionrendercom)). You can query the live service directly or launch the ASGI server locally for development:

```bash
# Start API service locally with hot reloading
uv run uvicorn ecu_hockey_calendar.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

#### 5.6.1. Calendar Subscription (Apple, Google, Outlook)

Subscribe to real-time fixture updates using the standard `webcal://` scheme or direct download:

```bash
# Apple Calendar / macOS one-click live subscription
open "webcal://ecu-hockey-api.onrender.com/calendar.ics"

# Download RFC 5545 .ics file from live service
curl -s https://ecu-hockey-api.onrender.com/calendar.ics -o ecu_schedule.ics

# Or subscribe locally when self-hosting
open "webcal://localhost:8000/calendar.ics"
```

For **Google Calendar** and **Outlook**, add by URL: `https://ecu-hockey-api.onrender.com/calendar.ics` (or `http://localhost:8000/calendar.ics` when self-hosting). For comprehensive, client-specific instructions with step-by-step guidance for desktop and mobile, see the [ECU Hockey Calendar Sync Guide](docs/calendar_sync.md).

#### 5.6.2. Querying Public Schedule Feeds

Retrieve structured JSON or CSV data feeds with filtering:

```bash
# Query JSON schedule with home match filter
curl -s "http://localhost:8000/api/schedule.json?home_only=true" | jq .

# Download CSV spreadsheet of scheduled matches
curl -s "http://localhost:8000/api/schedule.csv?status=SCHEDULED" -o schedule.csv
```

#### 5.6.3. Health Probes & Administration

```bash
# Probe system health and database connectivity
curl -s http://localhost:8000/health | jq .

# Trigger on-demand sync cycle (requires administrative token)
curl -X POST "http://localhost:8000/api/v1/sync/trigger" \
  -H "Authorization: Bearer secret-admin-token-12345"

# Inspect cross-source schedule discrepancies
curl -s "http://localhost:8000/api/v1/conflicts" \
  -H "Authorization: Bearer secret-admin-token-12345" | jq .
```

### 5.7. Command-Line Interface (`ecu-hockey`)

`ecu-hockey-calendar` includes a unified terminal-first CLI powered by Click and Rich:

```bash
# Display general help and registered subcommands
ecu-hockey --help

# Synchronize schedule from all active scrapers with database updates
ecu-hockey sync

# Preview synchronization changes in dry-run mode
ecu-hockey sync --season 2026-2027 --dry-run

# Display operational health, database connectivity, and team record overview
ecu-hockey status

# Export schedule to RFC 5545 iCalendar (.ics), JSON, or CSV
ecu-hockey export schedule.ics
ecu-hockey export --home-only -f csv home_games.csv
ecu-hockey export -f json | jq '.[0]'

# Inspect active cross-source discrepancies and conflicting fixtures
ecu-hockey conflicts --review-only

# Launch local Uvicorn ASGI server hosting the calendar feeds
ecu-hockey serve --port 8000

# Dispatch a test notification alert across configured webhooks
ecu-hockey notify -m "ECU vs NC State rescheduled to 8:00 PM" -s warning
```

#### 5.7.1. Subcommand Reference Table

| Subcommand  | Purpose                                                     | Key Options & Flags                                                                                         |
| :---------- | :---------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------- |
| `sync`      | Crawl sources, reconcile matches, diff state, and update DB | `--source [all\|ecuhockey\|acchockey]`, `--dry-run`, `--notify / --no-notify`, `--season`, `--db-url`       |
| `status`    | Display operational health, DB status, and season record    | `--season`, `--db-url`                                                                                      |
| `export`    | Export canonical schedule to `.ics`, `.json`, or `.csv`     | `-f, --format [ics\|json\|csv]`, `-o, --output <file>`, `--season`, `--opponent`, `--home-only`, `--status` |
| `conflicts` | Review multi-source discrepancies and flagged matches       | `--severity [low\|medium\|high\|critical]`, `--review-only`, `--field <name>`, `--db-url`                   |
| `serve`     | Run the FastAPI ASGI server with Uvicorn                    | `-h, --host`, `-p, --port`, `--reload / --no-reload`, `--db-url`                                            |
| `notify`    | Dispatch custom alerts across webhook channels              | `-m, --message`, `-t, --title`, `-s, --severity [info\|warning\|alert]`, `-c, --channel`                    |

For advanced usage details and exhaustive flag options, see the [CLI Documentation](docs/cli.md).

## 6. Database Schema Migrations

Database migrations are managed using Alembic. Run migrations to upgrade or downgrade your schema:

```bash
# Apply all migrations to the latest revision
uv run alembic upgrade head

# Roll back by one revision
uv run alembic downgrade -1

# Show migration history
uv run alembic history
```

## 7. Production Deployment & Containerization

### 7.1. Live Production Deployment (`ecu-hockey-api.onrender.com`)

A public production instance runs continuously on [Render](https://render.com) backed by managed PostgreSQL and an automated 6-hour synchronization worker:

- **Service Base URL**: [`https://ecu-hockey-api.onrender.com/`](https://ecu-hockey-api.onrender.com/)
- **One-Line Calendar Subscription**: [`webcal://ecu-hockey-api.onrender.com/calendar.ics`](webcal://ecu-hockey-api.onrender.com/calendar.ics)
- **Direct iCalendar Feed**: [`https://ecu-hockey-api.onrender.com/calendar.ics`](https://ecu-hockey-api.onrender.com/calendar.ics)
- **Interactive Documentation**: [`/docs`](https://ecu-hockey-api.onrender.com/docs) (Swagger UI) & [`/redoc`](https://ecu-hockey-api.onrender.com/redoc) (ReDoc)
- **Service Health Probe**: [`/health`](https://ecu-hockey-api.onrender.com/health)

| Method        | Endpoint                                                                        | Description                                          | Content-Type       | Access           |
| :------------ | :------------------------------------------------------------------------------ | :--------------------------------------------------- | :----------------- | :--------------- |
| `GET`         | [`/`](https://ecu-hockey-api.onrender.com/)                                     | API metadata, version provenance, and routes         | `application/json` | Public           |
| `GET`, `HEAD` | [`/health`](https://ecu-hockey-api.onrender.com/health)                         | Diagnostics, uptime, and database connectivity probe | `application/json` | Public           |
| `GET`, `HEAD` | [`/calendar.ics`](https://ecu-hockey-api.onrender.com/calendar.ics)             | RFC 5545 iCalendar feed (`?alarm_minutes=60`)        | `text/calendar`    | Public           |
| `GET`, `HEAD` | [`/api/schedule.json`](https://ecu-hockey-api.onrender.com/api/schedule.json)   | Master schedule JSON (`?home_only=true`)             | `application/json` | Public           |
| `GET`, `HEAD` | [`/api/schedule.csv`](https://ecu-hockey-api.onrender.com/api/schedule.csv)     | Master schedule CSV spreadsheet                      | `text/csv`         | Public           |
| `GET`         | [`/api/v1/sync/status`](https://ecu-hockey-api.onrender.com/api/v1/sync/status) | Sync telemetry & scraper execution history           | `application/json` | Public           |
| `POST`        | `/api/v1/sync/trigger`                                                          | Trigger on-demand scraper synchronization cycle      | `application/json` | **Bearer Token** |
| `GET`         | `/api/v1/conflicts`                                                             | Inspect multi-source schedule discrepancies          | `application/json` | **Bearer Token** |
| `GET`         | [`/docs`](https://ecu-hockey-api.onrender.com/docs)                             | Interactive Swagger UI API explorer                  | `text/html`        | Public           |

> [!NOTE]
> **Render Free-Tier Cold Starts**:
> On Render's free tier, the web service spins down after 15 minutes of inactivity. When a new request arrives, container cold start takes approximately 30–50 seconds before subsequent requests respond with sub-second latency. A slow initial request does not indicate an outage.

For full curl examples, administrative route details, and the complete architecture specification, refer to [`DEPLOYMENT.md`](DEPLOYMENT.md#68-live-production-deployment-ecu-hockey-apionrendercom).

### 7.2. Published Container Images (`ghcr.io`)

Pre-built multi-architecture (`linux/amd64`, `linux/arm64`) container images are automatically published to the GitHub Container Registry on releases and merges to `main`:

```bash
# Pull the latest published image
docker pull ghcr.io/bdperkin/ecu-hockey-calendar:latest

# Run the standalone calendar service
docker run -d --name ecu-hockey -p 8000:8000 ghcr.io/bdperkin/ecu-hockey-calendar:latest
```

### 7.3. Local Container Orchestration with Docker Compose

The repository also includes a production-ready, multi-stage `Dockerfile` and `docker-compose.yml` for unified local or production orchestration:

```bash
# Initialize environment configuration
cp .env.example .env

# Launch API, scraper worker, and PostgreSQL using published image
docker compose up -d

# Or build locally from source
docker compose up -d --build

# Check health probe
curl -s http://localhost:8000/health | jq .
```

### 7.4. Scheduled Ingestion & Static Feeds Automation

An automated GitHub Actions workflow ([`.github/workflows/schedule-sync.yml`](.github/workflows/schedule-sync.yml)) executes every 6 hours (`0 */6 * * *`):

- Ingests and reconciles fixtures across all primary, league, ticket, and social sources.
- Dispatches rich alert notifications to Discord, Slack, and Telegram for any detected changes.
- Exports static schedule feeds to `static/` (`calendar.ics`, `schedule.json`, `schedule.csv`).
- Triggers GitHub Pages deployment ([`.github/workflows/pages.yml`](.github/workflows/pages.yml)) to refresh the static CDN mirror at `https://bdperkin.github.io/ecu-hockey-calendar/`.

### 7.5. Automated Continuous Deployment

The repository includes an automated Continuous Deployment pipeline ([`.github/workflows/deploy.yml`](.github/workflows/deploy.yml)):

- Automatically triggers upon successful container publication on `main` or new release tags.
- Applies schema migrations (`alembic upgrade head`) before shifting live traffic.
- Performs automated health probe verification against `/health` to guarantee service readiness.

For an in-depth architectural comparison of background worker and API hosting providers (Render, Railway, Fly.io, AWS Lambda), persistent storage strategies, SSL/TLS termination requirements, and Instagram anti-bot scraping mitigations, see [`DEPLOYMENT.md`](DEPLOYMENT.md).

## 8. Development and Contributing

Contributions are welcome! Please review our [Contributing Guide](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md).

### 8.1. Quick Setup

```bash
# Clone the repository
git clone git@github.com:bdperkin/ecu-hockey-calendar.git
cd ecu-hockey-calendar

# Setup virtual environment and pre-commit hooks
make setup

# Run tests and linters
make check
```

## 9. Security

Please report vulnerabilities confidentially through GitHub Private Vulnerability Reporting or refer to our [Security Policy](SECURITY.md).

## 10. License

This project is licensed under the terms of the [MIT License](LICENSE).

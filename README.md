# ecu-hockey-calendar

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. System Architecture](#1-system-architecture)
- [2. Features](#2-features)
- [3. Installation](#3-installation)
- [4. Quickstart](#4-quickstart)
  - [4.1. Managing and Exporting Schedules Manually](#41-managing-and-exporting-schedules-manually)
  - [4.2. Ingesting Feeds from Live Web Sources](#42-ingesting-feeds-from-live-web-sources)
  - [4.3. Reconciling Feeds & Resolving Conflicts](#43-reconciling-feeds--resolving-conflicts)
  - [4.4. Relational Persistence & Migrations](#44-relational-persistence--migrations)
  - [4.5. Detecting Schedule Changes & Alerting](#45-detecting-schedule-changes--alerting)
  - [4.6. Calendar Feeds & REST API Service](#46-calendar-feeds--rest-api-service)
    - [4.6.1. Calendar Subscription (Apple, Google, Outlook)](#461-calendar-subscription-apple-google-outlook)
    - [4.6.2. Querying Public Schedule Feeds](#462-querying-public-schedule-feeds)
    - [4.6.3. Health Probes & Administration](#463-health-probes--administration)
  - [4.7. Command-Line Interface (`ecu-hockey`)](#47-command-line-interface--ecu-hockey)
- [5. Database Schema Migrations](#5-database-schema-migrations)
- [6. Production Deployment & Containerization](#6-production-deployment--containerization)
- [7. Development and Contributing](#7-development-and-contributing)
  - [7.1. Quick Setup](#71-quick-setup)
- [8. Security](#8-security)
- [9. License](#9-license)

______________________________________________________________________

<!--TOC-->

[![CI](https://github.com/bdperkin/ecu-hockey-calendar/actions/workflows/ci.yml/badge.svg)](https://github.com/bdperkin/ecu-hockey-calendar/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/bdperkin/ecu-hockey-calendar/graph/badge.svg?token=)](https://codecov.io/gh/bdperkin/ecu-hockey-calendar)
[![Python Version](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Type Checked with ty](https://img.shields.io/badge/type_checker-ty-blueviolet)](https://github.com/astral-sh/ty)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Pages](https://github.com/bdperkin/ecu-hockey-calendar/actions/workflows/pages.yml/badge.svg)](https://bdperkin.github.io/ecu-hockey-calendar/)
[![Documentation](https://img.shields.io/badge/docs-Sphinx-blue)](https://bdperkin.github.io/ecu-hockey-calendar/)

East Carolina University - Men's Ice Hockey Team - Calendar.

A modern, robust Python package for aggregating, reconciling, and distributing collegiate ice hockey schedules across web crawlers, relational persistence, conflict resolution, multi-channel webhook alerting, and calendar exports (RFC 5545 iCalendar, JSON, CSV).

## 1. System Architecture

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

## 2. Features

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

## 3. Installation

Install using `uv`:

```bash
uv add ecu-hockey-calendar
```

Or install with standard `pip`:

```bash
pip install ecu-hockey-calendar
```

## 4. Quickstart

### 4.1. Managing and Exporting Schedules Manually

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

### 4.2. Ingesting Feeds from Live Web Sources

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

### 4.3. Reconciling Feeds & Resolving Conflicts

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

### 4.4. Relational Persistence & Migrations

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

### 4.5. Detecting Schedule Changes & Alerting

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

### 4.6. Calendar Feeds & REST API Service

Launch the ASGI server locally to provide live calendar subscriptions and schedule feeds:

```bash
# Start API service with hot reloading
uv run uvicorn ecu_hockey_calendar.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

#### 4.6.1. Calendar Subscription (Apple, Google, Outlook)

Subscribe to real-time fixture updates using the standard `webcal://` scheme or direct download:

```bash
# Download RFC 5545 .ics file
curl -s http://localhost:8000/calendar.ics -o ecu_schedule.ics

# Apple Calendar / macOS instant subscription
open "webcal://localhost:8000/calendar.ics"
```

For **Google Calendar** and **Outlook**, add by URL: `https://your-domain.com/calendar.ics`.

#### 4.6.2. Querying Public Schedule Feeds

Retrieve structured JSON or CSV data feeds with filtering:

```bash
# Query JSON schedule with home match filter
curl -s "http://localhost:8000/api/schedule.json?home_only=true" | jq .

# Download CSV spreadsheet of scheduled matches
curl -s "http://localhost:8000/api/schedule.csv?status=SCHEDULED" -o schedule.csv
```

#### 4.6.3. Health Probes & Administration

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

### 4.7. Command-Line Interface (`ecu-hockey`)

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
```

## 5. Database Schema Migrations

Database migrations are managed using Alembic. Run migrations to upgrade or downgrade your schema:

```bash
# Apply all migrations to the latest revision
uv run alembic upgrade head

# Roll back by one revision
uv run alembic downgrade -1

# Show migration history
uv run alembic history
```

## 6. Production Deployment & Containerization

The repository includes a production-ready, multi-stage `Dockerfile` and `docker-compose.yml` for unified local or production orchestration:

```bash
# Initialize environment configuration
cp .env.example .env

# Build and launch API, scraper worker, and PostgreSQL
docker compose up -d --build

# Check health probe
curl -s http://localhost:8000/health | jq .
```

For an in-depth architectural comparison of background worker and API hosting providers (Render, Railway, Fly.io, AWS Lambda), persistent storage strategies, SSL/TLS termination requirements, and Instagram anti-bot scraping mitigations, see [`DEPLOYMENT.md`](DEPLOYMENT.md).

## 7. Development and Contributing

Contributions are welcome! Please review our [Contributing Guide](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md).

### 7.1. Quick Setup

```bash
# Clone the repository
git clone git@github.com:bdperkin/ecu-hockey-calendar.git
cd ecu-hockey-calendar

# Setup virtual environment and pre-commit hooks
make setup

# Run tests and linters
make check
```

## 8. Security

Please report vulnerabilities confidentially through GitHub Private Vulnerability Reporting or refer to our [Security Policy](SECURITY.md).

## 9. License

This project is licensed under the terms of the [MIT License](LICENSE).

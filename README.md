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
- [5. Database Schema Migrations](#5-database-schema-migrations)
- [6. Development and Contributing](#6-development-and-contributing)
  - [6.1. Quick Setup](#61-quick-setup)
- [7. Security](#7-security)
- [8. License](#8-license)

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

    subgraph OUT["Calendar & Alert Dispatch"]
        A1["RFC 5545 iCalendar (.ics)"]
        A2["Public JSON & CSV Feeds"]
        A3["Discord Webhook Embeds"]
        A4["Slack Block Kit Alerts"]
        A5["Telegram HTML Messages"]
    end

    SOT --> WORKER
    WORKER --> REC
    REC --> DB
    REC --> OUT
```

## 2. Features

- **Multi-Source Ingestion**: Robust web crawlers for primary schedule documents, ACCHL conference portals, ticketing tiers, social media announcements, and opponent feeds.
- **Resilient HTTP Client**: Connection pooling, exponential backoff, retry handling for transient errors (429/5xx), and SHA-256 payload caching.
- **Intelligent Reconciliation**: Transitive clustering, fuzzy opponent/venue matching with mascot stripping, and configurable source precedence hierarchies (Tier 1 SOT/League > Tier 2 Tickets/Social > Tier 3 Opponents).
- **Timezone-Aware Alignment**: Automatically normalizes game datetimes to Eastern Time (`America/New_York`), handling tolerance windows and tentative (TBD) times.
- **Relational Persistence**: SQLAlchemy 2.0 ORM models for SQLite and PostgreSQL with schema migrations managed by Alembic.
- **Change Detection & Audit Trail**: Real-time diffing of game schedule modifications, cancellations, and conflict flags with full sync cycle telemetry.
- **Multi-Channel Webhook Notifications**: Rich formatted alert dispatches to Discord, Slack, and Telegram.
- **RFC 5545 iCalendar & Data Exports**: Export standard `.ics` calendar files, CSV spreadsheets, and structured JSON feeds.
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

## 6. Development and Contributing

Contributions are welcome! Please review our [Contributing Guide](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md).

### 6.1. Quick Setup

```bash
# Clone the repository
git clone git@github.com:bdperkin/ecu-hockey-calendar.git
cd ecu-hockey-calendar

# Setup virtual environment and pre-commit hooks
make setup

# Run tests and linters
make check
```

## 7. Security

Please report vulnerabilities confidentially through GitHub Private Vulnerability Reporting or refer to our [Security Policy](SECURITY.md).

## 8. License

This project is licensed under the terms of the [MIT License](LICENSE).

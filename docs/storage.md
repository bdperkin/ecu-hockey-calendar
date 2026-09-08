# Relational Persistence Layer & Schema Migrations

The `ecu_hockey_calendar.storage` package provides a production-grade relational persistence layer built on SQLAlchemy 2.0 and Alembic. It supports both synchronous and asynchronous database interactions with SQLite (via standard sqlite3 and `aiosqlite`) and PostgreSQL (via `psycopg`).

## 1. Architecture Overview

The persistence architecture manages normalized entities (teams and games), provenance tracking (data sources and raw snapshot payloads), and audit history (sync telemetry and game state transitions).

```text
┌─────────────────┐       ┌─────────────────┐
│     TeamORM     │◄──────┤     GameORM     │
│ (ECU & Opponent)│  1:N  │(Schedule Events)│
└─────────────────┘       └────────┬────────┘
                                   │
      ┌────────────────────────────┼────────────────────────────┐
      │ 1:N                        │ 1:N                        │ 1:N
      ▼                            ▼                            ▼
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│  GameChangeORM  │       │ RawSnapshotORM  │       │  SyncAuditORM   │
│ (Diffs & State) │       │ (Raw Payloads)  │       │ (Run Telemetry) │
└─────────────────┘       └─────────────────┘       └─────────────────┘
```

## 2. Relational ORM Models

All database tables inherit from declarative `Base` with standardized constraint naming conventions.

### 2.1. Core Entities

- **`TeamORM` / `TeamModel`**: Stores team profiles, divisions, conferences, home venues, and social media handles.
- **`GameORM` / `GameModel`**: Stores scheduled and completed matches, including start and end times, venue, home/away designation, game status (`SCHEDULED`, `FINAL`, `CANCELLED`, `POSTPONED`), and final scores.
- **`DataSourceORM` / `DataSourceModel`**: Registers external data providers, source tier rankings, and crawler endpoint URLs.

### 2.2. Audit & Snapshot Entities

- **`RawSnapshotORM` / `RawSnapshotModel`**: Archives exact raw scrape payloads (HTML, JSON, iCalendar) alongside SHA-256 content hashes and scrape timestamps.
- **`SyncAuditORM` / `SyncAuditModel`**: Tracks sync execution cycles, elapsed durations in milliseconds, HTTP status codes, error messages, and ingested record counts.
- **`GameChangeORM` / `GameChangeModel`**: Immutable audit log recording atomic game transitions (`CREATED`, `UPDATED`, `DELETED`, `CONFLICT_DETECTED`) with field-level before/after JSON diffs.

## 3. Database Engine & Session Management

The storage package provides factory functions for both synchronous and asynchronous database engines and session contexts.

### 3.1. Synchronous Session Example

```python
from ecu_hockey_calendar.storage import (
    GameModel,
    GameStatus,
    create_sync_engine,
    get_sync_session,
    init_db,
)

# Create synchronous SQLite engine
engine = create_sync_engine("sqlite:///ecu_hockey.db")

# Initialize database tables
init_db(engine)

# Open managed session
with get_sync_session(engine) as session:
    games = (
        session.query(GameModel).filter(GameModel.status == GameStatus.SCHEDULED).all()
    )
    print(f"Retrieved {len(games)} scheduled games.")
```

### 3.2. Asynchronous Session Example

```python
import asyncio
from ecu_hockey_calendar.storage import (
    GameModel,
    async_init_db,
    create_async_engine,
    get_async_session,
)
from sqlalchemy import select


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///ecu_hockey.db")
    await async_init_db(engine)

    async with get_async_session(engine) as session:
        stmt = select(GameModel)
        result = await session.execute(stmt)
        games = result.scalars().all()
        print(f"Async query returned {len(games)} games.")


asyncio.run(main())
```

## 4. Database Schema Migrations with Alembic

All schema evolutions are managed through Alembic revision scripts stored in `alembic/versions/`.

### 4.1. Command-Line Migrations

Run database migrations via the project's development tools:

```bash
# Upgrade database to the latest schema revision
uv run alembic upgrade head

# Downgrade by one revision
uv run alembic downgrade -1

# View migration history
uv run alembic history
```

### 4.2. Programmatic Migration Execution

Migrations can also be executed programmatically in automation scripts or continuous integration workflows:

```python
from ecu_hockey_calendar.storage import run_migrations_upgrade

# Apply all pending schema migrations
run_migrations_upgrade(
    database_url="sqlite:///ecu_hockey.db",
    revision="head",
)
```

## 5. Audit & Change Tracking Service

The `storage.service` module provides high-level helpers for recording sync cycles and querying change history:

```python
from ecu_hockey_calendar.storage import (
    create_sync_engine,
    get_changes_since,
    get_sync_audit_history,
    get_sync_session,
)

engine = create_sync_engine("sqlite:///ecu_hockey.db")

with get_sync_session(engine) as session:
    # Query sync audit records
    audits = get_sync_audit_history(session, limit=10)
    for audit in audits:
        print(f"Sync cycle {audit.sync_id}: {audit.status} ({audit.duration_ms}ms)")

    # Query recent game changes
    changes = get_changes_since(session, hours=48)
    for change in changes:
        print(f"Game {change.game_id}: {change.transition} - {change.field_diffs}")
```

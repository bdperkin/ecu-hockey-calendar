# ECU Hockey Calendar

East Carolina University - Men's Ice Hockey Team - Calendar.

A modern, robust Python package for managing collegiate ice hockey schedules,
tracking team matches, and exporting calendar fixtures to standard iCalendar
(RFC 5545), JSON, and CSV formats.

```{toctree}
:maxdepth: 2
:caption: Contents:

installation
quickstart
cli
ingestion
storage
reconciliation
notifications
api_service
api
contributing
changelog
```

## 1. Features

- **Unified Command-Line Interface**: Terminal-first `ecu-hockey` CLI for syncing, health inspections, conflict diagnosis, schedule exporting, and API server hosting.
- **Multi-Source Web Crawlers**: Automated ingestion from official team sites (`ecuhockey.com`), ACCHL league portals (`acchockey.com`), ticketing platforms, Instagram feeds, and opponent calendars.
- **Relational Persistence & Migrations**: SQLAlchemy 2.0 ORM models for SQLite and PostgreSQL with automated Alembic schema migrations.
- **Schedule Reconciliation Engine**: Multi-tier source precedence, opponent and venue fuzzy matching, and timezone-aware date alignment.
- **Change Detection & Audit Trail**: Real-time diffing of game schedule changes, cancellations, and conflict flags with full cycle telemetry.
- **Multi-Platform Webhook Alerts**: Rich formatted alerts dispatched to Discord, Slack, and Telegram channels.
- **FastAPI Calendar & Data Service**: Live RFC 5545 iCalendar (`/calendar.ics`) and webcal subscription feeds, public JSON and CSV master schedule feeds, and interactive OpenAPI documentation.
- **Diagnostics & Conflict Administration**: Service health checks, synchronization telemetry, on-demand sync triggering, and administrative conflict review.
- **Interoperability**: Export schedules to CSV, JSON, and dictionary representations.
- **Strict Quality**: 100% line and branch test coverage, strict type annotations checked by `ty`, and formatting via `ruff`.

## 2. Indices and tables

- {ref}`genindex`
- {ref}`modindex`
- {ref}`search`

# Command-Line Interface (CLI)

The `ecu-hockey-calendar` package includes a unified, terminal-first CLI tool named `ecu-hockey`. Powered by [Click](https://click.palletsprojects.com/) and styled with [Rich](https://rich.readthedocs.io/), it provides full control over data ingestion, schedule diagnostics, cross-source conflict inspection, multi-format calendar export, and API service hosting.

## 1. Overview & Installation

When you install `ecu-hockey-calendar`, the executable entry point `ecu-hockey` is automatically registered in your Python environment:

```bash
# Verify installation
ecu-hockey --help
ecu-hockey --version
```

Alternatively, you can run the CLI as a Python module:

```bash
python -m ecu_hockey_calendar.cli --help
```

______________________________________________________________________

## 2. Global Database Configuration

All commands querying or updating relational state support the `--db-url` option or the `DATABASE_URL` environment variable. If omitted, the CLI defaults to a local SQLite database at `sqlite:///ecu_hockey.db`.

```bash
# Example using PostgreSQL environment variable
export DATABASE_URL="postgresql://localhost:5432/ecu_hockey"
ecu-hockey status
```

______________________________________________________________________

## 3. Subcommands Reference

### 3.1. `ecu-hockey sync`

Executes the automated ingestion and reconciliation pipeline across registered web sources, detects schedule changes, records audit history, dispatches webhook notifications, and updates the database.

```bash
ecu-hockey sync [OPTIONS]
```

**Options:**

| Option                   | Environment Variable | Default    | Description                                                                              |
| :----------------------- | :------------------- | :--------- | :--------------------------------------------------------------------------------------- |
| `-s, --source`           | —                    | `all`      | Restrict sync to a specific data source (`all`, `ecuhockey`, `acchockey`).               |
| `--dry-run`              | —                    | `False`    | Perform crawl, reconciliation, and diffing without committing changes to the database.   |
| `--notify / --no-notify` | —                    | `--notify` | Dispatch webhook notifications (Discord, Slack, Telegram) for detected schedule changes. |
| `--notify-individual`    | —                    | `False`    | Dispatch individual alert messages for each detected schedule change.                    |
| `--db-url`               | `DATABASE_URL`       | `None`     | Database connection URL override.                                                        |
| `--season`               | —                    | `None`     | Optional season filter (e.g., `2026-2027`).                                              |

**Examples:**

```bash
# Run a full sync for the current season
ecu-hockey sync

# Preview changes with a dry run for the 2026-2027 season
ecu-hockey sync --season 2026-2027 --dry-run

# Ingest exclusively from the official team site without sending notifications
ecu-hockey sync --source ecuhockey --no-notify
```

______________________________________________________________________

### 3.2. `ecu-hockey status`

Displays comprehensive operational telemetry, database connectivity, scraper status, schedule overview metrics (wins, losses, cancellations), and the next upcoming match spotlight.

```bash
ecu-hockey status [OPTIONS]
```

**Options:**

| Option     | Environment Variable | Default | Description                                 |
| :--------- | :------------------- | :------ | :------------------------------------------ |
| `--db-url` | `DATABASE_URL`       | `None`  | Database connection URL override.           |
| `--season` | —                    | `None`  | Optional season filter (e.g., `2026-2027`). |

**Example:**

```bash
ecu-hockey status
ecu-hockey status --season 2026-2027
```

______________________________________________________________________

### 3.3. `ecu-hockey export`

Exports the schedule into standard RFC 5545 iCalendar (`.ics`), structured JSON, CSV, standalone responsive HTML, or high-contrast printable PDF grid format. Output can be saved directly to a file or streamed to standard output for piping.

```bash
ecu-hockey export [OPTIONS] [OUTPUT_FILE]
```

**Options:**

| Option                           | Environment Variable | Default               | Description                                                                                                 |
| :------------------------------- | :------------------- | :-------------------- | :---------------------------------------------------------------------------------------------------------- |
| `-f, --format`                   | —                    | Auto-detected / `ics` | Output serialization format (`ics`, `json`, `csv`, `html`, `pdf`). Auto-detected from `--output` extension. |
| `-o, --output`                   | —                    | `None` (stdout)       | Destination file path (if omitted, writes to stdout).                                                       |
| `--season`                       | —                    | `None`                | Optional season filter (e.g., `2026-2027`).                                                                 |
| `--opponent`                     | —                    | `None`                | Filter games by opponent team name substring.                                                               |
| `--home-only`                    | —                    | `False`               | Filter games to only home matchups hosted by ECU.                                                           |
| `--status`                       | —                    | `None`                | Filter by fixture status (e.g., `scheduled`, `final`, `cancelled`).                                         |
| `--embed`                        | —                    | `False`               | Export lightweight embeddable widget HTML view instead of full schedule page.                               |
| `--include-past / --future-only` | —                    | `--include-past`      | Include completed and historical fixtures in export.                                                        |
| `--db-url`                       | `DATABASE_URL`       | `None`                | Database connection URL override.                                                                           |

**Examples:**

```bash
# Export iCalendar file
ecu-hockey export schedule.ics

# Export CSV spreadsheet of home games only
ecu-hockey export --home-only -f csv -o home_games.csv

# Export standalone responsive HTML schedule
ecu-hockey export -f html -o schedule.html

# Export lightweight embeddable HTML widget
ecu-hockey export --embed -f html -o embed_schedule.html

# Export printable schedule grid PDF for refrigerators and bench clipboards
ecu-hockey export -f pdf schedule.pdf

# Export printable PDF of home games only
ecu-hockey export --home-only -f pdf home_schedule.pdf

# Stream JSON schedule to stdout and pipe to jq
ecu-hockey export -f json | jq '.[0]'
```

______________________________________________________________________

### 3.4. `ecu-hockey conflicts`

Lists cross-source schedule discrepancies and potential data conflicts detected during reconciliation cycles. Discrepancies requiring manual review or administrative attention are highlighted.

```bash
ecu-hockey conflicts [OPTIONS]
```

**Options:**

| Option                  | Environment Variable | Default      | Description                                                                       |
| :---------------------- | :------------------- | :----------- | :-------------------------------------------------------------------------------- |
| `--severity`            | —                    | `None` (all) | Filter discrepancies by severity level (`low`, `medium`, `high`, `critical`).     |
| `--game-id`             | —                    | `None`       | Filter discrepancies for a specific canonical game identifier.                    |
| `--field`               | —                    | `None` (all) | Filter discrepancies by conflicting attribute name (e.g., `venue`, `start_time`). |
| `--review-only / --all` | —                    | `--all`      | Show only discrepancies flagged as requiring administrative review.               |
| `--db-url`              | `DATABASE_URL`       | `None`       | Database connection URL override.                                                 |

**Examples:**

```bash
# List all active schedule discrepancies
ecu-hockey conflicts

# Show only discrepancies requiring manual administrative review
ecu-hockey conflicts --review-only

# Filter discrepancies affecting game start times with critical severity
ecu-hockey conflicts --field start_time --severity critical
```

______________________________________________________________________

### 3.5. `ecu-hockey serve`

Starts the Uvicorn ASGI server hosting the FastAPI calendar and schedule service, providing live `/calendar.ics` webcal feeds, `/api/schedule.json`, `/api/schedule.csv`, and interactive OpenAPI docs.

```bash
ecu-hockey serve [OPTIONS]
```

**Options:**

| Option                   | Environment Variable | Default       | Description                                                  |
| :----------------------- | :------------------- | :------------ | :----------------------------------------------------------- |
| `-h, --host`             | —                    | `127.0.0.1`   | Network interface host to bind the server.                   |
| `-p, --port`             | —                    | `8000`        | TCP port number to listen on.                                |
| `--reload / --no-reload` | —                    | `--no-reload` | Enable auto-reload on filesystem changes (development mode). |
| `--db-url`               | `DATABASE_URL`       | `None`        | Database connection URL override.                            |

**Examples:**

```bash
# Start local calendar server
ecu-hockey serve

# Start server bound to all interfaces on port 8080 with reload
ecu-hockey serve -h 0.0.0.0 -p 8080 --reload
```

______________________________________________________________________

### 3.6. `ecu-hockey notify`

Dispatches custom notification alerts and automated failure reports across configured webhook channels (Discord, Slack, Telegram).

```bash
ecu-hockey notify [OPTIONS]
```

**Options:**

| Option          | Short | Default                   | Description                                                      |
| :-------------- | :---- | :------------------------ | :--------------------------------------------------------------- |
| `--message`     | `-m`  | *(Required)*              | Primary notification summary or message body.                    |
| `--title`       | `-t`  | `ECU Hockey Notification` | Title for the notification embed or message header.              |
| `--severity`    | `-s`  | `info`                    | Alert severity (`info`, `success`, `warning`, `alert`, `error`). |
| `--details`     | `-d`  | `None`                    | Extended details, context, or error trace.                       |
| `--url`         | —     | `None`                    | Associated action, run, or fixture URL.                          |
| `-c, --channel` | `-c`  | All configured            | Restrict dispatch to specific channel(s).                        |

**Examples:**

```bash
# Dispatch an informational alert
ecu-hockey notify -m "Schedule synchronization completed" -t "Sync Notice"

# Dispatch a critical failure alert with run URL
ecu-hockey notify \
  -t "🚨 Schedule Sync Failed" \
  -m "Automated schedule sync workflow failed in run #42." \
  -s alert \
  --url "https://github.com/bdperkin/ecu-hockey-calendar/actions/runs/42"

# Dispatch exclusively to Discord
ecu-hockey notify -m "Discord-only test message" -c discord
```

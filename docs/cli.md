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

## 2. Database & Remote API Configuration

The CLI supports two primary operational topologies:

1. **Direct Database Persistence Mode (Default)**: Commands connect directly to SQLite or PostgreSQL storage using the `--db-url` option or the `DATABASE_URL` environment variable. If omitted, the CLI defaults to local SQLite storage at `sqlite:///ecu_hockey.db`.
2. **Remote API Integration Mode**: Commands (`status`, `health`, `conflicts`, `export`, `sync`) can interact directly with remote HTTP API deployments (e.g., `https://ecu-hockey-api.onrender.com`) using `--api-url` (or `ECU_HOCKEY_API_URL`) and `--token` (or `ECU_HOCKEY_ADMIN_TOKEN`). This eliminates the requirement for direct database port exposure, VPNs, or network ingress into production databases.

```bash
# Direct database access via PostgreSQL
export DATABASE_URL="postgresql://localhost:5432/ecu_hockey"
ecu-hockey status

# Remote API access against production deployment
export ECU_HOCKEY_API_URL="https://ecu-hockey-api.onrender.com"
export ECU_HOCKEY_ADMIN_TOKEN="your-admin-secret-token"
ecu-hockey status
```

Options `--api-url` and `--token` can be supplied globally before subcommands (e.g. `ecu-hockey --api-url ... status`) or directly on individual subcommands (e.g. `ecu-hockey status --api-url ...`).

______________________________________________________________________

## 3. Subcommands Reference

### 3.1. `ecu-hockey sync`

Executes the automated ingestion and reconciliation pipeline across registered web sources, detects schedule changes, records audit history, dispatches webhook notifications, and updates the database.

By default, invoking `ecu-hockey sync` triggers the ingestion pipeline (equivalent to `ecu-hockey sync trigger`). To inspect recent synchronization history and telemetry without triggering a sync, use `ecu-hockey sync status`.

```bash
# Trigger synchronization cycle (default)
ecu-hockey sync [OPTIONS]
ecu-hockey sync trigger [OPTIONS]

# Inspect synchronization execution history & telemetry
ecu-hockey sync status [OPTIONS]
```

**Options (`sync` / `sync trigger`):**

| Option                   | Environment Variable     | Default    | Description                                                                                                   |
| :----------------------- | :----------------------- | :--------- | :------------------------------------------------------------------------------------------------------------ |
| `-s, --source`           | —                        | `all`      | Restrict sync to a specific data source (`all`, `ecuhockey`, `acchockey`, `instagram`, `opponent`, `social`). |
| `--dry-run`              | —                        | `False`    | Perform crawl, reconciliation, and diffing without committing changes to the database.                        |
| `--notify / --no-notify` | —                        | `--notify` | Dispatch webhook notifications (Discord, Slack, Telegram) for detected schedule changes.                      |
| `--notify-individual`    | —                        | `False`    | Dispatch individual alert messages for each detected schedule change.                                         |
| `-v, --verbose`          | —                        | `False`    | Display URLs being scraped and item extraction discovery statistics.                                          |
| `--debug`                | —                        | `False`    | Display all HTTP wire requests, responses, headers, body snippets, and latencies.                             |
| `--db-url`               | `DATABASE_URL`           | `None`     | Database connection URL override.                                                                             |
| `--season`               | —                        | `None`     | Optional season filter (e.g., `2026-2027`).                                                                   |
| `--api-url`              | `ECU_HOCKEY_API_URL`     | `None`     | Remote ECU Hockey API base URL (e.g. `https://ecu-hockey-api.onrender.com`).                                  |
| `--token`                | `ECU_HOCKEY_ADMIN_TOKEN` | `None`     | Administrative authentication Bearer token for protected remote endpoints.                                    |

**Options (`sync status`):**

| Option      | Environment Variable     | Default | Description                                                                  |
| :---------- | :----------------------- | :------ | :--------------------------------------------------------------------------- |
| `--db-url`  | `DATABASE_URL`           | `None`  | Database connection URL override.                                            |
| `--api-url` | `ECU_HOCKEY_API_URL`     | `None`  | Remote ECU Hockey API base URL (e.g. `https://ecu-hockey-api.onrender.com`). |
| `--token`   | `ECU_HOCKEY_ADMIN_TOKEN` | `None`  | Administrative authentication Bearer token for protected remote endpoints.   |
| `--json`    | —                        | `False` | Output raw synchronization telemetry as structured JSON.                     |

**Examples:**

```bash
# Run a full sync for the current season
ecu-hockey sync

# Run sync with verbose telemetry showing visited URLs
ecu-hockey sync -v

# Run sync with full wire-level HTTP request/response debugging
ecu-hockey sync --debug

# Inspect synchronization execution history
ecu-hockey sync status

# Inspect remote synchronization status formatted as JSON
ecu-hockey sync status --api-url https://ecu-hockey-api.onrender.com --json | jq .

# Preview changes with a dry run for the 2026-2027 season
ecu-hockey sync --season 2026-2027 --dry-run

# Ingest exclusively from the official team site without sending notifications
ecu-hockey sync --source ecuhockey --no-notify

# Trigger on-demand sync cycle on a remote deployment
ecu-hockey sync --api-url https://ecu-hockey-api.onrender.com --token secret-token-123
```

______________________________________________________________________

### 3.2. `ecu-hockey scrape` (or `ecu-hockey crawl`)

Directly executes schedule scrapers and crawlers without invoking the full reconciliation and diffing pipeline. Provides a three-tiered output granularity model for troubleshooting crawler health, verifying link traversal, and diagnosing API responses:

1. **Default (Minimal)**: Clean, concise summary table with minimal terminal output.
2. **Verbose (`-v`, `--verbose`)**: Real-time log of every URL fetched along with discovery statistics (games found, sublinks discovered).
3. **Debug (`--debug`)**: Comprehensive HTTP wire tracing displaying methods, request headers, response headers, status codes, latencies, and response body previews.

```bash
# Run with minimal output (default)
ecu-hockey scrape [OPTIONS]
ecu-hockey crawl [OPTIONS]

# Run with verbose URL logging
ecu-hockey scrape -s acchockey -v

# Run in debug mode (wire requests, responses, headers, timing)
ecu-hockey scrape -s acchockey --debug
```

**Options:**

| Option               | Environment Variable | Default     | Description                                                                                               |
| :------------------- | :------------------- | :---------- | :-------------------------------------------------------------------------------------------------------- |
| `-s, --source`       | —                    | `all`       | Target scraper(s) to run (`all`, `ecuhockey`, `acchockey`, `instagram`, `opponent`, `tickets`, `social`). |
| `-v, --verbose`      | —                    | `False`     | List URLs being scraped and extraction discovery statistics in real time.                                 |
| `--debug`            | —                    | `False`     | Display all HTTP wire requests, responses, headers, body snippets, and latencies.                         |
| `--subseasons`       | —                    | `None`      | Comma-separated subseason IDs or URLs for multi-season traversal on league scrapers.                      |
| `--season`           | —                    | `None`      | Collegiate hockey athletic season filter (e.g. `2026-2027`).                                              |
| `--json`             | —                    | `False`     | Output extracted fixtures and scraper telemetry as formatted JSON to stdout.                              |
| `--save / --no-save` | —                    | `--no-save` | Persist raw snapshots and fixtures into relational storage.                                               |
| `--db-url`           | `DATABASE_URL`       | `None`      | Database connection URL override when `--save` is used.                                                   |

**Examples:**

```bash
# Scrape all sources with minimal summary output
ecu-hockey scrape

# Inspect ACC Hockey crawler link traversal with verbose output
ecu-hockey scrape -s acchockey -v

# Debug HTTP requests and headers for the official team website crawler
ecu-hockey scrape -s ecuhockey --debug

# Traverse specific historical ACC Hockey subseasons
ecu-hockey scrape -s acchockey --subseasons 950924,932896 -v

# Pipe clean JSON records to jq (telemetry output goes to stderr)
ecu-hockey scrape -s acchockey --json | jq .records.acchockey[0]

# Scrape and persist raw snapshots and fixtures to local SQLite database
ecu-hockey scrape --save
```

______________________________________________________________________

### 3.3. `ecu-hockey status`

Displays comprehensive operational telemetry, database connectivity, scraper status, schedule overview metrics (wins, losses, cancellations), and the next upcoming match spotlight.

```bash
ecu-hockey status [OPTIONS]
```

**Options:**

| Option      | Environment Variable     | Default | Description                                                                  |
| :---------- | :----------------------- | :------ | :--------------------------------------------------------------------------- |
| `--db-url`  | `DATABASE_URL`           | `None`  | Database connection URL override.                                            |
| `--season`  | —                        | `None`  | Optional season filter (e.g., `2026-2027`).                                  |
| `--api-url` | `ECU_HOCKEY_API_URL`     | `None`  | Remote ECU Hockey API base URL (e.g. `https://ecu-hockey-api.onrender.com`). |
| `--token`   | `ECU_HOCKEY_ADMIN_TOKEN` | `None`  | Administrative authentication Bearer token for protected remote endpoints.   |

**Examples:**

```bash
# Inspect local database status
ecu-hockey status
ecu-hockey status --season 2026-2027

# Inspect remote production deployment status
ecu-hockey status --api-url https://ecu-hockey-api.onrender.com
```

______________________________________________________________________

### 3.4. `ecu-hockey health`

Inspects service health diagnostics, database connectivity, scraper status, API version, and system uptime locally or against a remote API deployment. Returns an exit code of `0` if healthy, or `1` if degraded or unhealthy.

```bash
ecu-hockey health [OPTIONS]
```

**Options:**

| Option      | Environment Variable     | Default | Description                                                                  |
| :---------- | :----------------------- | :------ | :--------------------------------------------------------------------------- |
| `--db-url`  | `DATABASE_URL`           | `None`  | Database connection URL override.                                            |
| `--api-url` | `ECU_HOCKEY_API_URL`     | `None`  | Remote ECU Hockey API base URL (e.g. `https://ecu-hockey-api.onrender.com`). |
| `--token`   | `ECU_HOCKEY_ADMIN_TOKEN` | `None`  | Administrative authentication Bearer token for protected remote endpoints.   |
| `--json`    | —                        | `False` | Render health diagnostics payload as structured JSON to stdout.              |

**Examples:**

```bash
# Inspect local database health
ecu-hockey health

# Output health diagnostics as JSON for monitoring/healthcheck scripts
ecu-hockey health --json | jq .

# Probe remote deployment health
ecu-hockey health --api-url https://ecu-hockey-api.onrender.com
```

______________________________________________________________________

### 3.5. `ecu-hockey export`

Exports the schedule into standard RFC 5545 iCalendar (`.ics`), structured JSON, CSV, standalone responsive HTML, high-contrast printable PDF grid, RSS 2.0 XML, or Atom 1.0 XML format. Output can be saved directly to a file or streamed to standard output for piping.

```bash
ecu-hockey export [OPTIONS] [OUTPUT_FILE]
```

**Options:**

| Option                           | Environment Variable     | Default               | Description                                                                                                                |
| :------------------------------- | :----------------------- | :-------------------- | :------------------------------------------------------------------------------------------------------------------------- |
| `-f, --format`                   | —                        | Auto-detected / `ics` | Output serialization format (`ics`, `json`, `csv`, `html`, `pdf`, `rss`, `atom`). Auto-detected from `--output` extension. |
| `-o, --output`                   | —                        | `None` (stdout)       | Destination file path (if omitted, writes to stdout).                                                                      |
| `--season`                       | —                        | `None`                | Optional season filter (e.g., `2026-2027`).                                                                                |
| `--opponent`                     | —                        | `None`                | Filter games by opponent team name substring.                                                                              |
| `--home-only`                    | —                        | `False`               | Filter games to only home matchups hosted by ECU.                                                                          |
| `--status`                       | —                        | `None`                | Filter by fixture status (e.g., `scheduled`, `final`, `cancelled`).                                                        |
| `--embed`                        | —                        | `False`               | Export lightweight embeddable widget HTML view instead of full schedule page.                                              |
| `--include-past / --future-only` | —                        | `--include-past`      | Include completed and historical fixtures in export.                                                                       |
| `--db-url`                       | `DATABASE_URL`           | `None`                | Database connection URL override.                                                                                          |
| `--api-url`                      | `ECU_HOCKEY_API_URL`     | `None`                | Remote ECU Hockey API base URL (e.g. `https://ecu-hockey-api.onrender.com`).                                               |
| `--token`                        | `ECU_HOCKEY_ADMIN_TOKEN` | `None`                | Administrative authentication Bearer token for protected remote endpoints.                                                 |

**Examples:**

```bash
# Export iCalendar file from local database
ecu-hockey export schedule.ics

# Export RSS 2.0 syndication feed
ecu-hockey export -f rss -o schedule.rss

# Export Atom 1.0 syndication feed for upcoming matches only
ecu-hockey export --future-only -f atom -o schedule.atom

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

# Export printable PDF directly from remote production API without local database access
ecu-hockey export --api-url https://ecu-hockey-api.onrender.com -f pdf -o remote_schedule.pdf
```

______________________________________________________________________

### 3.6. `ecu-hockey conflicts`

Lists cross-source schedule discrepancies and potential data conflicts detected during reconciliation cycles. Discrepancies requiring manual review or administrative attention are highlighted.

```bash
ecu-hockey conflicts [OPTIONS]
```

**Options:**

| Option                      | Environment Variable     | Default      | Description                                                                                 |
| :-------------------------- | :----------------------- | :----------- | :------------------------------------------------------------------------------------------ |
| `--severity`                | —                        | `None` (all) | Filter discrepancies by severity level (`low`, `medium`, `high`, `critical`).               |
| `--game-id`                 | —                        | `None`       | Filter discrepancies for a specific canonical game identifier.                              |
| `--field, --field-name`     | —                        | `None` (all) | Filter discrepancies by conflicting attribute name (e.g., `venue`, `start_time`).           |
| `--requires-review / --all` | —                        | `--all`      | Show only discrepancies flagged as requiring administrative review (`--review-only` alias). |
| `--limit`                   | —                        | `None`       | Maximum number of discrepancy items to return.                                              |
| `--offset`                  | —                        | `0`          | Zero-indexed offset for paginated discrepancy records.                                      |
| `--json`                    | —                        | `False`      | Output raw conflict payload as structured JSON.                                             |
| `--db-url`                  | `DATABASE_URL`           | `None`       | Database connection URL override.                                                           |
| `--api-url`                 | `ECU_HOCKEY_API_URL`     | `None`       | Remote ECU Hockey API base URL (e.g. `https://ecu-hockey-api.onrender.com`).                |
| `--token`                   | `ECU_HOCKEY_ADMIN_TOKEN` | `None`       | Administrative authentication Bearer token for protected remote endpoints.                  |

**Examples:**

```bash
# List all active schedule discrepancies from local database
ecu-hockey conflicts

# Show only discrepancies requiring manual administrative review
ecu-hockey conflicts --requires-review

# Filter discrepancies affecting game start times with critical severity
ecu-hockey conflicts --field-name start_time --severity critical

# Paginate through conflicts with limit and offset
ecu-hockey conflicts --limit 10 --offset 20

# Output raw conflicts payload as JSON
ecu-hockey conflicts --json | jq .

# Inspect discrepancies on remote production deployment (authenticated)
ecu-hockey conflicts --api-url https://ecu-hockey-api.onrender.com --token secret-token-123 --requires-review
```

______________________________________________________________________

### 3.7. `ecu-hockey serve`

Starts the Uvicorn ASGI server hosting the FastAPI calendar and schedule service, providing canonical live feeds (`/schedule.ics`, `/schedule.json`, `/schedule.csv`, `/schedule.pdf`, `/schedule.rss`, `/schedule.atom`), backward-compatible aliases (`/calendar.ics`, `/feed.rss`), responsive HTML dashboards (`/schedule`, `/health`, `/sync`, `/conflicts`), and interactive OpenAPI documentation (`/docs`, `/redoc`).

```bash
ecu-hockey serve [OPTIONS]
```

**Options:**

| Option                     | Environment Variable | Default        | Description                                                    |
| :------------------------- | :------------------- | :------------- | :------------------------------------------------------------- |
| `-h, --host`               | —                    | `127.0.0.1`    | Network interface host to bind the server.                     |
| `-p, --port`               | —                    | `8000`         | TCP port number to listen on.                                  |
| `--reload / --no-reload`   | —                    | `--no-reload`  | Enable auto-reload on filesystem changes (development mode).   |
| `--db-url`                 | `DATABASE_URL`       | `None`         | Database connection URL override.                              |
| `--migrate / --no-migrate` | —                    | `--no-migrate` | Run database schema migrations to head before starting server. |

**Examples:**

```bash
# Start local calendar server
ecu-hockey serve

# Start server bound to all interfaces on port 8080 with reload
ecu-hockey serve -h 0.0.0.0 -p 8080 --reload
```

______________________________________________________________________

### 3.8. `ecu-hockey notify`

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

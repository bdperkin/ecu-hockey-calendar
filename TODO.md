# Roadmap and Implementation Plan

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. System Architecture Overview](#1-system-architecture-overview)
- [2. Planned Milestones and Phases](#2-planned-milestones-and-phases)
  - [2.1. Milestone 1: v0.1.0 - Foundation & Core Architecture (Complete)](#21-milestone-1-v010---foundation--core-architecture-complete)
  - [2.2. Milestone 2: v0.2.0 - Storage Layer & Multi-Source Scrapers (Complete)](#22-milestone-2-v020---storage-layer--multi-source-scrapers-complete)
    - [2.2.1. Phase 2.1: Relational Persistence & Schema Migrations](#221-phase-21-relational-persistence--schema-migrations)
    - [2.2.2. Phase 2.2: Primary & League Web Crawlers](#222-phase-22-primary--league-web-crawlers)
    - [2.2.3. Phase 2.3: Social & Opponent Reverse Crawlers](#223-phase-23-social--opponent-reverse-crawlers)
  - [2.3. Milestone 3: v0.3.0 - Schedule Reconciliation, Change Detection & Alerts (Complete)](#23-milestone-3-v030---schedule-reconciliation-change-detection--alerts-complete)
    - [2.3.1. Phase 3.1: Tooling & Release Infrastructure Hygiene](#231-phase-31-tooling--release-infrastructure-hygiene)
    - [2.3.2. Phase 3.2: Reconciliation & Conflict Resolution Engine](#232-phase-32-reconciliation--conflict-resolution-engine)
    - [2.3.3. Phase 3.3: Change State Detection & Audit History](#233-phase-33-change-state-detection--audit-history)
    - [2.3.4. Phase 3.4: Webhook Notification Dispatcher](#234-phase-34-webhook-notification-dispatcher)
    - [2.3.5. Phase 3.5: Documentation Alignment](#235-phase-35-documentation-alignment)
  - [2.4. Milestone 4: v0.4.0 - Calendar & Data API Service](#24-milestone-4-v040---calendar--data-api-service)
    - [2.4.1. Phase 4.1: Public Calendar & Data Feeds](#241-phase-41-public-calendar--data-feeds)
    - [2.4.2. Phase 4.2: Diagnostics & Administration Endpoints](#242-phase-42-diagnostics--administration-endpoints)
    - [2.4.3. Phase 4.3: Documentation Alignment](#243-phase-43-documentation-alignment)
    - [2.4.4. Phase 4.4: Release Alignment & Milestone Reconciliation](#244-phase-44-release-alignment--milestone-reconciliation)
  - [2.5. Milestone 5: v0.5.0 - CLI, Automation & Production Deployment](#25-milestone-5-v050---cli-automation--production-deployment)
    - [2.5.1. Phase 5.1: Unified Command-Line Interface](#251-phase-51-unified-command-line-interface)
    - [2.5.2. Phase 5.2: Production Deployment Strategy & Hosting Analysis](#252-phase-52-production-deployment-strategy--hosting-analysis)
    - [2.5.3. Phase 5.3: Scheduled Automation & CI Sync Workflows](#253-phase-53-scheduled-automation--ci-sync-workflows)
    - [2.5.4. Phase 5.4: GitHub Pages Documentation & Static Calendar Deployment (Complete)](#254-phase-54-github-pages-documentation--static-calendar-deployment-complete)
    - [2.5.5. Phase 5.5: Documentation Alignment](#255-phase-55-documentation-alignment)
  - [2.6. Milestone 6: v0.6.0 - Fan Engagement, Syndication & Export Formats](#26-milestone-6-v060---fan-engagement-syndication--export-formats)
    - [2.6.1. Phase 6.1: Responsive HTML Interface & Embeds](#261-phase-61-responsive-html-interface--embeds)
    - [2.6.2. Phase 6.2: RSS / Atom Syndication Feeds](#262-phase-62-rss--atom-syndication-feeds)
    - [2.6.3. Phase 6.3: Printable Schedule Grid PDF Generation](#263-phase-63-printable-schedule-grid-pdf-generation)
- [3. CodeQL Security & Quality Audit Trail](#3-codeql-security--quality-audit-trail)
- [4. Implementation Sequencing & Dependency Graph](#4-implementation-sequencing--dependency-graph)
  - [4.1. Sequencing Rationale](#41-sequencing-rationale)

______________________________________________________________________

<!--TOC-->

This document establishes the canonical implementation roadmap and tracking plan for the **ECU Ice Hockey Schedule Aggregator & Calendar Service**.

______________________________________________________________________

## 1. System Architecture Overview

The platform is designed around three decoupled, production-grade core tiers:

```mermaid
flowchart TD
    subgraph SOT["Data Sources"]
        S1["ecuhockey.com/schedule (Primary SOT)"]
        S2["acchockey.com (League Schedule)"]
        S3["ecuhockey.com/tickets (Ticketing)"]
        S4["Instagram @ecuicehockey (Social)"]
        S5["Opponent Feeds (Reverse Check)"]
    end

    subgraph WORKER["Ingestion & Reconciliation Engine"]
        W1["Multi-Source Crawlers"]
        W2["Reconciliation & Conflict Resolver"]
        W3["Change Detection Engine"]
        W4["Webhook Dispatcher"]
    end

    subgraph DB["Storage Layer"]
        D1["PostgreSQL / SQLite (SQLAlchemy + Alembic)"]
        D2["Master Schedule & Snapshots"]
        D3["Sync Audit & Conflict Logs"]
    end

    subgraph API["FastAPI Calendar & Data Service"]
        A1["/calendar.ics (RFC 5545, Webcal)"]
        A2["/api/schedule.json"]
        A3["/api/schedule.csv"]
        A4["/health & /api/v1/conflicts"]
    end

    subgraph CLIENTS["Subscribers & Consumers"]
        C1["Apple Calendar / Google Calendar"]
        C2["Web & Mobile Clients"]
        C3["Discord / Slack / Telegram Webhooks"]
        C4["ECU Hockey CLI (ecu-hockey)"]
    end

    SOT --> W1
    W1 --> W2
    W2 --> DB
    W2 --> W3
    W3 --> W4
    W4 --> C3
    DB --> API
    API --> C1
    API --> C2
    DB --> C4
```

1. **Data Ingestion & Cross-Reference Engine (Worker):** Periodically scrapes multiple upstream sources, reconciles discrepancies, detects atomic changes (`CREATED`, `UPDATED`, `DELETED`, `CONFLICT_DETECTED`), and triggers webhook alerts.
2. **Calendar & Data API (FastAPI Application):** Lightweight, high-performance web service delivering RFC 5545 compliant `.ics` feeds (with `webcal://` support), normalized JSON feeds, and downloadable CSV exports.
3. **Storage & Persistence Layer:** Relational database (PostgreSQL in production, SQLite in development) managed with SQLAlchemy 2.0 and Alembic migrations, archiving raw source snapshots and synchronization audits.

______________________________________________________________________

## 2. Planned Milestones and Phases

### 2.1. Milestone 1: v0.1.0 - Foundation & Core Architecture (Complete)

- [x] Configure native `uv` project with dynamic versioning (`hatchling` + `hatch-vcs`) (Merged in [PR #1](https://github.com/bdperkin/ecu-hockey-calendar/pull/1)).
- [x] Implement strict `ruff` and `ty` type checking configurations (Merged in [PR #1](https://github.com/bdperkin/ecu-hockey-calendar/pull/1)).
- [x] Establish comprehensive test suite with 100% test and branch coverage (Merged in [PR #1](https://github.com/bdperkin/ecu-hockey-calendar/pull/1)).
- [x] Set up Sphinx documentation with markdown (`myst-parser`) and Furo theme (Merged in [PR #1](https://github.com/bdperkin/ecu-hockey-calendar/pull/1)).
- [x] Implement quality linters: Pylint (10.00/10), Codespell, Interrogate, Deptry, Vulture, Radon/Xenon (Merged in [PR #1](https://github.com/bdperkin/ecu-hockey-calendar/pull/1)).
- [x] Configure comprehensive pre-commit suite (73 hooks) and pre-commit.ci (Merged in [PR #1](https://github.com/bdperkin/ecu-hockey-calendar/pull/1)).
- [x] Configure GitHub Actions CI matrix, CodeQL security analysis, Dependabot, and Semantic Release (Merged in [PR #1](https://github.com/bdperkin/ecu-hockey-calendar/pull/1), [PR #20](https://github.com/bdperkin/ecu-hockey-calendar/pull/20), [PR #21](https://github.com/bdperkin/ecu-hockey-calendar/pull/21), Dependabot PRs [#27](https://github.com/bdperkin/ecu-hockey-calendar/pull/27), [#28](https://github.com/bdperkin/ecu-hockey-calendar/pull/28), [#29](https://github.com/bdperkin/ecu-hockey-calendar/pull/29), [#30](https://github.com/bdperkin/ecu-hockey-calendar/pull/30), [#31](https://github.com/bdperkin/ecu-hockey-calendar/pull/31)).
- [x] Configure repository settings (disable Projects & Wiki, enable auto-merge, branch protection) (Merged in [PR #1](https://github.com/bdperkin/ecu-hockey-calendar/pull/1)).
- [x] Integrate scraper specification and roadmap into `TODO.md` (Merged in [PR #17](https://github.com/bdperkin/ecu-hockey-calendar/pull/17)).

### 2.2. Milestone 2: v0.2.0 - Storage Layer & Multi-Source Scrapers (Complete)

#### 2.2.1. Phase 2.1: Relational Persistence & Schema Migrations

- [x] **[#2](https://github.com/bdperkin/ecu-hockey-calendar/issues/2) - feat(storage): implement SQLAlchemy models and Alembic migration pipeline** (Merged in [PR #24](https://github.com/bdperkin/ecu-hockey-calendar/pull/24))
  - **Summary:** Set up SQLAlchemy 2.0 ORM models for games, teams, sources, raw snapshots, and sync audits.
  - **Description:** Support PostgreSQL for production and SQLite for local development. Define `Team`, `Game`, `DataSource`, `RawSnapshot`, and `SyncAudit` tables. Configure Alembic migration environment with automated schema generation.
- [x] **[#25](https://github.com/bdperkin/ecu-hockey-calendar/issues/25) - fix(security): resolve CodeQL security and quality code scanning alerts** (Merged in [PR #26](https://github.com/bdperkin/ecu-hockey-calendar/pull/26))
  - **Summary:** Resolve 7 CodeQL code scanning alerts (Alerts #1–#4 `py/unused-global-variable`, Alerts #5–#6 `py/unreachable-statement`, Alert #7 `py/unused-import`).
  - **Description:** Add explicit `__all__` exports in Alembic migrations and `alembic/env.py`, and refactor session rollback test blocks to use explicit exception handling.

#### 2.2.2. Phase 2.2: Primary & League Web Crawlers

- [x] **[#3](https://github.com/bdperkin/ecu-hockey-calendar/issues/3) - feat(ingestion): build resilient crawler for primary ECU Hockey schedule site** (Merged in [PR #32](https://github.com/bdperkin/ecu-hockey-calendar/pull/32))
  - **Summary:** Build asynchronous crawler for `https://www.ecuhockey.com/schedule/upcoming`.
  - **Description:** Implement `httpx` + `BeautifulSoup4` parser with retry and backoff logic. Extract dates, times, home/away status, opponents, venues, scores, and game status.
- [x] **[#4](https://github.com/bdperkin/ecu-hockey-calendar/issues/4) - feat(ingestion): implement ACC Hockey league schedule page parser** (Merged in [PR #33](https://github.com/bdperkin/ecu-hockey-calendar/pull/33))
  - **Summary:** Ingest conference games and scores from `https://www.acchockey.com/page/show/9602441-east-carolina`.
  - **Description:** Handle SportEngine markup, normalize opponent names, and capture official conference verification metadata.
- [x] **[#5](https://github.com/bdperkin/ecu-hockey-calendar/issues/5) - feat(ingestion): parse ticket sales page for game schedules and promotions** (Merged in [PR #34](https://github.com/bdperkin/ecu-hockey-calendar/pull/34))
  - **Summary:** Scrape ticketing information from `https://www.ecuhockey.com/tickets`.
  - **Description:** Extract home games, promotional theme nights, ticket pricing, and ticketing links to enrich calendar event descriptions.
- [x] **fix(ingestion): resolve CodeQL alerts for fallback parser exception handling** (Merged in [PR #35](https://github.com/bdperkin/ecu-hockey-calendar/pull/35))
  - **Summary:** Resolve CodeQL Alerts #8 and #9 (`py/empty-except`) in fallback ingestion parser.
  - **Description:** Add explanatory comments and structured logger debug warnings inside empty fallback exception blocks.

#### 2.2.3. Phase 2.3: Social & Opponent Reverse Crawlers

- [x] **[#6](https://github.com/bdperkin/ecu-hockey-calendar/issues/6) - feat(ingestion): create resilient Instagram feed parser for game announcements** (Merged in [PR #36](https://github.com/bdperkin/ecu-hockey-calendar/pull/36))
  - **Summary:** Extract schedule announcements and time changes from `https://www.instagram.com/ecuicehockey/`.
  - **Description:** Integrate Instagram Graph API / resilient feed parser with exponential backoff and rate-limit mitigation.
- [x] **[#7](https://github.com/bdperkin/ecu-hockey-calendar/issues/7) - feat(ingestion): automated opponent schedule reverse lookup and cross-check** (Merged in [PR #37](https://github.com/bdperkin/ecu-hockey-calendar/pull/37))
  - **Summary:** Automatically query and cross-verify preliminary game data against opponent schedule sources.
  - **Description:** Maintain opponent directory (UNC, NC State, Virginia Tech, Wake Forest, etc.) and cross-check dates, venues, and times.

### 2.3. Milestone 3: v0.3.0 - Schedule Reconciliation, Change Detection & Alerts (Complete)

#### 2.3.1. Phase 3.1: Tooling & Release Infrastructure Hygiene

- [x] **[#47](https://github.com/bdperkin/ecu-hockey-calendar/issues/47) - chore(roadmap): remove ecu_hockey_scraper_prompt.md and perform comprehensive TODO.md audit** (Merged in [PR #49](https://github.com/bdperkin/ecu-hockey-calendar/pull/49))
  - **Summary:** Remove obsolete prompt document, reconcile all open/closed issues and PRs, and optimize implementation ordering.
  - **Description:** Clean up repository root, ensure bidirectional traceability across all issues and PRs, and sequence development milestones for maximum velocity.
- [x] **[#44](https://github.com/bdperkin/ecu-hockey-calendar/issues/44) - chore(tooling): migrate PyMarkdown configuration from .pymarkdown.json into pyproject.toml** (Merged in [PR #52](https://github.com/bdperkin/ecu-hockey-calendar/pull/52))
  - **Summary:** Consolidate markdown linter configuration into native `pyproject.toml`.
  - **Description:** Add `[tool.pymarkdown]` section to `pyproject.toml`, remove `.pymarkdown.json`, and update pre-commit / CI invocations.
- [x] **[#45](https://github.com/bdperkin/ecu-hockey-calendar/issues/45) - fix(ci): investigate and resolve why CHANGELOG.md is not updated by Python Semantic Release** (Merged in [PR #54](https://github.com/bdperkin/ecu-hockey-calendar/pull/54), pre-commit hook fixed in [PR #56](https://github.com/bdperkin/ecu-hockey-calendar/pull/56))
  - **Summary:** Configure PSR changelog update insertion markers, repository secrets, and CI release permissions.
  - **Description:** Add `<!-- version list -->` insertion flag to `CHANGELOG.md`, backfill historical release entries, configure `RELEASE_TOKEN` secret for branch protection bypass, and exclude `CHANGELOG.md` from markdown pre-commit hooks.
- [x] **[#48](https://github.com/bdperkin/ecu-hockey-calendar/issues/48) - fix(release): diagnose and align release versioning with project milestones (currently at v0.8.2 instead of v0.2.0)** (Merged in [PR #57](https://github.com/bdperkin/ecu-hockey-calendar/pull/57))
  - **Summary:** Align project version tags and package metadata with planned milestones.
  - **Description:** Adjust tag namespace and reset release version progression so that Milestone 3 releases as `v0.3.0`.

#### 2.3.2. Phase 3.2: Reconciliation & Conflict Resolution Engine

- [x] **[#8](https://github.com/bdperkin/ecu-hockey-calendar/issues/8) - feat(reconciliation): multi-source schedule cross-referencing and conflict resolution engine** (Merged in [PR #38](https://github.com/bdperkin/ecu-hockey-calendar/pull/38), fixed in [PR #40](https://github.com/bdperkin/ecu-hockey-calendar/pull/40) & [PR #42](https://github.com/bdperkin/ecu-hockey-calendar/pull/42))
  - **Summary:** Cross-reference data across disparate sources using deterministic and fuzzy scoring.
  - **Description:** Enforce configurable precedence hierarchy (Primary SOT + League > Ticketing/Social > Opponent). Detect discrepancies and flag high-confidence conflicts for review.
- [x] **[#39](https://github.com/bdperkin/ecu-hockey-calendar/issues/39) - fix(security): resolve CodeQL alert 12 for unused global variable in fuzzy_matcher** (Merged in [PR #40](https://github.com/bdperkin/ecu-hockey-calendar/pull/40))
  - **Summary:** Export `GENERIC_COLLEGE_TERMS` in `fuzzy_matcher.py` `__all__`.
  - **Description:** Resolve CodeQL `py/unused-global-variable` alert and verify tuple contents with unit tests.
- [x] **[#41](https://github.com/bdperkin/ecu-hockey-calendar/issues/41) - fix(security): resolve CodeQL alert 13 for import and import-from in test_reconciliation_fuzzy_matcher** (Merged in [PR #42](https://github.com/bdperkin/ecu-hockey-calendar/pull/42), roadmap updated in [PR #43](https://github.com/bdperkin/ecu-hockey-calendar/pull/43))
  - **Summary:** Remove redundant module alias import in reconciliation test suite.
  - **Description:** Resolve CodeQL `py/import-and-import-from` alert while preserving test coverage.

#### 2.3.3. Phase 3.3: Change State Detection & Audit History

- [x] **[#9](https://github.com/bdperkin/ecu-hockey-calendar/issues/9) - feat(reconciliation): change detection and sync state tracking engine** (Merged in [PR #58](https://github.com/bdperkin/ecu-hockey-calendar/pull/58))
  - **Summary:** Track atomic game state transitions (`CREATED`, `UPDATED`, `DELETED`, `CONFLICT_DETECTED`).
  - **Description:** Generate field-level diffs, store historical snapshots, and log sync cycle audits.

#### 2.3.4. Phase 3.4: Webhook Notification Dispatcher

- [x] **[#15](https://github.com/bdperkin/ecu-hockey-calendar/issues/15) - feat(notifications): multi-platform webhook alerting for schedule updates and conflicts** (Merged in [PR #60](https://github.com/bdperkin/ecu-hockey-calendar/pull/60))
  - **Summary:** Broadcast rich notifications to Discord, Slack, and Telegram channels.
  - **Description:** Dispatch formatted embeds for schedule additions, game updates, cancellations, and active conflict alerts.

#### 2.3.5. Phase 3.5: Documentation Alignment

- [x] **[#46](https://github.com/bdperkin/ecu-hockey-calendar/issues/46) - docs: update README.md and Sphinx documentation to reflect current project capabilities**
  - **Summary:** Update `README.md` and Sphinx docs in `docs/` to reflect current project capabilities.
  - **Description:** Document multi-source crawler architecture, SQLAlchemy persistence layer, reconciliation engine, change detection, and webhook notifications with usage examples.

### 2.4. Milestone 4: v0.4.0 - Calendar & Data API Service

#### 2.4.1. Phase 4.1: Public Calendar & Data Feeds

- [x] **[#10](https://github.com/bdperkin/ecu-hockey-calendar/issues/10) - feat(api): RFC 5545 iCalendar (.ics) subscription endpoint and webcal support**
  - **Summary:** Provide `/calendar.ics` adhering strictly to RFC 5545 with `webcal://` subscription support.
  - **Description:** Full compatibility with Apple Calendar, Google Calendar, and Outlook with deterministic UIDs, alarms, locations, and descriptions.
- [x] **[#11](https://github.com/bdperkin/ecu-hockey-calendar/issues/11) - feat(api): public JSON and CSV master schedule data feeds**
  - **Summary:** Provide machine-readable `/api/schedule.json` and downloadable `/api/schedule.csv`.
  - **Description:** Normalized feeds with query filters (`season`, `opponent`, `home_only`, `status`) and OpenAPI interactive documentation.

#### 2.4.2. Phase 4.2: Diagnostics & Administration Endpoints

- [x] **[#12](https://github.com/bdperkin/ecu-hockey-calendar/issues/12) - feat(api): health check, sync diagnostics, and conflict review endpoints**
  - **Summary:** Provide operational endpoints for system health, sync telemetry, and conflict review.
  - **Description:** Implement `/health`, `/api/v1/sync/status`, and `/api/v1/conflicts` with authentication for administrative actions.

#### 2.4.3. Phase 4.3: Documentation Alignment

- [x] **[#62](https://github.com/bdperkin/ecu-hockey-calendar/issues/62) - docs: update README.md and Sphinx documentation to reflect current project capabilities**
  - **Summary:** Update `README.md` and Sphinx docs in `docs/` to reflect public API endpoints and calendar feeds.
  - **Description:** Document `/calendar.ics`, `/api/schedule.json`, `/api/schedule.csv`, OpenAPI `/docs`, and administration diagnostics endpoints.

#### 2.4.4. Phase 4.4: Release Alignment & Milestone Reconciliation

- [x] **[#73](https://github.com/bdperkin/ecu-hockey-calendar/issues/73) - fix(release): diagnose and align release versioning with project milestones (currently at v0.2.7 instead of v0.4.0)**
  - **Summary:** Reconcile repository releases and git tags with completed milestones (v0.2.0, v0.3.0, v0.4.0) and fix PSR minor bumping.
  - **Description:** Resolve discrepancy between PSR parser rules, conventional-commit types, and workflow triggers to ensure Milestone 4 is released as `v0.4.0` and pre-1.0 milestone versioning is preserved.

### 2.5. Milestone 5: v0.5.0 - CLI, Automation & Production Deployment

#### 2.5.1. Phase 5.1: Unified Command-Line Interface

- [x] **[#13](https://github.com/bdperkin/ecu-hockey-calendar/issues/13) - feat(cli): command-line interface for schedule sync, inspection, and export**
  - **Summary:** Rich CLI interface (`ecu-hockey`) with subcommands: `sync`, `status`, `export`, `conflicts`, and `serve`.
  - **Description:** Provide interactive terminal output using `rich` for formatting, status tables, and diagnostics.

#### 2.5.2. Phase 5.2: Production Deployment Strategy & Hosting Analysis

- [x] **[#14](https://github.com/bdperkin/ecu-hockey-calendar/issues/14) - docs(deployment): architectural hosting analysis and production deployment guide**
  - **Summary:** Author `DEPLOYMENT.md` evaluating hosting providers, architecture, and operational practices.
  - **Description:** Compare Render, Railway, Fly.io, and AWS Lambda + EventBridge. Address Instagram rate limits, proxy rotation, persistent database volumes, SSL certificates, and container configuration.

#### 2.5.3. Phase 5.3: Scheduled Automation & CI Sync Workflows

- [ ] **[#16](https://github.com/bdperkin/ecu-hockey-calendar/issues/16) - ci(automation): automated scheduled ingestion and calendar release workflow**
  - **Summary:** GitHub Actions scheduled workflow running periodic syncs and publishing static calendar releases.
  - **Description:** Automate periodic schedule checks, publish calendar artifacts, and trigger webhooks on changes.

#### 2.5.4. Phase 5.4: GitHub Pages Documentation & Static Calendar Deployment (Complete)

- [x] **[#18](https://github.com/bdperkin/ecu-hockey-calendar/issues/18) - ci(pages): automated GitHub Pages deployment to `https://bdperkin.github.io/ecu-hockey-calendar/`** (Merged in [PR #19](https://github.com/bdperkin/ecu-hockey-calendar/pull/19), [PR #22](https://github.com/bdperkin/ecu-hockey-calendar/pull/22), [PR #23](https://github.com/bdperkin/ecu-hockey-calendar/pull/23))
  - **Summary:** Configure automated Sphinx documentation and static calendar asset publishing to GitHub Pages.
  - **Description:** Implement `.github/workflows/pages.yml` with `actions/upload-pages-artifact` and `actions/deploy-pages`. Build Sphinx documentation with Furo theme and publish static calendar artifacts (`calendar.ics`, `schedule.json`, `schedule.csv`) to `https://bdperkin.github.io/ecu-hockey-calendar/`.

#### 2.5.5. Phase 5.5: Documentation Alignment

- [ ] **[#63](https://github.com/bdperkin/ecu-hockey-calendar/issues/63) - docs: update README.md and Sphinx documentation to reflect current project capabilities**
  - **Summary:** Update `README.md` and Sphinx docs in `docs/` to reflect end-to-end capabilities, CLI, and production deployment.
  - **Description:** Document `ecu-hockey` CLI subcommands, production deployment guides, static GitHub Pages calendar feeds, and automated CI workflows.

### 2.6. Milestone 6: v0.6.0 - Fan Engagement, Syndication & Export Formats

#### 2.6.1. Phase 6.1: Responsive HTML Interface & Embeds

- [ ] **[#77](https://github.com/bdperkin/ecu-hockey-calendar/issues/77) - feat(web): responsive HTML schedule view and embeddable iframe widget**
  - **Summary:** Mobile-first HTML schedule view and lightweight embeddable iframe route powered by Jinja2 templates.
  - **Description:** Provide `/schedule` web interface with ECU branding, fixture cards, and ticket links, plus `/schedule/embed` stripped-down widget and iframe snippet for external community sites.

#### 2.6.2. Phase 6.2: RSS / Atom Syndication Feeds

- [ ] **[#78](https://github.com/bdperkin/ecu-hockey-calendar/issues/78) - feat(syndication): RSS and Atom XML schedule syndication feeds for media and automation**
  - **Summary:** Dynamic RSS 2.0 and Atom 1.0 XML feeds powered by `feedgen` for media outlets and automation workflows.
  - **Description:** Provide `/feed.rss` and `/feed.atom` feeds exposing fixture announcements, time changes, and final scores for integration with Zapier, Make.com, and Discord bots.

#### 2.6.3. Phase 6.3: Printable Schedule Grid PDF Generation

- [ ] **[#79](https://github.com/bdperkin/ecu-hockey-calendar/issues/79) - feat(export): printable schedule grid PDF generation for parents and coaches**
  - **Summary:** High-fidelity printable PDF schedule export using WeasyPrint for family refrigerators and bench clipboards.
  - **Description:** Provide `/api/schedule.pdf` and CLI `ecu-hockey export -f pdf` rendering a high-contrast, print-optimized calendar grid on standard US Letter layout.

______________________________________________________________________

## 3. CodeQL Security & Quality Audit Trail

The repository strictly enforces CodeQL security and code scanning analysis across all branches and pull requests. All detected findings have been remediated, tested, and verified with 0 active alerts:

| Alert # | Rule ID                     | Classification | Location                                                  | Resolution Details                                                         | Fix Reference                                                                                                                              |
| ------- | --------------------------- | -------------- | --------------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| #1      | `py/unused-global-variable` | Quality        | `alembic/versions/20260906_0155_...py`                    | Added explicit `__all__` export for migration revision identifiers         | [PR #26](https://github.com/bdperkin/ecu-hockey-calendar/pull/26) (Issue [#25](https://github.com/bdperkin/ecu-hockey-calendar/issues/25)) |
| #2      | `py/unused-global-variable` | Quality        | `alembic/versions/20260906_0155_...py`                    | Added explicit `__all__` export for migration revision identifiers         | [PR #26](https://github.com/bdperkin/ecu-hockey-calendar/pull/26) (Issue [#25](https://github.com/bdperkin/ecu-hockey-calendar/issues/25)) |
| #3      | `py/unused-global-variable` | Quality        | `alembic/versions/20260906_0155_...py`                    | Added explicit `__all__` export for migration revision identifiers         | [PR #26](https://github.com/bdperkin/ecu-hockey-calendar/pull/26) (Issue [#25](https://github.com/bdperkin/ecu-hockey-calendar/issues/25)) |
| #4      | `py/unused-global-variable` | Quality        | `alembic/versions/20260906_0155_...py`                    | Added explicit `__all__` export for migration revision identifiers         | [PR #26](https://github.com/bdperkin/ecu-hockey-calendar/pull/26) (Issue [#25](https://github.com/bdperkin/ecu-hockey-calendar/issues/25)) |
| #5      | `py/unreachable-statement`  | Quality        | `tests/test_storage_engine.py`                            | Refactored session rollback tests with explicit exception catching         | [PR #26](https://github.com/bdperkin/ecu-hockey-calendar/pull/26) (Issue [#25](https://github.com/bdperkin/ecu-hockey-calendar/issues/25)) |
| #6      | `py/unreachable-statement`  | Quality        | `tests/test_storage_engine.py`                            | Refactored session rollback tests with explicit exception catching         | [PR #26](https://github.com/bdperkin/ecu-hockey-calendar/pull/26) (Issue [#25](https://github.com/bdperkin/ecu-hockey-calendar/issues/25)) |
| #7      | `py/unused-import`          | Quality        | `alembic/env.py`                                          | Added explicit `__all__` export for target metadata                        | [PR #26](https://github.com/bdperkin/ecu-hockey-calendar/pull/26) (Issue [#25](https://github.com/bdperkin/ecu-hockey-calendar/issues/25)) |
| #8      | `py/empty-except`           | Quality        | `src/ecu_hockey_calendar/ingestion/parsers.py`            | Added debug warning log and comment explaining empty fallback parse block  | [PR #35](https://github.com/bdperkin/ecu-hockey-calendar/pull/35)                                                                          |
| #9      | `py/empty-except`           | Quality        | `src/ecu_hockey_calendar/ingestion/parsers.py`            | Added debug warning log and comment explaining empty fallback parse block  | [PR #35](https://github.com/bdperkin/ecu-hockey-calendar/pull/35)                                                                          |
| #12     | `py/unused-global-variable` | Quality        | `src/ecu_hockey_calendar/reconciliation/fuzzy_matcher.py` | Added `GENERIC_COLLEGE_TERMS` to module `__all__` export list              | [PR #40](https://github.com/bdperkin/ecu-hockey-calendar/pull/40) (Issue [#39](https://github.com/bdperkin/ecu-hockey-calendar/issues/39)) |
| #13     | `py/import-and-import-from` | Quality        | `tests/test_reconciliation_fuzzy_matcher.py`              | Cleaned redundant module import and standardized direct member imports     | [PR #42](https://github.com/bdperkin/ecu-hockey-calendar/pull/42) (Issue [#41](https://github.com/bdperkin/ecu-hockey-calendar/issues/41)) |
| #14     | `py/stack-trace-exposure`   | Security       | `src/ecu_hockey_calendar/api/routes/health.py`            | Log exceptions internally on server and return generic safe error messages | [PR #70](https://github.com/bdperkin/ecu-hockey-calendar/pull/70) (Issue [#69](https://github.com/bdperkin/ecu-hockey-calendar/issues/69)) |

______________________________________________________________________

## 4. Implementation Sequencing & Dependency Graph

To optimize delivery velocity and maintain continuous quality, issues are sequenced based on architectural dependencies and release hygiene:

```mermaid
flowchart TD
    subgraph HYGIENE["Stage 1: Tooling & Release Hygiene (Complete)"]
        T47["#47: Remove Prompt & Audit TODO.md"]
        T44["#44: Migrate PyMarkdown to pyproject.toml"]
        T45["#45: Fix Semantic Release CHANGELOG.md"]
        T48["#48: Align Release Versioning with Milestones"]
    end

    subgraph M3["Stage 2: Milestone 3 Completion (Complete)"]
        T9["#9: Change Detection & State Tracking"]
        T15["#15: Webhook Notification Dispatcher"]
        T46["#46: README & Sphinx Docs Update"]
    end

    subgraph M4["Stage 3: Milestone 4 (API Service)"]
        T10["#10: RFC 5545 iCalendar (.ics) Feed"]
        T11["#11: Public JSON & CSV Feeds"]
        T12["#12: Health & Diagnostics Endpoints"]
        T62["#62: README & Sphinx Docs Update (v0.4.0)"]
        T73["#73: Release Version Alignment (v0.4.0)"]
    end

    subgraph M5["Stage 4: Milestone 5 (CLI, Deployment & Automation)"]
        T13["#13: Unified CLI (ecu-hockey)"]
        T14["#14: DEPLOYMENT.md Hosting Analysis"]
        T16["#16: Scheduled Ingestion CI Workflow"]
        T63["#63: README & Sphinx Docs Update (v0.5.0)"]
    end

    subgraph M6["Stage 5: Milestone 6 (Fan Engagement & Formats)"]
        T77["#77: Responsive HTML View & Embeds"]
        T78["#78: RSS / Atom Syndication Feeds"]
        T79["#79: Printable Schedule PDF Export"]
    end

    T47 --> T44
    T44 --> T45
    T45 --> T48
    T48 --> T9
    T9 --> T15
    T15 --> T46
    T46 --> T10
    T10 --> T11
    T11 --> T12
    T12 --> T62
    T62 --> T73
    T73 --> T13
    T13 --> T14
    T14 --> T16
    T16 --> T63
    T63 --> T77
    T77 --> T78
    T78 --> T79
```

### 4.1. Sequencing Rationale

1. **Tooling & Release Hygiene**:
   - Issue **[#47](https://github.com/bdperkin/ecu-hockey-calendar/issues/47)** removes obsolete specification prompts and establishes complete issue/PR/CodeQL roadmap traceability.
   - Issue **[#44](https://github.com/bdperkin/ecu-hockey-calendar/issues/44)** consolidates `.pymarkdown.json` into `pyproject.toml`, eliminating unnecessary root config files.
   - Issue **[#45](https://github.com/bdperkin/ecu-hockey-calendar/issues/45)** and Issue **[#48](https://github.com/bdperkin/ecu-hockey-calendar/issues/48)** fix Python Semantic Release changelog generation and align release versioning with project milestones *before* additional features are merged.
2. **Milestone 3 Completion**:
   - Issue **[#9](https://github.com/bdperkin/ecu-hockey-calendar/issues/9)** (Change Detection) directly builds upon the multi-source reconciliation engine completed in Issue **[#8](https://github.com/bdperkin/ecu-hockey-calendar/issues/8)**.
   - Issue **[#15](https://github.com/bdperkin/ecu-hockey-calendar/issues/15)** (Webhooks) dispatches the atomic state change events detected by Issue **[#9](https://github.com/bdperkin/ecu-hockey-calendar/issues/9)**.
   - Issue **[#46](https://github.com/bdperkin/ecu-hockey-calendar/issues/46)** documents the completed Ingestion, Storage, Reconciliation, and Notification systems.
3. **Milestone 4 (API Feeds)**:
   - Issues **[#10](https://github.com/bdperkin/ecu-hockey-calendar/issues/10)** and **[#11](https://github.com/bdperkin/ecu-hockey-calendar/issues/11)** expose the reconciled database records as standard RFC 5545 iCalendar (`.ics`), JSON, and CSV feeds via FastAPI.
   - Issue **[#12](https://github.com/bdperkin/ecu-hockey-calendar/issues/12)** adds diagnostics and conflict management endpoints.
   - Issue **[#62](https://github.com/bdperkin/ecu-hockey-calendar/issues/62)** updates documentation and Sphinx guides for calendar feeds and API operational endpoints.
   - Issue **[#73](https://github.com/bdperkin/ecu-hockey-calendar/issues/73)** diagnoses version divergence, aligns git tags and GitHub Releases with completed Milestones 2, 3, and 4 (`v0.4.0`), and resolves release automation configuration before beginning Milestone 5.
4. **Milestone 5 (CLI, Deployment & Automation)**:
   - Issue **[#13](https://github.com/bdperkin/ecu-hockey-calendar/issues/13)** unifies crawlers, reconciliation, database operations, and API serving into an interactive CLI.
   - Issue **[#14](https://github.com/bdperkin/ecu-hockey-calendar/issues/14)** analyzes hosting architectures in `DEPLOYMENT.md`.
   - Issue **[#16](https://github.com/bdperkin/ecu-hockey-calendar/issues/16)** automates scheduled ingestion runs in GitHub Actions, publishing static calendar feeds to GitHub Pages (leveraging the pipeline from Issue **[#18](https://github.com/bdperkin/ecu-hockey-calendar/issues/18)**).
   - Issue **[#63](https://github.com/bdperkin/ecu-hockey-calendar/issues/63)** finalizes project documentation, user guides, and Sphinx docs for the CLI and production deployment workflows.
5. **Milestone 6 (Fan Engagement, Syndication & Export Formats)**:
   - Issue **[#77](https://github.com/bdperkin/ecu-hockey-calendar/issues/77)** implements the highest-priority direct fan engagement channel: a responsive Jinja2-rendered HTML schedule view (`/schedule`) and stripped-down iframe embed widget (`/schedule/embed`) with zero margin clipping for local blogs and community centers.
   - Issue **[#78](https://github.com/bdperkin/ecu-hockey-calendar/issues/78)** adds RSS 2.0 and Atom XML syndication feeds using `feedgen` for media outlets, bloggers, and automated Zapier/Make.com workflows.
   - Issue **[#79](https://github.com/bdperkin/ecu-hockey-calendar/issues/79)** provides printable PDF schedule grid generation via WeasyPrint for coaches, players, and parents needing hard copies for clipboards and refrigerators.

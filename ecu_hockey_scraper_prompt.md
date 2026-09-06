# ECU Ice Hockey Schedule Aggregator & Calendar Service: Production-Grade Engineering Prompt

You are an expert full-stack Python engineer and system architect. Your task is to build a robust, production-grade Python application that automates the collection, cross-referencing, and multi-format publishing of the East Carolina University (ECU) ice hockey team schedule and results.

______________________________________________________________________

## 1. **System Architecture Overview**

1. **Data Ingestion & Cross-Reference Engine (Worker):** Periodically scrapes multiple sources, reconciles discrepancies, detects changes (additions, modifications, deletions), and triggers notifications.
2. **Calendar & Data API (Web App):** A lightweight, hosted web service serving clean endpoints for multiple calendar types, JSON, and CSV formats.
3. **Storage:** A persistent database (e.g., PostgreSQL or SQLite) storing the canonical master schedule, raw source snapshots, and logs.

______________________________________________________________________

## 2. **Core Component Requirements**

### 2.1. **Part 1: Multi-Source Web Crawler & Reconciliation Engine**

- **Target Sources to Parse:**
  - Primary Source of Truth (SOT): `https://www.ecuhockey.com/schedule/upcoming`
  - League Schedule Page: `https://www.acchockey.com/page/show/9602441-east-carolina`
  - Tickets Page: `https://www.ecuhockey.com/tickets`
  - Instagram: `https://www.instagram.com/ecuicehockey/` (Use an official graph API approach or resilient HTML/JSON fallback parsing if possible; handle rate limits gracefully).
  - **Opponent Reverse Check:** Automatically identify opponents from preliminary game data and attempt to query or cross-reference their public schedule/calendar sources when available.
- **Reconciliation Logic:**
  - Implement a fuzzy-matching or deterministic scoring system matching games by date, opponent name, and home/away status.
  - *Conflict Resolution:* If sources disagree (e.g., time changes or game cancellations), prioritize sources based on a configurable hierarchy (e.g., Primary SOT + League Page > Tickets/Instagram > Opponent), and flag high-confidence conflicts for review.
- **Change Detection & Notifications:**
  - Track state changes between sync runs: `CREATED`, `UPDATED`, `DELETED`, and `CONFLICT_DETECTED`.
  - Send rich webhook alerts (support for Discord, Slack, or Telegram) detailing what changed or where data conflicts arose.

### 2.2. **Part 2: Hosted Web Application & Endpoints**

Build the web application using **FastAPI** (preferred for automatic OpenAPI docs and high performance) or **Flask**. It must provide the following public endpoints:

- `/calendar.ics` or standard `.ics` endpoint adhering strictly to **RFC 5545** (fully compatible with Apple Calendar, Google Calendar subscription URLs, and generic calendar apps). Include proper `VEVENT` summaries, descriptions, start/end timestamps, locations, and unique `UID` fields.
- `/api/schedule.json` – Full machine-readable JSON feed of all historical results and upcoming games.
- `/api/schedule.csv` – Downloadable CSV formatted file of the master schedule.
- Webcal support headers so users can easily subscribe via `webcal://<domain>/calendar.ics`.

______________________________________________________________________

## 3. **Hosting Strategy & Provider Analysis**

Include a detailed deployment recommendation section in a `DEPLOYMENT.md` file or architectural overview explaining the best options for hosting both components:

- **Background Worker (Scraper/Cron):** Evaluate options like Render Background Workers, Railway Cron, Fly.io Machines, or AWS Lambda + EventBridge. Give a recommendation considering Instagram scraping limitations (IP blocking/rate limits) and persistent storage needs.
- **Web App & Calendar URL Hosting:** Evaluate Render, Railway, Fly.io, or PythonAnywhere for hosting the FastAPI/Flask application with SSL support (mandatory for web subscription links).

______________________________________________________________________

## 4. **Tech Stack Preferences**

- **Language:** Python 3.11+
- **Framework:** FastAPI
- **Database/ORM:** SQLAlchemy with Alembic for migrations (PostgreSQL for production, SQLite for local dev).
- **Parsing/Scraping:** BeautifulSoup4, httpx/requests, and Playwright (if JavaScript rendering is required for Instagram or dynamic frontend tables).
- **Calendar Generation:** `icalendar` Python library.

Provide the complete file structure, clean modular code, error handling, configuration via environment variables (`.env`), and a comprehensive `README.md` to get the project running locally and deployed to production.

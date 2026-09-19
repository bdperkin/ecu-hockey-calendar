# Ingestion Framework & Multi-Source Crawlers

The `ecu_hockey_calendar.ingestion` package provides a robust, multi-source ingestion pipeline designed to gather East Carolina University Men's Ice Hockey schedules, opponent feeds, ticketing metadata, and social media announcements.

## 1. Architecture Overview

The ingestion framework employs a resilient HTTP client with configurable retries, exponential backoff, response caching, and custom User-Agent headers. Multiple specialized crawlers fetch raw data from primary team feeds, league portals, ticketing sites, opponent calendars, and social announcements.

```text
                    ┌─────────────────────────┐
                    │   ResilientHttpClient   │
                    └────────────┬────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ ECUHockeyCrawler │   │ ACCHockeyCrawler │   │  TicketsCrawler  │
│ (Primary SOT)    │   │ (League Portal)  │   │ (Pricing/Themes) │
└──────────────────┘   └──────────────────┘   └──────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
         ┌───────────────────────┴───────────────────────┐
         ▼                                               ▼
┌──────────────────┐                           ┌──────────────────┐
│ InstagramCrawler │                           │ OpponentCrawler  │
│ (Social Updates) │                           │ (Reverse Verify) │
└──────────────────┘                           └──────────────────┘
```

## 2. Resilient HTTP Client

All crawlers use `ResilientHttpClient` to execute HTTP operations reliably across unpredictable external networks.

Key capabilities include:

- **Configurable Retries & Backoff**: Retries transient HTTP errors (`429`, `500`, `502`, `503`, `504`) with exponential backoff and jitter.
- **Payload Caching**: In-memory and file-backed caching with SHA-256 content hashing to avoid redundant fetches.
- **Request Headers & User-Agent**: Configurable headers to comply with target site conventions.

```python
import asyncio
from ecu_hockey_calendar.ingestion import ResilientHttpClient


async def main() -> None:
    async with ResilientHttpClient(
        timeout=15.0,
        max_retries=3,
        backoff_factor=1.0,
    ) as client:
        html_content, content_hash = await client.fetch_with_hash(
            "https://www.ecuhockey.com/schedule/upcoming"
        )
        print(f"Fetched {len(html_content)} bytes (SHA-256: {content_hash[:8]}...)")


asyncio.run(main())
```

## 3. Primary Team Crawler (ECUHockeyCrawler)

The primary source-of-truth (SOT) crawler targets `ecuhockey.com`. It queries the backend Google Firestore REST endpoint for structured schedule documents, falling back gracefully to HTML scraping if the API is unreachable.

```python
import asyncio
from ecu_hockey_calendar.ingestion import ECUHockeyCrawler, ResilientHttpClient


async def fetch_primary_schedule() -> None:
    async with ResilientHttpClient() as client:
        crawler = ECUHockeyCrawler(client=client)
        records, raw_text, content_hash, content_type = await crawler.crawl(
            prefer_api=True
        )
        for record in records:
            print(
                f"Found match vs {record.opponent_name} on {record.game_date} ({record.game_time})"
            )


asyncio.run(fetch_primary_schedule())
```

## 4. League Crawler (ACCHockeyCrawler)

The Atlantic Collegiate Conference Hockey League (ACCHL) operates a SportsEngine portal at `acchockey.com`. `ACCHockeyCrawler` crawls the conference schedule pages, handles subseason pagination, and extracts official league start times and arena venues.

```python
import asyncio
from ecu_hockey_calendar.ingestion import ACCHockeyCrawler, ResilientHttpClient


async def fetch_league_schedule() -> None:
    async with ResilientHttpClient() as client:
        crawler = ACCHockeyCrawler(client=client)
        records, raw_text, content_hash, content_type = await crawler.crawl()
        print(f"Ingested {len(records)} official ACCHL conference games.")


asyncio.run(fetch_league_schedule())
```

## 5. ACHA Master League Crawler (ACHAHockeyCrawler)

The American Collegiate Hockey Association (ACHA) operates a master schedule portal at `achahockey.org` powered by HockeyTech ModuleKit APIs (`lscluster.hockeytech.com`). `ACHAHockeyCrawler` discovers current, historical, and future seasons dynamically, normalizes team names, converts game start datetimes to UTC, and extracts official scores and rink venues.

```python
import asyncio
from ecu_hockey_calendar.ingestion import ACHAHockeyCrawler, ResilientHttpClient


async def fetch_acha_schedule() -> None:
    async with ResilientHttpClient() as client:
        crawler = ACHAHockeyCrawler(client=client)
        records, raw_text, content_hash, content_type = await crawler.crawl()
        print(f"Ingested {len(records)} official ACHA schedule games.")


asyncio.run(fetch_acha_schedule())
```

## 6. Ticketing & Promotional Crawler (TicketsCrawler)

`TicketsCrawler` scrapes ticket listings from `ecuhockey.com/tickets`. It parses pricing tiers (e.g., student discounts, general admission) and extracts special promotional themes such as *Military Appreciation Night* or *Teddy Bear Toss*.

```python
import asyncio
from ecu_hockey_calendar.ingestion import ResilientHttpClient, TicketsCrawler


async def fetch_ticketing_data() -> None:
    async with ResilientHttpClient() as client:
        crawler = TicketsCrawler(client=client)
        tickets, raw_text, content_hash, content_type = await crawler.crawl()
        for ticket in tickets:
            theme_str = (
                f" [Theme: {ticket.promotional_theme}]"
                if ticket.promotional_theme
                else ""
            )
            print(
                f"Game: vs {ticket.opponent_name}{theme_str} - Tickets: {ticket.ticket_url}"
            )


asyncio.run(fetch_ticketing_data())
```

## 7. Social Media & Announcements (InstagramCrawler)

Game times and cancellations are frequently announced first on social media. `InstagramCrawler` monitors public Instagram posts from `@ecuicehockey`, using fuzzy keyword heuristics to classify announcements into categories:

- `GAME_DAY`: Gameday hype posts confirming puck drop time and venue.
- `SCHEDULE_UPDATE`: Rescheduled dates or modified game times.
- `CANCELLATION`: Postponed or cancelled fixtures.
- `SERIES_PREVIEW`: Upcoming weekend series announcements.

```python
import asyncio
from ecu_hockey_calendar.ingestion import InstagramCrawler, ResilientHttpClient


async def fetch_social_announcements() -> None:
    async with ResilientHttpClient() as client:
        crawler = InstagramCrawler(client=client)
        posts, raw_text, content_hash, content_type = await crawler.crawl()
        for post in posts:
            if post.announcement_type:
                print(
                    f"[{post.announcement_type.value}] {post.date}: {post.caption[:60]}..."
                )


asyncio.run(fetch_social_announcements())
```

## 8. Opponent Schedule Reverse Check (OpponentCrawler)

To ensure schedule integrity, `OpponentCrawler` performs reverse lookups against opponent team sites and league feeds. It cross-checks ECU fixtures against opponent schedules, verifying start times, dates, and venues, and alerting when discrepancies are detected.

```python
import asyncio
from ecu_hockey_calendar.ingestion import OpponentCrawler, ResilientHttpClient


async def verify_against_opponents() -> None:
    async with ResilientHttpClient() as client:
        crawler = OpponentCrawler(client=client)
        results, raw_text, content_hash, content_type = await crawler.crawl()
        for res in results:
            print(f"Opponent verification fixture: {res.opponent_name}")


asyncio.run(verify_against_opponents())
```

## 9. Opponent Schedule Feeds Configuration (YAML Schema)

Opponent schedule endpoints can be configured dynamically using structured YAML files, allowing feeds, venues, aliases, and platforms to be managed without modifying code.

### 9.1. YAML Schema Definition

```yaml
opponents:
  - canonical_name: "UNC Chapel Hill"
    feed_url: "https://tarheelhockey.com/schedule.ics"
    feed_type: "ical"  # 'ical' | 'json' | 'html' | 'sportengine'
    home_venue: "Orange County Sportsplex"
    division: "ACHA M2"
    conference: "ACCHL"
    aliases:
      - "unc"
      - "north carolina"
      - "tar heels"
    website: "https://tarheelhockey.com"
    enabled: true
```

### 9.2. Loading & Serialization

`OpponentDirectory` provides `from_yaml()` and `to_yaml()` methods to load and export endpoint configurations from file paths (`Path` or `str`), file-like streams (`TextIO`), or raw YAML strings:

```python
from pathlib import Path

from ecu_hockey_calendar.ingestion import OpponentDirectory

# Load from file path or Path object
directory = OpponentDirectory.from_yaml(Path("config/opponents.yaml"))

# Query opponent by name or alias
endpoint = directory.get("unc")
if endpoint and endpoint.enabled:
    print(f"Feed URL: {endpoint.feed_url} ({endpoint.feed_type.value})")

# Export directory back to YAML
yaml_output = directory.to_yaml()
```

### 9.3. Bundled Verified Dataset

The library includes a pre-configured, verified dataset of ACCHL and regional collegiate opponents bundled within the package at `ecu_hockey_calendar.data/opponents.yaml`. This resource includes verified official team websites, schedule feed URLs, feed types (`ical`, `html`), and home venues for 14 programs:

- Appalachian State University
- Duke University
- Elon University
- Georgetown University
- High Point University
- James Madison University
- NC State University
- UNC Chapel Hill
- UNC Charlotte
- UNC Wilmington
- University of Richmond
- University of Virginia
- Virginia Tech
- Wake Forest University

To instantiate an `OpponentDirectory` populated with the bundled verified dataset:

```python
from ecu_hockey_calendar.ingestion import get_default_opponent_directory

# Loads package-bundled opponents.yaml automatically via importlib.resources
directory = get_default_opponent_directory()
print(f"Loaded {len(directory)} verified collegiate opponents.")
```

### 9.4. Runtime Resolution Hierarchy

For runtime operations and CLI pipelines, `resolve_opponent_directory()` automatically applies the precedence hierarchy:

1. **Explicit file path**: `resolve_opponent_directory(config_path)`.
2. **Environment variable override**: `OPPONENTS_CONFIG=/path/to/opponents.yaml`.
3. **Bundled default dataset**: Falls back cleanly to `get_default_opponent_directory()`.

```python
from ecu_hockey_calendar.ingestion import resolve_opponent_directory

# Automatically resolves via explicit argument, OPPONENTS_CONFIG envvar, or bundled default
directory = resolve_opponent_directory()
print(f"Active opponent directory contains {len(directory)} entries.")
```

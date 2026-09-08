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

## 5. Ticketing & Promotional Crawler (TicketsCrawler)

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

## 6. Social Media & Announcements (InstagramCrawler)

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

## 7. Opponent Schedule Reverse Check (OpponentCrawler)

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

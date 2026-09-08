# Quickstart

This guide illustrates how to use `ecu-hockey-calendar` across the full schedule management lifecycle: defining fixtures manually, crawling live web sources, reconciling disparate feeds, persisting records to a relational database, and exporting calendar feeds.

## 1. Manual Calendar Creation & Export

To create schedules programmatically and export standard RFC 5545 `.ics` calendars:

```python
from datetime import UTC, datetime
from ecu_hockey_calendar import ECUHockeyCalendar, Team

# Initialize calendar for 2026-2027 season
calendar = ECUHockeyCalendar(season="2026-2027")

# Define an opponent
unc = Team(
    name="UNC Chapel Hill",
    city="Chapel Hill",
    state="NC",
    division="ACHA M2",
    conference="ACCHL",
)

# Schedule a match
game = calendar.add_match(
    opponent=unc,
    start_time=datetime(2026, 10, 15, 19, 0, tzinfo=UTC),
    venue="The Factory Ice House",
    is_home=True,
)

# Export to RFC 5545 iCalendar (.ics)
ics_data = calendar.export_ics()
with open("ecu_schedule.ics", "w", encoding="utf-8") as f:
    f.write(ics_data)

# Export to JSON or CSV
json_data = calendar.export_json()
csv_data = calendar.export_csv()
```

## 2. Ingesting Live Web Feeds

To crawl schedule feeds from primary and conference websites:

```python
import asyncio
from ecu_hockey_calendar.ingestion import (
    ACCHockeyCrawler,
    ECUHockeyCrawler,
    ResilientHttpClient,
)


async def ingest_live_feeds() -> None:
    async with ResilientHttpClient() as client:
        # Ingest primary SOT schedule
        ecu_crawler = ECUHockeyCrawler(client=client)
        ecu_records, _, _, _ = await ecu_crawler.crawl()
        print(f"Scraped {len(ecu_records)} games from ecuhockey.com")

        # Ingest ACCHL league schedule
        acchl_crawler = ACCHockeyCrawler(client=client)
        acchl_records, _, _, _ = await acchl_crawler.crawl()
        print(f"Scraped {len(acchl_records)} games from acchockey.com")


asyncio.run(ingest_live_feeds())
```

## 3. Reconciling Feeds & Resolving Conflicts

When data from multiple sources is gathered, `ReconciliationEngine` clusters duplicate entries, aligns timezones, and resolves field-level discrepancies using configurable priority rules:

```python
from datetime import UTC, datetime
from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.reconciliation import (
    ReconciliationEngine,
    SourceGameRecord,
)
from ecu_hockey_calendar.storage import DataSourceType

# Create records representing the same match from two sources
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

league_rec = SourceGameRecord(
    source_type=DataSourceType.LEAGUE_ACCHL,
    source_code="acchockey",
    opponent_name="UNC",
    start_time=datetime(2026, 10, 15, 23, 0, tzinfo=UTC),
    venue="The Factory",
    is_home=True,
)

# Run reconciliation cycle
engine = ReconciliationEngine()
records = [
    SourceGameRecord.from_game(primary_game, source_type=DataSourceType.PRIMARY_SOT),
    league_rec,
]
cycle = engine.reconcile_games(records)

print(f"Reconciled {cycle.total_games} canonical game(s):")
for game in cycle.reconciled_games:
    print(
        f"- vs {game.opponent_name} at {game.venue} (confidence: {game.confidence_score:.2f})"
    )
```

## 4. Persisting Reconciled Games

Persist canonical records to a relational SQLite or PostgreSQL database:

```python
from ecu_hockey_calendar.storage import (
    GameModel,
    GameStatus,
    TeamModel,
    create_sync_engine,
    get_sync_session,
    init_db,
)

engine = create_sync_engine("sqlite:///ecu_hockey.db")
init_db(engine)

with get_sync_session(engine) as session:
    # Ensure team exists
    opponent = session.query(TeamModel).filter_by(name="UNC Chapel Hill").first()
    if not opponent:
        opponent = TeamModel(name="UNC Chapel Hill", city="Chapel Hill", state="NC")
        session.add(opponent)
        session.flush()

    print(f"Opponent record ID: {opponent.team_id}")
```

## 5. Detecting Changes & Webhook Alerting

Track modifications between sync runs and dispatch alerts:

```python
from datetime import UTC, datetime
from ecu_hockey_calendar.notifications import (
    NotificationChannel,
    NotificationConfig,
    NotificationDispatcher,
    NotificationField,
    NotificationMessage,
    NotificationSeverity,
)
from ecu_hockey_calendar.reconciliation import ChangeDetector

# Detect differences between prior state and new reconciliation
detector = ChangeDetector()
changes = detector.detect_changes(
    previous_games=[],
    current_games=cycle.reconciled_games,
)

# Create notification message for newly detected games
for game in changes.created:
    message = NotificationMessage(
        title=f"New Game Scheduled: ECU vs {game.opponent_name}",
        description=f"Puck drop set for {game.start_time.strftime('%b %d, %Y at %H:%M UTC')}.",
        severity=NotificationSeverity.INFO,
        fields=[
            NotificationField(name="Venue", value=game.venue, inline=True),
            NotificationField(
                name="Designation",
                value="Home" if game.is_home else "Away",
                inline=True,
            ),
        ],
        timestamp=datetime.now(UTC),
    )
```

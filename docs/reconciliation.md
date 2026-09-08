# Schedule Reconciliation & Conflict Resolution

The `ecu_hockey_calendar.reconciliation` package merges game records harvested from multiple upstream sources into a single, authoritative master schedule. It detects discrepancies in dates, start times, venues, and designations, enforces a configurable source priority hierarchy, and flags conflicting data for administrative review.

## 1. Architecture Overview

When disparate web crawlers harvest schedules, data is frequently inconsistent:

- Start times may differ due to timezone ambiguities or tentative schedules.
- Opponent names vary across platforms (e.g., "UNC Tar Heels", "North Carolina", "UNC-Chapel Hill").
- Arena names are abbreviated or aliased (e.g., "The Factory", "The Factory Ice House", "Wake Forest Ice House").
- Venue designations (home vs. away) may conflict.

The reconciliation engine addresses these issues through a multi-stage pipeline:

```text
┌───────────────────────────┐
│ Disparate Ingested Feeds  │ (Primary SOT, League, Tickets, Social, Opponent)
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│    SourceGameRecord       │ (Normalized record representations)
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│   Pairwise Fuzzy Match    │ (Mascot stripping, venue aliases, date tolerance)
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│   Transitive Clustering   │ (Group representations of the same physical match)
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│ Source Priority Hierarchy │ (Tier 1 SOT/League > Tier 2 Tickets/Social > Tier 3 Opponent)
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│      ReconciledGame       │ (Canonical game with provenance and flagged conflicts)
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│      ChangeDetector       │ (Diffs vs previous snapshot: CREATED, UPDATED, DELETED)
└───────────────────────────┘
```

## 2. Source Priority Hierarchy

Precedence is managed by `SourcePriority`, ordering sources into numeric tiers (lower number = higher precedence):

- **Tier 1 (High Authority)**:
  - `PRIMARY_SOT` (`ecuhockey`): Official athletic department schedule.
  - `LEAGUE_ACCHL` (`acchockey`): Official conference schedule.
- **Tier 2 (Secondary/Promotional)**:
  - `TICKETING` (`tickets`): Verified ticketing event listings.
  - `INSTAGRAM` (`instagram`): Real-time social media announcements.
- **Tier 3 (Verification Check)**:
  - `OPPONENT` (`opponent`): Opponent athletic department calendar feeds.

When two sources report conflicting values (e.g., different start times), the value from the higher-priority tier is selected for the canonical record, while a `DetectedConflict` is generated to preserve auditability.

## 3. Fuzzy Matching & Normalization

The `fuzzy_matcher` module determines whether two game records represent the same fixture.

### 3.1. Opponent Matching

Team names are normalized by stripping common university suffixes (`University`, `College`, `Campus`), generic sports terms (`Men's Ice Hockey`, `D2`), and known mascots (`Tar Heels`, `Blue Devils`, `Wolfpack`, `Pirates`):

```python
from ecu_hockey_calendar.reconciliation import (
    compute_opponent_similarity,
    is_opponent_match,
)

score = compute_opponent_similarity(
    "UNC Chapel Hill Ice Hockey", "University of North Carolina"
)
print(f"Similarity: {score:.2f}")  # Score > 0.85

assert is_opponent_match("NC State Icepack", "North Carolina State University")
```

### 3.2. Venue Matching & Aliasing

Ice rinks are frequently entered under informal abbreviations or alternate names. `fuzzy_matcher` maintains a canonical alias dictionary (`VENUE_ALIASES`) mapping aliases like "The Factory" to "The Factory Ice House (Wake Forest, NC)".

```python
from ecu_hockey_calendar.reconciliation import compute_venue_similarity, is_venue_match

assert is_venue_match("The Factory", "The Factory Ice House")
```

## 4. Timezone & Schedule Date Alignment

The `date_aligner` module aligns start times across different time zones into the canonical local timezone (`America/New_York`):

- **Exact Match Window**: Within 15 minutes (default `DEFAULT_EXACT_TOLERANCE_MINUTES`).
- **Near Match Window**: Within 120 minutes (default `DEFAULT_NEAR_TOLERANCE_MINUTES`).
- **TBD Handling**: Games with unspecified or tentative puck drop times match against timed games if scheduled on the same calendar day.

```python
from datetime import datetime, UTC
from ecu_hockey_calendar.reconciliation import align_game_datetimes

# Compare UTC schedule vs local time entry
t1 = datetime(2026, 10, 15, 23, 0, tzinfo=UTC)  # 7:00 PM EDT
t2 = datetime(2026, 10, 15, 23, 15, tzinfo=UTC)  # 7:15 PM EDT

result = align_game_datetimes(t1, t2)
print(f"Aligned: {result.aligned}, Date distance: {result.date_difference_days} days")
```

## 5. End-to-End Reconciliation Example

The `ReconciliationEngine` clusters all incoming records, resolves fields, and produces canonical `ReconciledGame` entities:

```python
from datetime import datetime, UTC
from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.reconciliation import (
    ReconciliationEngine,
    SourceGameRecord,
)
from ecu_hockey_calendar.storage import DataSourceType

# Primary SOT game
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

# League schedule with slight variation in venue text
league_rec = SourceGameRecord(
    source_type=DataSourceType.LEAGUE_ACCHL,
    source_code="acchockey",
    opponent_name="North Carolina",
    start_time=datetime(2026, 10, 15, 23, 0, tzinfo=UTC),
    venue="The Factory",
    is_home=True,
)

# Reconcile records
engine = ReconciliationEngine()
records = [
    SourceGameRecord.from_game(primary_game, source_type=DataSourceType.PRIMARY_SOT),
    league_rec,
]

cycle_result = engine.reconcile_games(records)

print(f"Reconciled {cycle_result.total_games} unique games.")
for game in cycle_result.reconciled_games:
    print(f"Canonical Game: vs {game.opponent_name} at {game.venue}")
    print(f"Contributing sources: {game.contributing_sources}")
    print(f"Requires review: {game.requires_admin_review}")
```

## 6. Change State Detection

The `ChangeDetector` compares newly reconciled games against the previous stored snapshot, identifying transitions and field diffs:

- `CREATED`: Newly scheduled game.
- `UPDATED`: Start time, venue, or status changes (includes before/after diff).
- `DELETED`: Previously scheduled game removed from all upstream feeds.
- `CONFLICT_DETECTED`: High-confidence discrepancy flagged.

```python
from ecu_hockey_calendar.reconciliation import ChangeDetector

detector = ChangeDetector()
changes = detector.detect_changes(
    previous_games=[],
    current_games=cycle_result.reconciled_games,
)

for change in changes.created:
    print(f"New fixture scheduled: {change.game_id} vs {change.opponent_name}")
```

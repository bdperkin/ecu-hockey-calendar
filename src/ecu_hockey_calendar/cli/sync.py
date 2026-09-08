"""Implementation of the 'ecu-hockey sync' CLI command.

Synchronizes schedule fixtures from upstream crawlers, reconciles conflicts,
detects state transitions, and persists updates to relational storage.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import click
from sqlalchemy import select

from ecu_hockey_calendar.cli.console import (
    create_table,
    format_status_badge,
    get_console,
    print_banner,
    print_error,
    print_success,
    print_warning,
)
from ecu_hockey_calendar.ingestion.acchockey_crawler import ACCHockeyCrawler
from ecu_hockey_calendar.ingestion.ecuhockey_crawler import ECUHockeyCrawler
from ecu_hockey_calendar.notifications.dispatcher import NotificationDispatcher
from ecu_hockey_calendar.reconciliation.change_detector import ChangeDetector
from ecu_hockey_calendar.reconciliation.engine import ReconciliationEngine
from ecu_hockey_calendar.reconciliation.models import (
    DataSourceType,
    DetectedConflict,
    ReconciledGame,
    SourceGameRecord,
)
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.engine import (
    create_sync_engine,
    get_sync_database_url,
    get_sync_session,
)
from ecu_hockey_calendar.storage.models import (
    DataSourceModel,
    GameModel,
    SyncStatus,
    TeamModel,
)
from ecu_hockey_calendar.storage.service import record_change_cycle

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

    from ecu_hockey_calendar.ingestion.html_parser import ParsedGameRecord
    from ecu_hockey_calendar.models import GameResult
    from ecu_hockey_calendar.reconciliation.models import ChangeDetectionCycleResult


def _convert_parsed_to_source_record(
    record: ParsedGameRecord,
    source_type: DataSourceType,
    source_code: str,
) -> SourceGameRecord:
    """Convert an ingested ParsedGameRecord into a reconciliation SourceGameRecord."""
    outcome: GameResult | None = None
    if record.home_score is not None and record.away_score is not None:
        outcome = record.calculate_result()

    return SourceGameRecord(
        source_type=source_type,
        source_code=source_code,
        opponent_name=record.opponent_name,
        start_time=record.start_time,
        game_id=record.game_id,
        is_home=record.is_home,
        venue=record.venue,
        status=record.status,
        result=outcome,
        home_score=record.home_score,
        away_score=record.away_score,
        confidence_score=1.0,
        metadata=dict(record.metadata) if record.metadata else {},
    )


async def _run_ecuhockey_crawler() -> tuple[list[SourceGameRecord], str, float]:
    """Execute the primary ECU Hockey crawler.

    Returns:
        Tuple of (source_records, status_string, duration_seconds).
    """
    t0 = datetime.now(UTC)
    crawler = ECUHockeyCrawler()
    records, _, _, _ = await crawler.crawl()
    dur = (datetime.now(UTC) - t0).total_seconds()
    src_records = [
        _convert_parsed_to_source_record(
            r,
            DataSourceType.PRIMARY_SOT,
            "ecuhockey",
        )
        for r in records
    ]
    return src_records, "SUCCESS", dur


async def _run_acchockey_crawler() -> tuple[list[SourceGameRecord], str, float]:
    """Execute the ACC Hockey league schedule crawler.

    Returns:
        Tuple of (source_records, status_string, duration_seconds).
    """
    t0 = datetime.now(UTC)
    crawler = ACCHockeyCrawler()
    records, _, _, _ = await crawler.crawl()
    dur = (datetime.now(UTC) - t0).total_seconds()
    src_records = [
        _convert_parsed_to_source_record(
            r,
            DataSourceType.LEAGUE,
            "acchockey",
        )
        for r in records
    ]
    return src_records, "SUCCESS", dur


def _load_baseline_games_from_db(
    session: Session,
    season: str | None = None,
) -> list[GameModel]:
    """Retrieve existing game models from database."""
    stmt = select(GameModel)
    if season:
        stmt = stmt.where(GameModel.season == season)

    return list(session.scalars(stmt).all())


def _get_or_create_team(
    session: Session,
    name: str,
    city: str = "Unknown",
    state: str = "NC",
) -> TeamModel:
    """Find or create team record by normalized name."""
    team = session.scalar(select(TeamModel).where(TeamModel.name == name))
    if not team:
        team = TeamModel(name=name, city=city, state=state)
        session.add(team)
        session.flush()

    return team


def _upsert_reconciled_game(
    session: Session,
    rec_game: ReconciledGame,
    ecu_team_id: int,
) -> None:
    """Upsert a single reconciled game model."""
    opp_team = _get_or_create_team(session, rec_game.opponent_name)
    home_id = ecu_team_id if rec_game.is_home else opp_team.id
    away_id = opp_team.id if rec_game.is_home else ecu_team_id

    game = session.scalar(
        select(GameModel).where(GameModel.game_id == rec_game.canonical_game_id),
    )
    res_val = rec_game.result.value if rec_game.result else None
    if not game:
        game = GameModel(
            game_id=rec_game.canonical_game_id,
            home_team_id=home_id,
            away_team_id=away_id,
            start_time=rec_game.start_time,
            venue=rec_game.venue,
            status=rec_game.status.value,
            home_score=rec_game.home_score,
            away_score=rec_game.away_score,
            result=res_val,
        )
        session.add(game)
    else:
        game.home_team_id = home_id
        game.away_team_id = away_id
        game.start_time = rec_game.start_time
        game.venue = rec_game.venue
        game.status = rec_game.status.value
        game.home_score = rec_game.home_score
        game.away_score = rec_game.away_score
        game.result = res_val

    session.flush()


def _ensure_data_source(
    session: Session,
    source_code: str,
    source_name: str,
    source_type: DataSourceType,
    source_url: str = "",
) -> DataSourceModel:
    """Ensure DataSourceModel row exists for tracking."""
    source = session.scalar(
        select(DataSourceModel).where(DataSourceModel.source_code == source_code),
    )
    if not source_url:
        source_url = (
            "https://www.ecuhockey.com"
            if source_code == "ecuhockey"
            else "https://www.acchockey.com"
        )

    if not source:
        source = DataSourceModel(
            source_code=source_code,
            name=source_name,
            source_url=source_url,
            source_type=source_type.value,
            priority_order=1,
            is_active=True,
            last_scraped_at=datetime.now(UTC),
        )
        session.add(source)
        session.flush()
    else:
        source.last_scraped_at = datetime.now(UTC)
        session.flush()

    return source


async def _execute_crawlers(
    source_filter: str,
) -> tuple[list[SourceGameRecord], list[dict[str, Any]]]:
    """Execute active crawlers and collect telemetry."""
    all_source_records: list[SourceGameRecord] = []
    crawl_telemetry: list[dict[str, Any]] = []

    if source_filter in ("all", "ecuhockey"):
        try:
            records, status_val, dur = await _run_ecuhockey_crawler()
            all_source_records.extend(records)
            crawl_telemetry.append(
                {
                    "source": "ecuhockey",
                    "name": "ECU Hockey Official",
                    "records": len(records),
                    "status": status_val,
                    "duration": dur,
                },
            )
        except Exception as err:  # noqa: BLE001 # pylint: disable=broad-exception-caught
            crawl_telemetry.append(
                {
                    "source": "ecuhockey",
                    "name": "ECU Hockey Official",
                    "records": 0,
                    "status": f"FAILED: {err}",
                    "duration": 0.0,
                },
            )

    if source_filter in ("all", "acchockey"):
        try:
            records, status_val, dur = await _run_acchockey_crawler()
            all_source_records.extend(records)
            crawl_telemetry.append(
                {
                    "source": "acchockey",
                    "name": "ACC Hockey League",
                    "records": len(records),
                    "status": status_val,
                    "duration": dur,
                },
            )
        except Exception as err:  # noqa: BLE001 # pylint: disable=broad-exception-caught
            crawl_telemetry.append(
                {
                    "source": "acchockey",
                    "name": "ACC Hockey League",
                    "records": 0,
                    "status": f"FAILED: {err}",
                    "duration": 0.0,
                },
            )

    return all_source_records, crawl_telemetry


def _persist_sync_results(
    session: Session,
    reconciled_games: Sequence[ReconciledGame],
    crawl_telemetry: Sequence[dict[str, Any]],
    change_result: ChangeDetectionCycleResult,
) -> None:
    """Persist reconciled fixtures, active data sources, and audit record."""
    ecu_team = _get_or_create_team(
        session,
        "East Carolina University",
        "Greenville",
        "NC",
    )
    for rg in reconciled_games:
        _upsert_reconciled_game(session, rg, ecu_team.id)

    for telemetry in crawl_telemetry:
        st = (
            DataSourceType.PRIMARY_SOT
            if telemetry["source"] == "ecuhockey"
            else DataSourceType.LEAGUE
        )
        _ensure_data_source(session, telemetry["source"], telemetry["name"], st)

    record_change_cycle(
        session,
        change_result,
        sync_status=SyncStatus.SUCCESS,
    )


def _execute_sync_pipeline(  # pylint: disable=too-many-locals
    *,
    engine: Engine,
    source_filter: str,
    dry_run: bool,
    notify: bool,
    season: str | None,
) -> tuple[list[dict[str, Any]], ChangeDetectionCycleResult, list[DetectedConflict]]:
    """Synchronous core pipeline orchestrating crawl, reconciliation, and storage."""
    Base.metadata.create_all(engine)

    # 1. Run crawlers
    all_source_records, crawl_telemetry = asyncio.run(_execute_crawlers(source_filter))

    # 2. Reconcile records
    rec_engine = ReconciliationEngine()
    reconciled_cycle = rec_engine.reconcile_games(all_source_records)

    all_conflicts: list[DetectedConflict] = []
    for rg in reconciled_cycle.reconciled_games:
        all_conflicts.extend(rg.conflicts)

    # 3. Detect changes against DB baseline
    with get_sync_session(engine) as session:
        baseline_games = _load_baseline_games_from_db(session, season)
        detector = ChangeDetector()
        change_result = detector.detect_changes(
            baseline_games,
            reconciled_cycle.reconciled_games,
            cycle_id=reconciled_cycle.cycle_id,
        )

        if not dry_run:
            _persist_sync_results(
                session,
                reconciled_cycle.reconciled_games,
                crawl_telemetry,
                change_result,
            )

    # 4. Webhook notifications
    if notify and not dry_run:
        dispatcher = NotificationDispatcher()
        dispatcher.dispatch_cycle(change_result)

    return crawl_telemetry, change_result, all_conflicts


@click.command("sync")
@click.option(
    "--source",
    "-s",
    "source_code",
    type=click.Choice(["all", "ecuhockey", "acchockey"], case_sensitive=False),
    default="all",
    show_default=True,
    help="Restrict synchronization to a specific data source.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help=(
        "Perform crawl, reconciliation, and diffing without committing to the database."
    ),
)
@click.option(
    "--notify/--no-notify",
    default=False,
    help="Dispatch multi-channel webhook notifications for detected schedule changes.",
)
@click.option(
    "--db-url",
    envvar="DATABASE_URL",
    default=None,
    help="Database connection URL override (defaults to local SQLite or DATABASE_URL).",
)
@click.option(
    "--season",
    default=None,
    help="Optional season filter (e.g., '2026-2027').",
)
def sync_command(  # pylint: disable=too-many-locals
    *,
    source_code: str,
    dry_run: bool,
    notify: bool,
    db_url: str | None,
    season: str | None,
) -> None:
    """Ingest upstream schedules, reconcile conflicts, and detect changes."""
    console = get_console()
    print_banner("SCHEDULE SYNCHRONIZATION & RECONCILIATION")

    db_url_resolved = get_sync_database_url(db_url)
    engine = create_sync_engine(db_url_resolved)

    mode_str = (
        "[bold yellow]DRY RUN[/bold yellow]"
        if dry_run
        else "[bold green]LIVE[/bold green]"
    )
    console.print(
        f"Mode: {mode_str} | "
        f"Source: [bold cyan]{source_code}[/bold cyan] | "
        f"Target DB: [dim]{db_url_resolved}[/dim]\n",
    )

    with console.status(
        "[bold #fec923]Crawling sources and reconciling fixtures...[/bold #fec923]",
        spinner="dots",
    ):
        try:
            telemetry, change_result, conflicts = _execute_sync_pipeline(
                engine=engine,
                source_filter=source_code.lower(),
                dry_run=dry_run,
                notify=notify,
                season=season,
            )
        except Exception as exc:
            print_error(f"Synchronization pipeline encountered a fatal error: {exc}")
            raise click.ClickException(str(exc)) from exc

    # Render Sources Table
    sources_table = create_table(
        "Ingestion Sources Telemetry",
        [
            ("Source", "bold cyan"),
            ("Records Extracted", "bold"),
            ("Status", "bold"),
            ("Elapsed Time", "dim"),
        ],
    )
    for t in telemetry:
        sources_table.add_row(
            t["name"],
            str(t["records"]),
            format_status_badge(t["status"]),
            f"{t['duration']:.2f}s",
        )

    console.print(sources_table)
    console.print()

    # Render Reconciliation & Changes Summary Table
    summary_table = create_table(
        "Reconciliation & Change Detection Summary",
        [
            ("Metric", "bold #fec923"),
            ("Count", "bold"),
        ],
    )
    summary_table.add_row("Total Games Processed", str(len(change_result.changes)))
    summary_table.add_row(
        "New Games Created",
        f"[green]{len(change_result.created_games)}[/green]",
    )
    summary_table.add_row(
        "Games Updated",
        f"[yellow]{len(change_result.updated_games)}[/yellow]",
    )
    summary_table.add_row(
        "Games Cancelled / Deleted",
        f"[red]{len(change_result.deleted_games)}[/red]",
    )
    summary_table.add_row(
        "Active Discrepancies / Conflicts",
        f"[bold red]{len(conflicts)}[/bold red]",
    )
    console.print(summary_table)
    console.print()

    if dry_run:
        print_warning(
            "Dry run completed: Changes detected above were NOT committed "
            "to the database.",
        )
    else:
        print_success(
            "Schedule synchronization completed successfully "
            f"(Cycle: {change_result.cycle_id}).",
        )

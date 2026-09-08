"""Implementation of the 'ecu-hockey status' CLI command.

Displays operational health, database connectivity, registered scraper statuses,
synchronization metrics, and current schedule overview.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import click
from rich.panel import Panel
from rich.text import Text
from sqlalchemy import func, select

from ecu_hockey_calendar.api.routes.health import DEFAULT_SCRAPERS
from ecu_hockey_calendar.calendar import ECUHockeyCalendar
from ecu_hockey_calendar.cli.console import (
    create_table,
    format_status_badge,
    get_console,
    print_banner,
    print_error,
)
from ecu_hockey_calendar.models import GameResult
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.engine import (
    create_sync_engine,
    get_sync_database_url,
    get_sync_session,
)
from ecu_hockey_calendar.storage.models import (
    DataSourceModel,
    GameModel,
    SyncAuditModel,
    SyncStatus,
)
from ecu_hockey_calendar.storage.service import get_sync_audit_history

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rich.table import Table
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

    from ecu_hockey_calendar.models import Game


def _query_sync_telemetry(session: Session) -> dict[str, Any]:
    """Retrieve telemetry metrics for the latest sync cycle."""
    audits = get_sync_audit_history(session, limit=1)
    latest_audit = audits[0] if audits else None

    count_val = session.scalar(select(func.count(SyncAuditModel.id)))  # pylint: disable=not-callable
    total_count = int(count_val) if count_val is not None else 0

    stmt_last_success = (
        select(SyncAuditModel.completed_at)
        .where(SyncAuditModel.status.in_([SyncStatus.SUCCESS.value, "COMPLETED"]))
        .order_by(SyncAuditModel.started_at.desc())
        .limit(1)
    )
    last_success_dt = session.scalar(stmt_last_success)

    return {
        "latest_audit": latest_audit,
        "total_cycles": total_count,
        "last_success_at": last_success_dt,
    }


def _query_sources(session: Session) -> list[dict[str, Any]]:
    """Retrieve registered data source statuses."""
    stmt = select(DataSourceModel).order_by(DataSourceModel.priority_order)
    sources = session.scalars(stmt).all()
    if not sources:
        return list(DEFAULT_SCRAPERS)

    return [
        {
            "source_code": s.source_code,
            "name": s.name,
            "source_type": s.source_type,
            "is_active": s.is_active,
            "last_scraped_at": s.last_scraped_at,
        }
        for s in sources
    ]


def _query_schedule_games(
    session: Session,
    season: str | None = None,
) -> list[Game]:
    """Retrieve schedule games from database.

    Falls back to default calendar fixtures if the database table is empty.
    """
    stmt = select(GameModel)
    if season:
        stmt = stmt.where(GameModel.season == season)

    db_games = session.scalars(stmt).all()
    if db_games:
        return [g.to_domain() for g in db_games]

    default_cal = ECUHockeyCalendar()
    return list(default_cal.schedule.games)


RESULT_CATEGORY_MAP: dict[GameResult | None, str] = {
    GameResult.WIN: "wins",
    GameResult.LOSS: "losses",
    GameResult.OVERTIME_LOSS: "losses",
    GameResult.TIE: "ties",
    GameResult.CANCELLED: "cancelled",
    GameResult.POSTPONED: "postponed",
}


def _find_next_upcoming_game(games: list[Game], now_utc: datetime) -> Game | None:
    """Identify the nearest chronological upcoming fixture."""
    upcoming = [
        g
        for g in games
        if g.start_time.astimezone(UTC) >= now_utc
        and g.result not in (GameResult.CANCELLED, GameResult.POSTPONED)
    ]
    upcoming.sort(key=lambda g: g.start_time)
    return upcoming[0] if upcoming else None


def _compute_schedule_stats(games: list[Game]) -> dict[str, Any]:
    """Compute summary statistics across games collection."""
    now_utc = datetime.now(UTC)
    counts: dict[str, int] = {
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "scheduled": 0,
        "cancelled": 0,
        "postponed": 0,
    }

    for g in games:
        category = RESULT_CATEGORY_MAP.get(g.result, "scheduled")
        counts[category] += 1

    return {
        "total": len(games),
        "wins": counts["wins"],
        "losses": counts["losses"],
        "ties": counts["ties"],
        "scheduled": counts["scheduled"],
        "cancelled": counts["cancelled"],
        "postponed": counts["postponed"],
        "next_game": _find_next_upcoming_game(games, now_utc),
    }


def _render_system_panel(telemetry: dict[str, Any], db_url: str) -> Panel:
    """Render overall system health and sync cycle summary panel."""
    audit: SyncAuditModel | None = telemetry["latest_audit"]
    panel_text = Text()
    panel_text.append("Database URL: ", style="bold")
    panel_text.append(f"{db_url}\n", style="dim")
    panel_text.append("Total Sync Cycles Recorded: ", style="bold")
    panel_text.append(f"{telemetry['total_cycles']}\n", style="cyan")

    last_succ = telemetry.get("last_success_at")
    last_succ_str = last_succ.strftime("%Y-%m-%d %H:%M:%S UTC") if last_succ else "None"
    panel_text.append("Last Successful Sync: ", style="bold")
    panel_text.append(f"{last_succ_str}\n", style="green")

    if audit is not None:
        panel_text.append("Latest Cycle ID: ", style="bold")
        panel_text.append(f"{audit.sync_cycle_id} (", style="bold")
        panel_text.append(format_status_badge(audit.status))
        panel_text.append(")\n")
        panel_text.append("Started At: ", style="bold")
        started_str = (
            audit.started_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            if audit.started_at
            else "Unknown"
        )
        panel_text.append(
            f"{started_str} | Duration: {audit.duration_ms or 0} ms\n",
            style="dim",
        )
        panel_text.append(
            f"Games: +{audit.games_created} created, ~{audit.games_updated} updated, "
            f"-{audit.games_deleted} deleted, !{audit.conflicts_detected} conflicts",
            style="bold #fec923",
        )
    else:
        panel_text.append("Latest Sync Cycle: ", style="bold")
        panel_text.append("Never Run", style="yellow")

    return Panel(
        panel_text,
        title="[bold #fec923]System & Synchronization Status[/bold #fec923]",
        border_style="#592a8a",
    )


def _render_next_game_panel(next_game: Game | None) -> Panel:
    """Render upcoming match spotlight panel."""
    panel_text = Text()
    if next_game is not None:
        is_home = next_game.is_home_game("East Carolina University")
        opp = next_game.opponent_of("East Carolina University")
        dt_str = next_game.start_time.strftime("%A, %b %d, %Y at %I:%M %p %Z")
        designation = "HOME MATCH" if is_home else "AWAY FIXTURE"
        desig_style = "bold green" if is_home else "bold yellow"

        panel_text.append(f"Match: ECU Hockey vs {opp.name}\n", style="bold #fec923")
        panel_text.append(f"Date: {dt_str}\n", style="bold white")
        panel_text.append(
            f"Designation: {designation} ({next_game.venue})\n",
            style=desig_style,
        )
        if is_home:
            panel_text.append(
                "Tickets: https://www.ecuhockey.com/tickets",
                style="bold cyan",
            )
    else:
        panel_text.append(
            "No future games currently scheduled for this season.",
            style="dim",
        )

    return Panel(
        panel_text,
        title="[bold #fec923]Next Upcoming Fixture[/bold #fec923]",
        border_style="#592a8a",
    )


def _render_sources_table(sources: Sequence[dict[str, Any]]) -> Table:
    """Construct Rich Table of registered scrapers and their active states."""
    table = create_table(
        "Registered Data Sources",
        [
            ("Source Code", "bold cyan"),
            ("Name", "bold"),
            ("Type", "dim"),
            ("Active", "bold"),
            ("Last Crawled", "dim"),
        ],
    )
    for s in sources:
        last_dt = s.get("last_scraped_at")
        last_str = (
            last_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            if isinstance(last_dt, datetime)
            else (str(last_dt) if last_dt else "Never")
        )
        active_str = (
            "[bold green]Active[/bold green]"
            if s.get("is_active", True)
            else "[bold red]Inactive[/bold red]"
        )
        table.add_row(
            s.get("source_code", "unknown"),
            s.get("name", "Unknown Source"),
            s.get("source_type", "unknown"),
            active_str,
            last_str,
        )

    return table


def _render_schedule_table(stats: dict[str, Any], season: str | None) -> Table:
    """Construct Rich Table summarizing schedule counts and team record."""
    title = f"Schedule Overview ({season})" if season else "Schedule Overview"
    table = create_table(
        title,
        [
            ("Metric", "bold #fec923"),
            ("Value", "bold"),
        ],
    )
    table.add_row("Total Fixtures", str(stats["total"]))
    table.add_row("Upcoming Scheduled Games", f"[blue]{stats['scheduled']}[/blue]")
    rec_str = (
        f"[green]{stats['wins']}[/green]W - "
        f"[red]{stats['losses']}[/red]L - "
        f"[yellow]{stats['ties']}[/yellow]T"
    )
    table.add_row("Record (W-L-T)", rec_str)
    table.add_row("Cancelled Games", f"[red]{stats['cancelled']}[/red]")
    table.add_row("Postponed Games", f"[yellow]{stats['postponed']}[/yellow]")
    return table


@click.command("status")
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
def status_command(
    *,
    db_url: str | None,
    season: str | None,
) -> None:
    """Display system status, sync telemetry, and schedule summary."""
    console = get_console()
    print_banner("SYSTEM STATUS & SCHEDULE DIAGNOSTICS")

    db_url_resolved = get_sync_database_url(db_url)
    engine: Engine = create_sync_engine(db_url_resolved)
    try:
        Base.metadata.create_all(engine)
        with get_sync_session(engine) as session:
            telemetry = _query_sync_telemetry(session)
            sources = _query_sources(session)
            games = _query_schedule_games(session, season)
    except Exception as exc:
        print_error(f"Failed to query status from database: {exc}")
        raise click.ClickException(str(exc)) from exc

    stats = _compute_schedule_stats(games)

    console.print(_render_system_panel(telemetry, db_url_resolved))
    console.print()
    console.print(_render_sources_table(sources))
    console.print()
    console.print(_render_schedule_table(stats, season))
    console.print()
    console.print(_render_next_game_panel(stats["next_game"]))

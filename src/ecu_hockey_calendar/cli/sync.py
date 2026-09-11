"""Implementation of the 'ecu-hockey sync' CLI command.

Synchronizes schedule fixtures from upstream crawlers, reconciles conflicts,
detects state transitions, and persists updates to relational storage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

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
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.engine import (
    create_sync_engine,
    get_sync_database_url,
    get_sync_session,
)
from ecu_hockey_calendar.sync_service import (
    _convert_parsed_to_source_record,
    _ensure_data_source,
    _execute_crawlers,
    _load_baseline_games_from_db,
    execute_sync_pipeline,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from ecu_hockey_calendar.reconciliation.models import (
        ChangeDetectionCycleResult,
        DetectedConflict,
    )

__all__ = [
    "ACCHockeyCrawler",
    "Base",
    "ECUHockeyCrawler",
    "NotificationDispatcher",
    "_convert_parsed_to_source_record",
    "_ensure_data_source",
    "_execute_crawlers",
    "_execute_sync_pipeline",
    "_load_baseline_games_from_db",
    "create_sync_engine",
    "execute_sync_pipeline",
    "get_sync_database_url",
    "get_sync_session",
    "sync_command",
]


def _execute_sync_pipeline(
    *,
    engine: Engine,
    source_filter: str,
    dry_run: bool,
    notify: bool,
    notify_individual: bool = False,
    season: str | None,
) -> tuple[list[dict[str, Any]], ChangeDetectionCycleResult, list[DetectedConflict]]:
    """Synchronous core pipeline orchestrating crawl, reconciliation, and storage."""
    return execute_sync_pipeline(
        engine=engine,
        source_filter=source_filter,
        dry_run=dry_run,
        notify=notify,
        notify_individual=notify_individual,
        season=season,
        crawler_fn=_execute_crawlers,
        baseline_loader_fn=_load_baseline_games_from_db,
        session_factory=get_sync_session,
        dispatcher_cls=NotificationDispatcher,
    )


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
    "--notify-individual",
    is_flag=True,
    default=False,
    help="Dispatch individual alert messages for each detected schedule change.",
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
    notify_individual: bool = False,
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
                notify_individual=notify_individual,
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

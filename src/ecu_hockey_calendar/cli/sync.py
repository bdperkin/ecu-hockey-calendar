"""Implementation of the 'ecu-hockey sync' CLI command.

Synchronizes schedule fixtures from upstream crawlers, reconciles conflicts,
detects state transitions, and persists updates to relational storage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

from ecu_hockey_calendar.api.client import (
    RemoteApiAuthError,
    RemoteApiClient,
    RemoteApiError,
)
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
    "_execute_remote_sync",
    "_execute_sync_pipeline",
    "_extract_ctx_str",
    "_handle_remote_sync_result",
    "_load_baseline_games_from_db",
    "_normalize_source_filter",
    "_render_sync_results",
    "_resolve_remote_credentials",
    "create_sync_engine",
    "execute_sync_pipeline",
    "get_sync_database_url",
    "get_sync_session",
    "sync_command",
]


def _normalize_source_filter(source_code: str) -> str | None:
    """Convert CLI source code to crawler filter parameter."""
    norm = source_code.lower()
    return None if norm == "all" else norm


def _handle_remote_sync_result(result: dict[str, Any]) -> None:
    """Render warning or success message for remote sync trigger result."""
    if result.get("status") == "unsupported":
        warn_msg = result.get("message", "Synchronization trigger not supported.")
        print_warning(warn_msg)
        return

    status_msg = result.get("message") or result.get("status") or "Triggered"
    print_success(f"Remote synchronization dispatched successfully: {status_msg}")


def _execute_remote_sync(
    *,
    api_url: str,
    token: str | None,
    source_code: str,
) -> None:
    """Dispatch synchronization trigger request to remote HTTP API."""
    console = get_console()
    console.print(
        f"Target: [bold cyan]Remote API ({api_url})[/bold cyan]\n",
    )
    client = RemoteApiClient(api_url, token=token)
    status_spinner_msg = (
        "[bold #fec923]Dispatching remote synchronization request...[/bold #fec923]"
    )
    source_filter = _normalize_source_filter(source_code)
    try:
        with console.status(
            status_spinner_msg,
            spinner="dots",
        ):
            result = client.trigger_sync(source=source_filter)
    except RemoteApiAuthError as exc:
        auth_msg = (
            f"Authentication required: {exc}\n"
            "Provide --token <TOKEN> or set ECU_HOCKEY_ADMIN_TOKEN."
        )
        print_error(auth_msg)
        err_msg = "Authentication failed for remote sync trigger."
        raise click.ClickException(err_msg) from exc
    except RemoteApiError as exc:
        print_error(f"Failed to trigger synchronization on remote API: {exc}")
        raise click.ClickException(str(exc)) from exc

    _handle_remote_sync_result(result)


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


def _extract_ctx_str(obj: object, key: str) -> str | None:
    """Extract string value from context dictionary."""
    if isinstance(obj, dict):
        val = obj.get(key)
        if val is not None:
            return str(val)

    return None


def _resolve_remote_credentials(
    ctx: click.Context | None,
    api_url: str | None,
    token: str | None,
) -> tuple[str | None, str | None]:
    """Extract and resolve remote API URL and admin token from CLI context."""
    obj = ctx.obj if ctx else None
    url = api_url if api_url is not None else _extract_ctx_str(obj, "api_url")
    tok = token if token is not None else _extract_ctx_str(obj, "token")
    return url, tok


def _render_sync_results(
    telemetry: list[dict[str, Any]],
    change_result: ChangeDetectionCycleResult,
    conflicts: list[DetectedConflict],
    *,
    dry_run: bool,
) -> None:
    """Render Rich tables displaying crawler telemetry and reconciliation summary."""
    console = get_console()
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
@click.option(
    "--api-url",
    envvar="ECU_HOCKEY_API_URL",
    default=None,
    help="Remote ECU Hockey API base URL (e.g., 'https://ecu-hockey-api.onrender.com').",
)
@click.option(
    "--token",
    envvar="ECU_HOCKEY_ADMIN_TOKEN",
    default=None,
    help="Administrative authentication Bearer token for protected remote endpoints.",
)
@click.pass_context
def sync_command(  # noqa: PLR0913 # pylint: disable=too-many-arguments,too-many-locals
    ctx: click.Context | None,
    *,
    source_code: str,
    dry_run: bool,
    notify: bool,
    notify_individual: bool = False,
    db_url: str | None,
    season: str | None,
    api_url: str | None = None,
    token: str | None = None,
) -> None:
    """Ingest upstream schedules, reconcile conflicts, and detect changes."""
    console = get_console()
    print_banner("SCHEDULE SYNCHRONIZATION & RECONCILIATION")

    api_url, token = _resolve_remote_credentials(ctx, api_url, token)
    if api_url:
        _execute_remote_sync(
            api_url=api_url,
            token=token,
            source_code=source_code,
        )
        return

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

    _render_sync_results(telemetry, change_result, conflicts, dry_run=dry_run)

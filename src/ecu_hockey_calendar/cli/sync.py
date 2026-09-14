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
    _parse_audit_record,
    _parse_optional_datetime,
)
from ecu_hockey_calendar.api.routes.sync import _extract_db_sync_telemetry
from ecu_hockey_calendar.cli.console import (
    create_table,
    format_status_badge,
    get_console,
    print_banner,
    print_error,
    print_success,
    print_warning,
)
from ecu_hockey_calendar.cli.status import (
    _query_sources,
    _query_sync_telemetry,
    _render_sources_table,
    _render_system_panel,
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
    "_fetch_remote_sync_status",
    "_handle_remote_sync_result",
    "_load_baseline_games_from_db",
    "_normalize_source_filter",
    "_populate_ctx_params",
    "_render_local_sync_status",
    "_render_remote_sync_status",
    "_render_sync_results",
    "_resolve_remote_credentials",
    "_run_sync_status",
    "_run_sync_trigger",
    "create_sync_engine",
    "execute_sync_pipeline",
    "get_sync_database_url",
    "get_sync_session",
    "sync_command",
    "sync_status_command",
    "sync_trigger_command",
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


def _populate_ctx_params(
    ctx: click.Context | None,
    api_url: str | None,
    token: str | None,
    db_url: str | None,
) -> None:
    """Store group-level connection parameters in Click context object."""
    if ctx is None:
        return

    ctx.ensure_object(dict)
    if api_url is not None:
        ctx.obj["api_url"] = api_url

    if token is not None:
        ctx.obj["token"] = token

    if db_url is not None:
        ctx.obj["db_url"] = db_url


def _run_sync_trigger(  # noqa: PLR0913 # pylint: disable=too-many-arguments,too-many-locals
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
    """Execute schedule crawl, reconciliation, and diffing pipeline."""
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


def _fetch_remote_sync_status(api_url: str, token: str | None) -> dict[str, Any]:
    """Query synchronization status payload from remote API."""
    client = RemoteApiClient(api_url, token=token)
    try:
        return client.get_sync_status()
    except RemoteApiError as exc:
        print_error(f"Failed to query sync status from remote API: {exc}")
        raise click.ClickException(str(exc)) from exc


def _render_remote_sync_status(
    payload: dict[str, Any],
    api_url: str,
    *,
    as_json: bool,
) -> None:
    """Render remote synchronization telemetry panel and registered sources."""
    console = get_console()
    if as_json:
        console.print_json(data=payload)
        return

    telemetry = {
        "total_cycles": (
            payload.get("total_syncs") or payload.get("total_sync_cycles", 0)
        ),
        "last_success_at": _parse_optional_datetime(
            payload.get("last_success_at") or payload.get("last_successful_sync"),
        ),
        "latest_audit": _parse_audit_record(payload.get("last_sync")),
        "status": payload.get("current_status") or payload.get("status", "idle"),
    }
    sources = payload.get("sources", [])
    print_banner("SYNCHRONIZATION TELEMETRY & AUDIT STATUS")
    console.print(
        _render_system_panel(
            telemetry,
            f"Remote API ({api_url})",
            target_label="Remote API: ",
        ),
    )
    console.print()
    console.print(_render_sources_table(sources))


def _render_local_sync_status(
    engine: Engine,
    db_url_display: str,
    *,
    as_json: bool,
) -> None:
    """Render local relational database synchronization telemetry and sources."""
    console = get_console()
    if as_json:
        payload = _extract_db_sync_telemetry(engine)
        console.print_json(data=payload)
        return

    with get_sync_session(engine) as session:
        telemetry = _query_sync_telemetry(session)
        sources = _query_sources(session)

    print_banner("SYNCHRONIZATION TELEMETRY & AUDIT STATUS")
    console.print(
        _render_system_panel(
            telemetry,
            db_url_display,
            target_label="Database URL: ",
        ),
    )
    console.print()
    console.print(_render_sources_table(sources))


def _run_sync_status(
    ctx: click.Context | None,
    *,
    db_url: str | None,
    api_url: str | None,
    token: str | None,
    as_json: bool,
) -> None:
    """Orchestrate sync status inspection in local or remote mode."""
    api_url, token = _resolve_remote_credentials(ctx, api_url, token)
    if api_url:
        payload = _fetch_remote_sync_status(api_url, token)
        _render_remote_sync_status(payload, api_url, as_json=as_json)
        return

    obj = ctx.obj if ctx else None
    resolved_db_url = db_url or _extract_ctx_str(obj, "db_url")
    db_url_resolved = get_sync_database_url(resolved_db_url)
    engine = create_sync_engine(db_url_resolved)
    try:
        Base.metadata.create_all(engine)
        _render_local_sync_status(engine, db_url_resolved, as_json=as_json)
    except Exception as exc:
        print_error(f"Failed to query sync status from database: {exc}")
        raise click.ClickException(str(exc)) from exc


@click.group("sync", invoke_without_command=True)
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
    ctx: click.Context,
    *,
    source_code: str = "all",
    dry_run: bool = False,
    notify: bool = False,
    notify_individual: bool = False,
    db_url: str | None = None,
    season: str | None = None,
    api_url: str | None = None,
    token: str | None = None,
) -> None:
    """Ingest upstream schedules, reconcile conflicts, and detect changes."""
    _populate_ctx_params(ctx, api_url, token, db_url)
    if ctx.invoked_subcommand is not None:
        return

    _run_sync_trigger(
        ctx=ctx,
        source_code=source_code,
        dry_run=dry_run,
        notify=notify,
        notify_individual=notify_individual,
        db_url=db_url,
        season=season,
        api_url=api_url,
        token=token,
    )


@sync_command.command("trigger")
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
def sync_trigger_command(  # noqa: PLR0913 # pylint: disable=too-many-arguments,too-many-locals
    ctx: click.Context | None,
    *,
    source_code: str = "all",
    dry_run: bool = False,
    notify: bool = False,
    notify_individual: bool = False,
    db_url: str | None = None,
    season: str | None = None,
    api_url: str | None = None,
    token: str | None = None,
) -> None:
    """Trigger schedule crawl, reconciliation, and change detection pipeline."""
    _run_sync_trigger(
        ctx=ctx,
        source_code=source_code,
        dry_run=dry_run,
        notify=notify,
        notify_individual=notify_individual,
        db_url=db_url,
        season=season,
        api_url=api_url,
        token=token,
    )


@sync_command.command("status")
@click.option(
    "--db-url",
    envvar="DATABASE_URL",
    default=None,
    help="Database connection URL override (defaults to local SQLite or DATABASE_URL).",
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
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output synchronization telemetry as formatted JSON.",
)
@click.pass_context
def sync_status_command(
    ctx: click.Context | None,
    *,
    db_url: str | None = None,
    api_url: str | None = None,
    token: str | None = None,
    as_json: bool = False,
) -> None:
    """Display synchronization telemetry, latest audit cycle, and crawler sources."""
    _run_sync_status(
        ctx=ctx,
        db_url=db_url,
        api_url=api_url,
        token=token,
        as_json=as_json,
    )

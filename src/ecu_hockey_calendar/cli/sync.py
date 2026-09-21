"""Implementation of the 'ecu-hockey sync' CLI command.

Synchronizes schedule fixtures from upstream crawlers, reconciles conflicts,
detects state transitions, and persists updates to relational storage.
"""

# pylint: disable=too-many-lines

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import rich_click as click

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
from ecu_hockey_calendar.cli.production import (
    DEFAULT_PROD_API_URL,
    dispatch_production_sync,
    resolve_admin_token,
)
from ecu_hockey_calendar.cli.status import (
    _query_sources,
    _query_sync_telemetry,
    _render_sources_table,
    _render_system_panel,
)
from ecu_hockey_calendar.ingestion.acchockey_crawler import ACCHockeyCrawler
from ecu_hockey_calendar.ingestion.achahockey_crawler import ACHAHockeyCrawler
from ecu_hockey_calendar.ingestion.ecuhockey_crawler import ECUHockeyCrawler
from ecu_hockey_calendar.ingestion.instagram_crawler import InstagramCrawler
from ecu_hockey_calendar.ingestion.opponent_config import (
    OpponentConfigError,
    OpponentDirectory,
    resolve_opponent_directory,
)
from ecu_hockey_calendar.ingestion.opponent_crawler import OpponentCrawler
from ecu_hockey_calendar.ingestion.telemetry import (
    ConsoleScrapeObserver,
    ScrapeObserver,
)
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
    from pathlib import Path

    from rich.console import Console
    from sqlalchemy.engine import Engine

    from ecu_hockey_calendar.reconciliation.models import (
        ChangeDetectionCycleResult,
        DetectedConflict,
    )

__all__ = [
    "ACCHockeyCrawler",
    "ACHAHockeyCrawler",
    "Base",
    "ECUHockeyCrawler",
    "InstagramCrawler",
    "NotificationDispatcher",
    "OpponentCrawler",
    "_apply_prod_defaults",
    "_convert_parsed_to_source_record",
    "_ensure_data_source",
    "_execute_crawlers",
    "_execute_remote_sync",
    "_execute_sync_pipeline",
    "_extract_ctx_str",
    "_fetch_remote_sync_status",
    "_handle_remote_sync_result",
    "_load_baseline_games_from_db",
    "_maybe_dispatch_remote_sync",
    "_normalize_source_filter",
    "_populate_ctx_params",
    "_render_local_sync_status",
    "_render_remote_sync_status",
    "_render_sync_details",
    "_render_sync_results",
    "_render_sync_url",
    "_resolve_cli_opponent_directory",
    "_resolve_prod_flag",
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


def _render_sync_url(console: Console, api_url: str | None) -> None:
    """Display status URL line if remote API URL is present."""
    if api_url:
        status_url = f"{api_url.rstrip('/')}/api/v1/sync/status"
        console.print(f"  [bold]Status URL:[/bold]    [dim]{status_url}[/dim]")


def _render_sync_details(result: dict[str, Any], api_url: str | None) -> None:
    """Display Rich confirmation details for remote sync trigger result."""
    console = get_console()
    cycle_id = result.get("sync_cycle_id")
    target_source = result.get("target_source") or result.get("source")
    timestamp = result.get("timestamp")
    if cycle_id:
        console.print(f"  [bold]Run ID:[/bold]        [cyan]{cycle_id}[/cyan]")

    if target_source:
        console.print(f"  [bold]Target Source:[/bold] [cyan]{target_source}[/cyan]")

    if timestamp:
        console.print(f"  [bold]Dispatched At:[/bold] [dim]{timestamp}[/dim]")

    _render_sync_url(console, api_url)


def _handle_remote_sync_result(
    result: dict[str, Any],
    api_url: str | None = None,
) -> None:
    """Render warning or success message for remote sync trigger result."""
    if result.get("status") == "unsupported":
        warn_msg = result.get("message", "Synchronization trigger not supported.")
        print_warning(warn_msg)
        return

    status_msg = result.get("message") or result.get("status") or "Triggered"
    print_success(f"Remote synchronization dispatched successfully: {status_msg}")
    _render_sync_details(result, api_url)


def _execute_remote_sync(
    *,
    api_url: str,
    token: str | None,
    source_code: str,
    is_production: bool = False,
) -> None:
    """Dispatch synchronization trigger request to remote HTTP API."""
    console = get_console()
    label = (
        f"Production Web API ({api_url})"
        if is_production
        else f"Remote API ({api_url})"
    )
    console.print(
        f"Target: [bold cyan]{label}[/bold cyan]\n",
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

    _handle_remote_sync_result(result, api_url=api_url)


def _execute_sync_pipeline(  # noqa: PLR0913 # pylint: disable=too-many-arguments
    *,
    engine: Engine,
    source_filter: str,
    dry_run: bool,
    notify: bool,
    notify_individual: bool = False,
    season: str | None,
    verify_opponents: bool = False,
    observer: ScrapeObserver | None = None,
    opponent_directory: OpponentDirectory | None = None,
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
        verify_opponents=verify_opponents,
        observer=observer,
        opponent_directory=opponent_directory,
    )


def _extract_ctx_str(obj: object, key: str) -> str | None:
    """Extract string value from context dictionary."""
    if isinstance(obj, dict):
        val = obj.get(key)
        if val is not None:
            return str(val)

    return None


def _resolve_prod_flag(ctx: click.Context | None, prod: bool) -> bool:
    """Determine whether production mode is active."""
    if prod:
        return True

    if ctx and isinstance(ctx.obj, dict):
        return bool(ctx.obj.get("prod"))

    return False


def _apply_prod_defaults(
    url: str | None,
    token: str | None,
) -> tuple[str, str | None]:
    """Apply default production URL and token when in production mode."""
    target_url = url or DEFAULT_PROD_API_URL
    target_token = token or resolve_admin_token(None)
    return target_url, target_token


def _resolve_remote_credentials(
    ctx: click.Context | None,
    api_url: str | None,
    token: str | None,
    prod: bool = False,
) -> tuple[str | None, str | None]:
    """Extract and resolve remote API URL and admin token from CLI context."""
    obj = ctx.obj if ctx else None
    url = api_url if api_url is not None else _extract_ctx_str(obj, "api_url")
    tok = token if token is not None else _extract_ctx_str(obj, "token")
    if _resolve_prod_flag(ctx, prod):
        return _apply_prod_defaults(url, tok)

    return url, tok


def _render_sync_results(
    telemetry: list[dict[str, Any]],
    change_result: ChangeDetectionCycleResult,
    conflicts: list[DetectedConflict],
    *,
    dry_run: bool,
    verify_opponents: bool = False,
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
    if verify_opponents:
        summary_table.add_row(
            "Opponent Verification",
            "[bold green]Completed[/bold green]",
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


def _populate_ctx_params(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    ctx: click.Context | None,
    api_url: str | None,
    token: str | None,
    db_url: str | None,
    opponents_config: str | None = None,
    prod: bool = False,
) -> None:
    """Store group-level connection parameters in Click context object."""
    if ctx is None:
        return

    ctx.ensure_object(dict)
    params = {
        "api_url": api_url,
        "token": token,
        "db_url": db_url,
        "opponents_config": opponents_config,
    }
    for key, val in params.items():
        if val is not None:
            ctx.obj[key] = val

    if prod:
        ctx.obj["prod"] = True


def _resolve_cli_opponent_directory(
    ctx: click.Context | None,
    opponents_config: str | Path | None,
) -> OpponentDirectory:
    """Resolve OpponentDirectory for CLI execution with user-friendly error handling."""
    ctx_val = _extract_ctx_str(ctx.obj if ctx else None, "opponents_config")
    resolved_path = opponents_config or ctx_val
    try:
        return resolve_opponent_directory(resolved_path)
    except (FileNotFoundError, OpponentConfigError) as exc:
        err_msg = f"Invalid opponent configuration: {exc}"
        print_error(err_msg)
        raise click.ClickException(err_msg) from exc


def _resolve_sync_cli_flags(
    ctx: click.Context | None,
    verbose: bool,
    debug: bool,
) -> tuple[bool, bool]:
    """Extract and combine verbose and debug flags from CLI and context."""
    obj = ctx.obj if ctx and isinstance(ctx.obj, dict) else {}
    return verbose or bool(obj.get("verbose")), debug or bool(obj.get("debug"))


def _print_sync_banner(
    console: Console,
    dry_run: bool,
    source_code: str,
    db_url_resolved: str,
) -> None:
    """Print synchronization execution banner and run mode."""
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


def _run_sync_pipeline_with_progress(  # noqa: PLR0913 # pylint: disable=too-many-arguments
    *,
    engine: Engine,
    source_code: str,
    dry_run: bool,
    notify: bool,
    notify_individual: bool,
    season: str | None,
    verify_opponents: bool,
    observer: ScrapeObserver | None,
    console: Console,
    opponent_directory: OpponentDirectory | None = None,
) -> tuple[list[dict[str, Any]], ChangeDetectionCycleResult, list[DetectedConflict]]:
    """Execute sync pipeline with spinner or live observer telemetry."""
    if observer is not None:
        return _execute_sync_pipeline(
            engine=engine,
            source_filter=source_code.lower(),
            dry_run=dry_run,
            notify=notify,
            notify_individual=notify_individual,
            season=season,
            verify_opponents=verify_opponents,
            observer=observer,
            opponent_directory=opponent_directory,
        )

    with console.status(
        ("[bold #fec923]Crawling sources and reconciling fixtures...[/bold #fec923]"),
        spinner="dots",
    ):
        return _execute_sync_pipeline(
            engine=engine,
            source_filter=source_code.lower(),
            dry_run=dry_run,
            notify=notify,
            notify_individual=notify_individual,
            season=season,
            verify_opponents=verify_opponents,
            observer=None,
            opponent_directory=opponent_directory,
        )


def _maybe_dispatch_remote_sync(  # noqa: PLR0913 # pylint: disable=too-many-arguments
    *,
    is_prod: bool,
    method: str,
    api_url: str | None,
    token: str | None,
    source_code: str,
    dry_run: bool,
    notify: bool,
    notify_individual: bool,
    season: str | None,
) -> bool:
    """Dispatch production or remote API sync if applicable."""
    if is_prod or method in ("github", "render"):
        dispatch_production_sync(
            method=method,
            api_url=api_url or DEFAULT_PROD_API_URL,
            token=token,
            source_code=source_code,
            dry_run=dry_run,
            notify=notify,
            notify_individual=notify_individual,
            season=season,
            execute_remote_fn=_execute_remote_sync,
        )
        return True

    if api_url:
        _execute_remote_sync(api_url=api_url, token=token, source_code=source_code)
        return True

    return False


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
    verify_opponents: bool = False,
    verbose: bool = False,
    debug: bool = False,
    opponents_config: str | Path | None = None,
    prod: bool = False,
    method: str = "auto",
) -> None:
    """Execute schedule crawl, reconciliation, and diffing pipeline."""
    console = get_console()
    print_banner("SCHEDULE SYNCHRONIZATION & RECONCILIATION")

    opponent_directory = _resolve_cli_opponent_directory(ctx, opponents_config)
    is_verbose, is_debug = _resolve_sync_cli_flags(ctx, verbose, debug)
    api_url, token = _resolve_remote_credentials(ctx, api_url, token, prod=prod)
    is_prod = _resolve_prod_flag(ctx, prod)

    if _maybe_dispatch_remote_sync(
        is_prod=is_prod,
        method=method,
        api_url=api_url,
        token=token,
        source_code=source_code,
        dry_run=dry_run,
        notify=notify,
        notify_individual=notify_individual,
        season=season,
    ):
        return

    db_url_resolved = get_sync_database_url(db_url)
    engine = create_sync_engine(db_url_resolved)
    _print_sync_banner(console, dry_run, source_code, db_url_resolved)

    observer = (
        ConsoleScrapeObserver(console=console, verbose=is_verbose, debug=is_debug)
        if (is_verbose or is_debug)
        else None
    )

    try:
        telemetry, change_result, conflicts = _run_sync_pipeline_with_progress(
            engine=engine,
            source_code=source_code,
            dry_run=dry_run,
            notify=notify,
            notify_individual=notify_individual,
            season=season,
            verify_opponents=verify_opponents,
            observer=observer,
            console=console,
            opponent_directory=opponent_directory,
        )
    except Exception as exc:
        print_error(f"Synchronization pipeline encountered a fatal error: {exc}")
        raise click.ClickException(str(exc)) from exc

    _render_sync_results(
        telemetry,
        change_result,
        conflicts,
        dry_run=dry_run,
        verify_opponents=verify_opponents,
    )


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


def _run_sync_status(  # pylint: disable=too-many-arguments
    ctx: click.Context | None,
    *,
    db_url: str | None,
    api_url: str | None,
    token: str | None,
    as_json: bool,
    prod: bool = False,
) -> None:
    """Orchestrate sync status inspection in local or remote mode."""
    api_url, token = _resolve_remote_credentials(ctx, api_url, token, prod=prod)
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
    type=click.Choice(
        [
            "all",
            "ecuhockey",
            "acchockey",
            "achahockey",
            "instagram",
            "opponent",
            "social",
        ],
        case_sensitive=False,
    ),
    default="all",
    show_default=True,
    help="Restrict synchronization to a specific data source.",
)
@click.option(
    "--verify-opponents",
    is_flag=True,
    default=False,
    help="Perform reverse cross-checking against opponent schedule feeds.",
)
@click.option(
    "--opponents-config",
    "-O",
    "opponents_config",
    envvar="OPPONENTS_CONFIG",
    default=None,
    help="Path to YAML configuration file for opponent schedule feeds.",
)
@click.option(
    "--dry-run",
    "-n",
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
    "-S",
    default=None,
    help="Optional season filter (e.g., '2026-2027').",
)
@click.option(
    "--api-url",
    "-u",
    envvar="ECU_HOCKEY_API_URL",
    default=None,
    help="Remote ECU Hockey API base URL (e.g., 'https://ecu-hockey-api.onrender.com').",
)
@click.option(
    "--token",
    "-t",
    envvar="ECU_HOCKEY_ADMIN_TOKEN",
    default=None,
    help="Administrative authentication Bearer token for protected remote endpoints.",
)
@click.option(
    "--prod",
    "--production",
    "-p",
    "prod",
    is_flag=True,
    default=False,
    help=(
        "Target production environment "
        "(defaults API URL to https://ecu-hockey-api.onrender.com)."
    ),
)
@click.option(
    "--method",
    "-m",
    type=click.Choice(["auto", "api", "github", "render"], case_sensitive=False),
    default="auto",
    show_default=True,
    help=(
        "Production dispatch strategy "
        "(auto-detect, Web API, GitHub Actions, or Render)."
    ),
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Display URLs being scraped and extraction telemetry.",
)
@click.option(
    "--debug",
    "-d",
    is_flag=True,
    default=False,
    help="Display all HTTP wire requests, responses, headers, and body snippets.",
)
@click.pass_context
def sync_command(  # noqa: PLR0913 # pylint: disable=too-many-arguments,too-many-locals
    ctx: click.Context,
    *,
    source_code: str = "all",
    verify_opponents: bool = False,
    opponents_config: str | None = None,
    dry_run: bool = False,
    notify: bool = False,
    notify_individual: bool = False,
    db_url: str | None = None,
    season: str | None = None,
    api_url: str | None = None,
    token: str | None = None,
    verbose: bool = False,
    debug: bool = False,
    prod: bool = False,
    method: str = "auto",
) -> None:
    """Ingest upstream schedules, reconcile conflicts, and detect changes."""
    _populate_ctx_params(ctx, api_url, token, db_url, opponents_config, prod=prod)
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
        verify_opponents=verify_opponents,
        verbose=verbose,
        debug=debug,
        opponents_config=opponents_config,
        prod=prod,
        method=method,
    )


@sync_command.command("trigger")
@click.option(
    "--source",
    "-s",
    "source_code",
    type=click.Choice(
        [
            "all",
            "ecuhockey",
            "acchockey",
            "achahockey",
            "instagram",
            "opponent",
            "social",
        ],
        case_sensitive=False,
    ),
    default="all",
    show_default=True,
    help="Restrict synchronization to a specific data source.",
)
@click.option(
    "--verify-opponents",
    is_flag=True,
    default=False,
    help="Perform reverse cross-checking against opponent schedule feeds.",
)
@click.option(
    "--opponents-config",
    "-O",
    "opponents_config",
    envvar="OPPONENTS_CONFIG",
    default=None,
    help="Path to YAML configuration file for opponent schedule feeds.",
)
@click.option(
    "--dry-run",
    "-n",
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
    "-S",
    default=None,
    help="Optional season filter (e.g., '2026-2027').",
)
@click.option(
    "--api-url",
    "-u",
    envvar="ECU_HOCKEY_API_URL",
    default=None,
    help="Remote ECU Hockey API base URL (e.g., 'https://ecu-hockey-api.onrender.com').",
)
@click.option(
    "--token",
    "-t",
    envvar="ECU_HOCKEY_ADMIN_TOKEN",
    default=None,
    help="Administrative authentication Bearer token for protected remote endpoints.",
)
@click.option(
    "--prod",
    "--production",
    "-p",
    "prod",
    is_flag=True,
    default=False,
    help=(
        "Target production environment "
        "(defaults API URL to https://ecu-hockey-api.onrender.com)."
    ),
)
@click.option(
    "--method",
    "-m",
    type=click.Choice(["auto", "api", "github", "render"], case_sensitive=False),
    default="auto",
    show_default=True,
    help=(
        "Production dispatch strategy "
        "(auto-detect, Web API, GitHub Actions, or Render)."
    ),
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Display URLs being scraped and extraction telemetry.",
)
@click.option(
    "--debug",
    "-d",
    is_flag=True,
    default=False,
    help="Display all HTTP wire requests, responses, headers, and body snippets.",
)
@click.pass_context
def sync_trigger_command(  # noqa: PLR0913 # pylint: disable=too-many-arguments,too-many-locals
    ctx: click.Context | None,
    *,
    source_code: str = "all",
    verify_opponents: bool = False,
    opponents_config: str | None = None,
    dry_run: bool = False,
    notify: bool = False,
    notify_individual: bool = False,
    db_url: str | None = None,
    season: str | None = None,
    api_url: str | None = None,
    token: str | None = None,
    verbose: bool = False,
    debug: bool = False,
    prod: bool = False,
    method: str = "auto",
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
        verify_opponents=verify_opponents,
        verbose=verbose,
        debug=debug,
        opponents_config=opponents_config,
        prod=prod,
        method=method,
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
    "-u",
    envvar="ECU_HOCKEY_API_URL",
    default=None,
    help="Remote ECU Hockey API base URL (e.g., 'https://ecu-hockey-api.onrender.com').",
)
@click.option(
    "--token",
    "-t",
    envvar="ECU_HOCKEY_ADMIN_TOKEN",
    default=None,
    help="Administrative authentication Bearer token for protected remote endpoints.",
)
@click.option(
    "--prod",
    "--production",
    "-p",
    "prod",
    is_flag=True,
    default=False,
    help=(
        "Target production environment "
        "(defaults API URL to https://ecu-hockey-api.onrender.com)."
    ),
)
@click.option(
    "--json",
    "-j",
    "as_json",
    is_flag=True,
    default=False,
    help="Output synchronization telemetry as formatted JSON.",
)
@click.pass_context
def sync_status_command(  # pylint: disable=too-many-arguments
    ctx: click.Context | None,
    *,
    db_url: str | None = None,
    api_url: str | None = None,
    token: str | None = None,
    as_json: bool = False,
    prod: bool = False,
) -> None:
    """Display synchronization telemetry, latest audit cycle, and crawler sources."""
    _run_sync_status(
        ctx=ctx,
        db_url=db_url,
        api_url=api_url,
        token=token,
        as_json=as_json,
        prod=prod,
    )

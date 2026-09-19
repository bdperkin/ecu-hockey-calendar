"""Implementation of the 'ecu-hockey conflicts' CLI command.

Inspects active cross-source discrepancies and conflicting fixtures requiring
administrative review, and provides workflows for administrative manual resolution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

from ecu_hockey_calendar.api.client import (
    RemoteApiAuthError,
    RemoteApiClient,
    RemoteApiError,
)
from ecu_hockey_calendar.api.routes.conflicts import (
    _active_conflicts_query,
    _change_model_to_conflict,
)
from ecu_hockey_calendar.cli.console import (
    create_table,
    format_severity_badge,
    get_console,
    print_banner,
    print_error,
    print_panel,
)
from ecu_hockey_calendar.cli.production import DEFAULT_PROD_API_URL
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.engine import (
    create_sync_engine,
    get_sync_database_url,
    get_sync_session,
)
from ecu_hockey_calendar.storage.overrides import (
    resolve_conflict as storage_resolve_conflict,
)

if TYPE_CHECKING:
    from rich.table import Table
    from sqlalchemy.orm import Session

    from ecu_hockey_calendar.storage.models import GameChangeModel


__all__ = [
    "_fetch_remote_conflicts",
    "_handle_local_conflicts_list",
    "_handle_remote_conflicts_list",
    "_matches_filter",
    "_matches_review_filter",
    "_matches_text_filter",
    "_normalize_conflict",
    "_query_conflicts",
    "_render_conflicts_count",
    "_render_conflicts_display",
    "_render_conflicts_output",
    "_render_conflicts_table",
    "_render_resolve_display",
    "_render_resolve_output",
    "_resolve_local_conflict",
    "_resolve_remote_conflict",
    "_resolve_remote_credentials",
    "_run_conflicts_list",
    "_run_conflicts_resolve",
    "_slice_conflicts",
    "_validate_resolve_args",
    "conflicts_command",
    "list_command",
    "resolve_command",
]


def _matches_text_filter(
    actual: object,
    expected: str | None,
    *,
    case_fold: bool = False,
) -> bool:
    """Check whether field matches expected filter text."""
    if not expected:
        return True

    act_str = str(actual or "").strip()
    exp_str = expected.strip()
    if case_fold:
        return act_str.lower() == exp_str.lower()

    return act_str.upper() == exp_str.upper()


def _matches_review_filter(item: dict[str, Any], is_review: bool) -> bool:
    """Check if item satisfies administrative review requirement."""
    return not (is_review and not item.get("requires_review", False))


def _matches_filter(
    item: dict[str, Any],
    *,
    severity: str | None,
    game_id: str | None,
    field_name: str | None,
    review_only: bool = False,
    requires_review: bool | None = None,
) -> bool:
    """Filter conflict items against command line options."""
    is_review = review_only if requires_review is None else requires_review
    if not _matches_text_filter(item.get("severity"), severity):
        return False

    if not _matches_text_filter(item.get("game_id"), game_id):
        return False

    if not _matches_text_filter(item.get("field"), field_name, case_fold=True):
        return False

    return _matches_review_filter(item, is_review)


def _normalize_conflict(change: GameChangeModel) -> dict[str, Any]:
    """Convert change model and extract review status."""
    item = _change_model_to_conflict(change)
    diffs = change.field_diffs or []
    if diffs and "requires_review" in diffs[0]:
        item["requires_review"] = bool(diffs[0]["requires_review"])

    return item


def _slice_conflicts(
    items: list[dict[str, Any]],
    offset: int,
    limit: int | None,
) -> list[dict[str, Any]]:
    """Slice conflict list based on offset and limit."""
    end = (offset + limit) if limit is not None else None
    return items[offset:end]


def _query_conflicts(
    session: Session,
    *,
    severity: str | None,
    game_id: str | None,
    field_name: str | None,
    review_only: bool = False,
    requires_review: bool | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Query and filter conflict records from storage."""
    is_review = review_only if requires_review is None else requires_review
    stmt = _active_conflicts_query()
    changes = session.scalars(stmt).all()
    all_conflicts = [_normalize_conflict(c) for c in changes]

    filtered = [
        c
        for c in all_conflicts
        if _matches_filter(
            c,
            severity=severity,
            game_id=game_id,
            field_name=field_name,
            requires_review=is_review,
        )
    ]
    return _slice_conflicts(filtered, offset, limit), len(filtered)


def _render_conflicts_table(conflicts: list[dict[str, Any]]) -> Table:
    """Build formatted conflicts table."""
    table = create_table(
        f"Active Schedule Discrepancies ({len(conflicts)} found)",
        [
            ("Game ID", "bold cyan"),
            ("Field", "bold #fec923"),
            ("Severity", "bold"),
            ("Review Needed", "bold"),
            ("Discrepancy Details", "white"),
            ("Recorded At", "dim"),
        ],
    )

    for c in conflicts:
        sev_badge = format_severity_badge(c.get("severity", "MEDIUM"))
        rev_needed = (
            "[bold red]YES[/bold red]" if c.get("requires_review") else "[dim]No[/dim]"
        )
        rec_at = str(c.get("recorded_at") or "Unknown").replace("T", " ")[:19]

        table.add_row(
            str(c.get("game_id", "N/A")),
            str(c.get("field", "N/A")),
            sev_badge,
            rev_needed,
            str(c.get("summary", "")),
            str(rec_at),
        )

    return table


def _extract_ctx_str(obj: object, key: str) -> str | None:
    """Extract string value from context dictionary."""
    if isinstance(obj, dict):
        val = obj.get(key)
        if val is not None:
            return str(val)

    return None


def _is_prod_target(obj: object, prod: bool) -> bool:
    """Determine whether production target is requested."""
    if prod:
        return True

    return bool(isinstance(obj, dict) and obj.get("prod"))


def _resolve_api_url(obj: object, api_url: str | None, *, prod: bool) -> str | None:
    """Resolve target API URL respecting production flag and context."""
    if api_url is not None:
        return api_url

    if _is_prod_target(obj, prod):
        return DEFAULT_PROD_API_URL

    return _extract_ctx_str(obj, "api_url")


def _resolve_remote_credentials(
    ctx: click.Context | None,
    api_url: str | None,
    token: str | None,
    *,
    prod: bool = False,
) -> tuple[str | None, str | None]:
    """Extract and resolve remote API URL and admin token from CLI context."""
    obj = ctx.obj if ctx else None
    url = _resolve_api_url(obj, api_url, prod=prod)
    tok = token if token is not None else _extract_ctx_str(obj, "token")
    return url, tok


def _fetch_remote_conflicts(
    api_url: str,
    token: str | None,
    *,
    severity: str | None,
    game_id: str | None,
    field_name: str | None,
    review_only: bool,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    """Fetch conflict items from a remote ECU Hockey HTTP API instance."""
    client = RemoteApiClient(api_url, token=token)
    try:
        payload = client.get_conflicts(
            severity=severity,
            game_id=game_id,
            field_name=field_name,
            review_only=review_only,
            limit=limit,
            offset=offset,
        )
    except RemoteApiAuthError as exc:
        auth_msg = (
            f"Authentication required: {exc}\n"
            "Provide --token <TOKEN> or set ECU_HOCKEY_ADMIN_TOKEN."
        )
        print_error(auth_msg)
        err_msg = "Authentication failed for remote conflicts."
        raise click.ClickException(err_msg) from exc
    except RemoteApiError as exc:
        print_error(f"Failed to query conflicts from remote API: {exc}")
        raise click.ClickException(str(exc)) from exc

    conflicts = payload.get("conflicts", [])
    total_count = int(payload.get("total_conflicts", len(conflicts)))
    return conflicts, total_count, payload


def _render_conflicts_count(
    conflicts_count: int,
    total_count: int,
    *,
    limit: int | None,
    offset: int,
) -> None:
    """Print displayed discrepancies count and pagination information."""
    console = get_console()
    if offset > 0 or limit is not None:
        console.print(
            f"[bold]Discrepancies Displayed:[/] "
            f"[bold cyan]{conflicts_count}[/bold cyan] of "
            f"[bold cyan]{total_count}[/bold cyan] (offset: {offset})",
        )
    else:
        console.print(
            f"[bold]Total Discrepancies Displayed:[/] "
            f"[bold cyan]{conflicts_count}[/bold cyan]",
        )


def _render_conflicts_display(
    conflicts: list[dict[str, Any]],
    total_count: int,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> None:
    """Render conflicts table or clean-state panel."""
    if not conflicts and total_count == 0:
        clean_msg = (
            "[bold green]No active schedule conflicts or discrepancies found."
            "[/bold green]\n"
            "All crawled fixtures are aligned across upstream sources."
        )
        print_panel(
            clean_msg,
            title="[bold green]Conflict Status Clean[/bold green]",
            border_style="green",
        )
        return

    console = get_console()
    console.print(_render_conflicts_table(conflicts))
    _render_conflicts_count(
        len(conflicts),
        total_count,
        limit=limit,
        offset=offset,
    )


def _render_conflicts_output(
    conflicts: list[dict[str, Any]],
    total_count: int,
    *,
    as_json: bool,
    payload: dict[str, Any] | None,
    limit: int | None,
    offset: int,
) -> None:
    """Render conflicts as JSON or Rich table."""
    console = get_console()
    if as_json:
        json_data = payload or {
            "total_conflicts": total_count,
            "filtered_count": len(conflicts),
            "limit": limit,
            "offset": offset,
            "conflicts": conflicts,
        }
        console.print_json(data=json_data)
        return

    _render_conflicts_display(
        conflicts,
        total_count,
        limit=limit,
        offset=offset,
    )


def _handle_remote_conflicts_list(  # noqa: PLR0913 # pylint: disable=too-many-arguments
    api_url: str,
    token: str | None,
    *,
    severity: str | None,
    game_id: str | None,
    field_name: str | None,
    requires_review: bool,
    limit: int | None,
    offset: int,
    as_json: bool,
) -> None:
    """Fetch and render conflict records from a remote API instance."""
    if not as_json:
        get_console().print(
            f"Target: [bold cyan]Remote API ({api_url})[/bold cyan]\n",
        )

    conflicts, total_count, payload = _fetch_remote_conflicts(
        api_url,
        token,
        severity=severity,
        game_id=game_id,
        field_name=field_name,
        review_only=requires_review,
        limit=limit,
        offset=offset,
    )
    _render_conflicts_output(
        conflicts,
        total_count,
        as_json=as_json,
        payload=payload,
        limit=limit,
        offset=offset,
    )


def _handle_local_conflicts_list(
    db_url: str | None,
    *,
    severity: str | None,
    game_id: str | None,
    field_name: str | None,
    requires_review: bool,
    limit: int | None,
    offset: int,
    as_json: bool,
) -> None:
    """Query and render conflict records from local relational database."""
    db_url_resolved = get_sync_database_url(db_url)
    engine = create_sync_engine(db_url_resolved)
    try:
        Base.metadata.create_all(engine)
        with get_sync_session(engine) as session:
            conflicts, total_count = _query_conflicts(
                session,
                severity=severity,
                game_id=game_id,
                field_name=field_name,
                requires_review=requires_review,
                limit=limit,
                offset=offset,
            )
    except Exception as exc:
        print_error(f"Failed to query conflicts from database: {exc}")
        raise click.ClickException(str(exc)) from exc

    _render_conflicts_output(
        conflicts,
        total_count,
        as_json=as_json,
        payload=None,
        limit=limit,
        offset=offset,
    )


def _run_conflicts_list(  # noqa: PLR0913 # pylint: disable=too-many-arguments
    ctx: click.Context | None,
    *,
    severity: str | None,
    game_id: str | None,
    field_name: str | None,
    requires_review: bool,
    limit: int | None = None,
    offset: int = 0,
    as_json: bool = False,
    db_url: str | None,
    api_url: str | None = None,
    token: str | None = None,
    prod: bool = False,
) -> None:
    """Execute list workflow for schedule conflicts."""
    if not as_json:
        print_banner("CROSS-SOURCE SCHEDULE CONFLICTS & DISCREPANCIES")

    api_url, token = _resolve_remote_credentials(ctx, api_url, token, prod=prod)
    if api_url:
        _handle_remote_conflicts_list(
            api_url,
            token,
            severity=severity,
            game_id=game_id,
            field_name=field_name,
            requires_review=requires_review,
            limit=limit,
            offset=offset,
            as_json=as_json,
        )
        return

    _handle_local_conflicts_list(
        db_url,
        severity=severity,
        game_id=game_id,
        field_name=field_name,
        requires_review=requires_review,
        limit=limit,
        offset=offset,
        as_json=as_json,
    )


def _check_field_value_pair(field: str | None, value: str | None) -> None:
    """Ensure value accompanies field when specified."""
    if field and not value:
        err = "When specifying --field, --value must also be provided."
        raise click.ClickException(err)


def _validate_resolve_args(
    field: str | None,
    value: str | None,
    accept_source: str | None,
) -> None:
    """Validate presence and consistency of conflict resolution options."""
    _check_field_value_pair(field, value)
    has_override = bool(field and value)
    if not accept_source and not has_override:
        err = (
            "Must specify either --accept-source <SOURCE> "
            "or both --field <NAME> and --value <VAL>."
        )
        raise click.ClickException(err)


def _resolve_remote_conflict(
    api_url: str,
    token: str | None,
    *,
    conflict_id: str,
    field: str | None,
    value: str | None,
    accept_source: str | None,
    notes: str | None,
    resolved_by: str | None,
) -> dict[str, Any]:
    """Execute conflict resolution via remote API."""
    client = RemoteApiClient(api_url, token=token)
    try:
        return client.resolve_conflict(
            conflict_id,
            field=field,
            value=value,
            accept_source=accept_source,
            notes=notes,
            resolved_by=resolved_by or "admin",
        )
    except RemoteApiAuthError as exc:
        auth_msg = (
            f"Authentication required: {exc}\n"
            "Provide --token <TOKEN> or set ECU_HOCKEY_ADMIN_TOKEN."
        )
        print_error(auth_msg)
        err_msg = "Authentication failed for remote conflict resolution."
        raise click.ClickException(err_msg) from exc
    except RemoteApiError as exc:
        print_error(f"Failed to resolve conflict on remote API: {exc}")
        raise click.ClickException(str(exc)) from exc


def _resolve_local_conflict(
    db_url: str | None,
    *,
    conflict_id: str,
    field: str | None,
    value: str | None,
    accept_source: str | None,
    notes: str | None,
    resolved_by: str | None,
) -> dict[str, Any]:
    """Execute conflict resolution directly in local database storage."""
    db_url_resolved = get_sync_database_url(db_url)
    engine = create_sync_engine(db_url_resolved)
    try:
        Base.metadata.create_all(engine)
        with get_sync_session(engine) as session:
            result = storage_resolve_conflict(
                session,
                conflict_id,
                field_name=field,
                override_value=value,
                accept_source=accept_source,
                resolved_by=resolved_by or "admin",
                notes=notes,
            )
            session.commit()
            return result
    except ValueError as exc:
        print_error(f"Failed to resolve conflict: {exc}")
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        print_error(f"Database error while resolving conflict: {exc}")
        raise click.ClickException(str(exc)) from exc


def _render_resolve_display(result: dict[str, Any]) -> None:
    """Render Rich confirmation panel for manual conflict resolution."""
    cid = result.get("conflict_id", "N/A")
    gid = result.get("game_id", "N/A")
    fld = result.get("field", "N/A")
    val = result.get("value", "N/A")
    src = result.get("accepted_source") or "manual"
    user = result.get("resolved_by", "admin")

    msg = (
        f"[bold green]Conflict Resolved Successfully![/bold green]\n\n"
        f"  [bold]Conflict ID:[/]     [cyan]{cid}[/cyan]\n"
        f"  [bold]Game ID:[/]         [cyan]{gid}[/cyan]\n"
        f"  [bold]Field:[/]           [#fec923]{fld}[/#fec923]\n"
        f"  [bold]Override Value:[/]  [white]{val}[/white]\n"
        f"  [bold]Accepted Source:[/] [dim]{src}[/dim]\n"
        f"  [bold]Resolved By:[/]     [dim]{user}[/dim]"
    )
    print_panel(
        msg,
        title="[bold green]Conflict Resolution Complete[/bold green]",
        border_style="green",
    )


def _render_resolve_output(result: dict[str, Any], *, as_json: bool) -> None:
    """Render resolution outcome as JSON or formatted panel."""
    if as_json:
        get_console().print_json(data=result)
        return

    _render_resolve_display(result)


def _run_conflicts_resolve(  # noqa: PLR0913 # pylint: disable=too-many-arguments
    ctx: click.Context | None,
    *,
    conflict_id: str,
    field: str | None,
    value: str | None,
    accept_source: str | None,
    notes: str | None,
    resolved_by: str | None,
    db_url: str | None,
    api_url: str | None,
    token: str | None,
    prod: bool,
    as_json: bool,
) -> None:
    """Execute resolution workflow for a specific schedule discrepancy."""
    _validate_resolve_args(field, value, accept_source)
    api_url, token = _resolve_remote_credentials(ctx, api_url, token, prod=prod)
    if api_url:
        result = _resolve_remote_conflict(
            api_url,
            token,
            conflict_id=conflict_id,
            field=field,
            value=value,
            accept_source=accept_source,
            notes=notes,
            resolved_by=resolved_by,
        )
    else:
        result = _resolve_local_conflict(
            db_url,
            conflict_id=conflict_id,
            field=field,
            value=value,
            accept_source=accept_source,
            notes=notes,
            resolved_by=resolved_by,
        )

    _render_resolve_output(result, as_json=as_json)


@click.group("conflicts", invoke_without_command=True)
@click.option(
    "--severity",
    type=click.Choice(["LOW", "MEDIUM", "HIGH", "CRITICAL"], case_sensitive=False),
    default=None,
    help="Filter discrepancies by severity level.",
)
@click.option(
    "--game-id",
    default=None,
    help="Filter discrepancies for a specific canonical game identifier.",
)
@click.option(
    "--field",
    "--field-name",
    "field_name",
    default=None,
    help=(
        "Filter discrepancies by conflicting attribute name "
        "(e.g., 'venue', 'start_time')."
    ),
)
@click.option(
    "--requires-review/--all",
    "--review-only/--show-all",
    "requires_review",
    default=False,
    help="Show only discrepancies flagged as requiring administrative review.",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    default=None,
    help="Maximum number of discrepancies to return or display.",
)
@click.option(
    "--offset",
    type=click.IntRange(min=0),
    default=0,
    show_default=True,
    help="Number of discrepancies to skip for pagination.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output discrepancies as formatted JSON.",
)
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
    "--prod",
    "--production",
    "prod",
    is_flag=True,
    default=False,
    help="Target production environment (https://ecu-hockey-api.onrender.com).",
)
@click.pass_context
def conflicts_command(  # noqa: PLR0913 # pylint: disable=too-many-locals,too-many-arguments
    ctx: click.Context | None,
    *,
    severity: str | None = None,
    game_id: str | None = None,
    field_name: str | None = None,
    requires_review: bool = False,
    limit: int | None = None,
    offset: int = 0,
    as_json: bool = False,
    db_url: str | None = None,
    api_url: str | None = None,
    token: str | None = None,
    prod: bool = False,
) -> None:
    """Inspect and resolve schedule discrepancies."""
    if ctx and ctx.invoked_subcommand is not None:
        return

    _run_conflicts_list(
        ctx,
        severity=severity,
        game_id=game_id,
        field_name=field_name,
        requires_review=requires_review,
        limit=limit,
        offset=offset,
        as_json=as_json,
        db_url=db_url,
        api_url=api_url,
        token=token,
        prod=prod,
    )


@conflicts_command.command("list")
@click.option(
    "--severity",
    type=click.Choice(["LOW", "MEDIUM", "HIGH", "CRITICAL"], case_sensitive=False),
    default=None,
    help="Filter discrepancies by severity level.",
)
@click.option(
    "--game-id",
    default=None,
    help="Filter discrepancies for a specific canonical game identifier.",
)
@click.option(
    "--field",
    "--field-name",
    "field_name",
    default=None,
    help="Filter discrepancies by conflicting attribute name.",
)
@click.option(
    "--requires-review/--all",
    "--review-only/--show-all",
    "requires_review",
    default=False,
    help="Show only discrepancies flagged as requiring administrative review.",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    default=None,
    help="Maximum number of discrepancies to return or display.",
)
@click.option(
    "--offset",
    type=click.IntRange(min=0),
    default=0,
    show_default=True,
    help="Number of discrepancies to skip for pagination.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output discrepancies as formatted JSON.",
)
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
    "--prod",
    "--production",
    "prod",
    is_flag=True,
    default=False,
    help="Target production environment (https://ecu-hockey-api.onrender.com).",
)
@click.pass_context
def list_command(  # noqa: PLR0913 # pylint: disable=too-many-locals,too-many-arguments
    ctx: click.Context | None,
    *,
    severity: str | None = None,
    game_id: str | None = None,
    field_name: str | None = None,
    requires_review: bool = False,
    limit: int | None = None,
    offset: int = 0,
    as_json: bool = False,
    db_url: str | None = None,
    api_url: str | None = None,
    token: str | None = None,
    prod: bool = False,
) -> None:
    """List active cross-source discrepancies in a formatted table or JSON."""
    _run_conflicts_list(
        ctx,
        severity=severity,
        game_id=game_id,
        field_name=field_name,
        requires_review=requires_review,
        limit=limit,
        offset=offset,
        as_json=as_json,
        db_url=db_url,
        api_url=api_url,
        token=token,
        prod=prod,
    )


@conflicts_command.command("resolve")
@click.argument("conflict_id", required=True)
@click.option(
    "--field",
    "--field-name",
    "field",
    default=None,
    help="Attribute name to override (e.g. 'venue', 'start_time').",
)
@click.option(
    "--value",
    "value",
    default=None,
    help="Explicit override value to apply to conflicting attribute.",
)
@click.option(
    "--accept-source",
    "accept_source",
    default=None,
    help="Accept upstream data source value (e.g. 'ECU Hockey', 'achahockey').",
)
@click.option(
    "--notes",
    default=None,
    help="Audit notes explaining the manual resolution decision.",
)
@click.option(
    "--resolved-by",
    default=None,
    help="Username or administrator identifier performing the resolution.",
)
@click.option(
    "--prod",
    "--production",
    "prod",
    is_flag=True,
    default=False,
    help="Resolve conflict on production API instance.",
)
@click.option(
    "--api-url",
    envvar="ECU_HOCKEY_API_URL",
    default=None,
    help="Remote ECU Hockey API base URL.",
)
@click.option(
    "--token",
    envvar="ECU_HOCKEY_ADMIN_TOKEN",
    default=None,
    help="Administrative authentication Bearer token.",
)
@click.option(
    "--db-url",
    envvar="DATABASE_URL",
    default=None,
    help="Database connection URL override.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output resolution result as formatted JSON.",
)
@click.pass_context
def resolve_command(  # noqa: PLR0913 # pylint: disable=too-many-arguments
    ctx: click.Context | None,
    *,
    conflict_id: str,
    field: str | None = None,
    value: str | None = None,
    accept_source: str | None = None,
    notes: str | None = None,
    resolved_by: str | None = None,
    prod: bool = False,
    api_url: str | None = None,
    token: str | None = None,
    db_url: str | None = None,
    as_json: bool = False,
) -> None:
    """Manually resolve a schedule conflict by accepting a source or override value."""
    _run_conflicts_resolve(
        ctx,
        conflict_id=conflict_id,
        field=field,
        value=value,
        accept_source=accept_source,
        notes=notes,
        resolved_by=resolved_by,
        db_url=db_url,
        api_url=api_url,
        token=token,
        prod=prod,
        as_json=as_json,
    )

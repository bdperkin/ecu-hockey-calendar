"""Implementation of the 'ecu-hockey conflicts' CLI command.

Inspects active cross-source discrepancies and conflicting fixtures requiring
administrative review.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click
from sqlalchemy import select

from ecu_hockey_calendar.api.client import (
    RemoteApiAuthError,
    RemoteApiClient,
    RemoteApiError,
)
from ecu_hockey_calendar.api.routes.conflicts import (
    CONFLICT_CHANGE_TYPES,
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
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.engine import (
    create_sync_engine,
    get_sync_database_url,
    get_sync_session,
)
from ecu_hockey_calendar.storage.models import GameChangeModel

if TYPE_CHECKING:
    from rich.table import Table
    from sqlalchemy.orm import Session


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


def _matches_filter(
    item: dict[str, Any],
    *,
    severity: str | None,
    game_id: str | None,
    field_name: str | None,
    review_only: bool,
) -> bool:
    """Filter conflict items against command line options."""
    if not _matches_text_filter(item.get("severity"), severity):
        return False

    if not _matches_text_filter(item.get("game_id"), game_id):
        return False

    if not _matches_text_filter(item.get("field"), field_name, case_fold=True):
        return False

    return not (review_only and not item.get("requires_review", False))


def _normalize_conflict(change: GameChangeModel) -> dict[str, Any]:
    """Convert change model and extract review status."""
    item = _change_model_to_conflict(change)
    diffs = change.field_diffs or []
    if diffs and "requires_review" in diffs[0]:
        item["requires_review"] = bool(diffs[0]["requires_review"])

    return item


def _query_conflicts(
    session: Session,
    *,
    severity: str | None,
    game_id: str | None,
    field_name: str | None,
    review_only: bool,
) -> list[dict[str, Any]]:
    """Query and filter conflict records from storage."""
    stmt = (
        select(GameChangeModel)
        .where(GameChangeModel.change_type.in_(CONFLICT_CHANGE_TYPES))
        .order_by(GameChangeModel.recorded_at.desc())
    )
    changes = session.scalars(stmt).all()
    all_conflicts = [_normalize_conflict(c) for c in changes]

    return [
        c
        for c in all_conflicts
        if _matches_filter(
            c,
            severity=severity,
            game_id=game_id,
            field_name=field_name,
            review_only=review_only,
        )
    ]


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


def _fetch_remote_conflicts(
    api_url: str,
    token: str | None,
    *,
    severity: str | None,
    game_id: str | None,
    field_name: str | None,
    review_only: bool,
) -> list[dict[str, Any]]:
    """Fetch conflict items from a remote ECU Hockey HTTP API instance."""
    client = RemoteApiClient(api_url, token=token)
    try:
        payload = client.get_conflicts(
            severity=severity,
            game_id=game_id,
            field_name=field_name,
            review_only=review_only,
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

    return payload.get("conflicts", [])


def _render_conflicts_display(conflicts: list[dict[str, Any]]) -> None:
    """Render conflicts table or clean-state panel."""
    console = get_console()
    if not conflicts:
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

    console.print(_render_conflicts_table(conflicts))
    console.print(
        "[bold]Total Discrepancies Displayed:[/] "
        f"[bold cyan]{len(conflicts)}[/bold cyan]",
    )


@click.command("conflicts")
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
    "field_name",
    default=None,
    help=(
        "Filter discrepancies by conflicting attribute name "
        "(e.g., 'venue', 'start_time')."
    ),
)
@click.option(
    "--review-only/--all",
    default=False,
    help="Show only discrepancies flagged as requiring administrative review.",
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
@click.pass_context
def conflicts_command(  # pylint: disable=too-many-locals
    ctx: click.Context | None,
    *,
    severity: str | None,
    game_id: str | None,
    field_name: str | None,
    review_only: bool,
    db_url: str | None,
    api_url: str | None = None,
    token: str | None = None,
) -> None:
    """Display active cross-source discrepancies in a formatted table."""
    print_banner("CROSS-SOURCE SCHEDULE CONFLICTS & DISCREPANCIES")

    api_url, token = _resolve_remote_credentials(ctx, api_url, token)
    if api_url:
        console = get_console()
        console.print(f"Target: [bold cyan]Remote API ({api_url})[/bold cyan]\n")
        conflicts = _fetch_remote_conflicts(
            api_url,
            token,
            severity=severity,
            game_id=game_id,
            field_name=field_name,
            review_only=review_only,
        )
        _render_conflicts_display(conflicts)
        return

    db_url_resolved = get_sync_database_url(db_url)
    engine = create_sync_engine(db_url_resolved)
    try:
        Base.metadata.create_all(engine)
        with get_sync_session(engine) as session:
            conflicts = _query_conflicts(
                session,
                severity=severity,
                game_id=game_id,
                field_name=field_name,
                review_only=review_only,
            )
    except Exception as exc:
        print_error(f"Failed to query conflicts from database: {exc}")
        raise click.ClickException(str(exc)) from exc

    _render_conflicts_display(conflicts)

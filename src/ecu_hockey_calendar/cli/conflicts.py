"""Implementation of the 'ecu-hockey conflicts' CLI command.

Inspects active cross-source discrepancies and conflicting fixtures requiring
administrative review.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click
from sqlalchemy import select

from ecu_hockey_calendar.api.routes.conflicts import _change_model_to_conflict
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
        .where(GameChangeModel.change_type.in_(["CONFLICT", "DISCREPANCY"]))
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
def conflicts_command(  # pylint: disable=too-many-locals
    *,
    severity: str | None,
    game_id: str | None,
    field_name: str | None,
    review_only: bool,
    db_url: str | None,
) -> None:
    """Display active cross-source discrepancies in a formatted table."""
    console = get_console()
    print_banner("CROSS-SOURCE SCHEDULE CONFLICTS & DISCREPANCIES")

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

    if not conflicts:
        print_panel(
            "[bold green]No active schedule conflicts or discrepancies found."
            "[/bold green]\n"
            "All crawled fixtures are aligned across upstream sources.",
            title="[bold green]Conflict Status Clean[/bold green]",
            border_style="green",
        )
        return

    console.print(_render_conflicts_table(conflicts))
    console.print()
    console.print(
        "[bold]Total Discrepancies Displayed:[/] "
        f"[bold cyan]{len(conflicts)}[/bold cyan]",
    )

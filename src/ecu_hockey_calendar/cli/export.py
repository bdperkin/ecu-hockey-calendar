"""Implementation of the 'ecu-hockey export' CLI command.

Exports the master schedule into RFC 5545 iCalendar (.ics), JSON, CSV, or HTML formats
with query parameter filtering.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click
from sqlalchemy import select

from ecu_hockey_calendar.api.schedule_service import ScheduleDataService
from ecu_hockey_calendar.api.service import CalendarFeedService
from ecu_hockey_calendar.calendar import ECUHockeyCalendar
from ecu_hockey_calendar.cli.console import (
    print_error,
    print_panel,
)
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.engine import (
    create_sync_engine,
    get_sync_database_url,
    get_sync_session,
)
from ecu_hockey_calendar.storage.models import GameModel

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ecu_hockey_calendar.models import Game


def _load_games(
    session: Session,
    season: str | None = None,
) -> list[Game]:
    """Retrieve games from database or fall back to default fixtures."""
    stmt = select(GameModel)
    if season:
        stmt = stmt.where(GameModel.season == season)

    db_games = session.scalars(stmt).all()
    if db_games:
        return [g.to_domain() for g in db_games]

    default_cal = ECUHockeyCalendar()
    return list(default_cal.schedule.games)


def _detect_format(
    fmt: str | None,
    output_path: str | Path | None,
    *,
    embed: bool = False,
) -> str:
    """Infer export format from explicit argument or output file extension.

    Args:
        fmt: Explicitly specified format string.
        output_path: Destination file path.
        embed: Whether embed mode is requested.

    Returns:
        Resolved format string ('ics', 'json', 'csv', or 'html').
    """
    if fmt:
        return fmt.lower()

    if output_path:
        ext = Path(output_path).suffix.lower().lstrip(".")
        if ext in ("ics", "json", "csv", "html", "pdf"):
            return ext

    if embed:
        return "html"

    return "ics"


def _serialize_schedule(
    games: list[Game],
    resolved_format: str,
    *,
    season: str | None,
    opponent: str | None,
    home_only: bool,
    status_query: str | None,
    include_past: bool,
    embed: bool = False,
) -> str | bytes:
    """Serialize games into ics, json, csv, html, or pdf format."""
    if resolved_format == "ics":
        ics_svc = CalendarFeedService()
        return ics_svc.generate_ics_feed(
            games,
            season=season,
            include_past=include_past,
        )

    data_svc = ScheduleDataService()
    if resolved_format == "json":
        return data_svc.generate_json_string(
            games,
            season=season,
            opponent=opponent,
            home_only=home_only,
            status=status_query,
        )

    if resolved_format == "html":
        return data_svc.generate_html_schedule(
            games,
            season=season,
            opponent=opponent,
            home_only=home_only,
            status=status_query,
            embed=embed,
        )

    if resolved_format == "pdf":
        return data_svc.generate_pdf_schedule(
            games,
            season=season,
            opponent=opponent,
            home_only=home_only,
            status=status_query,
        )

    return data_svc.generate_csv_feed(
        games,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status=status_query,
    )


def _write_binary_export(output_path: Path | None, data: bytes) -> int:
    """Write binary content to destination file or standard output."""
    if output_path is None:
        sys.stdout.buffer.write(data)
        return len(data)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
    except OSError as exc:
        print_error(f"Failed to write output file {output_path}: {exc}")
        raise click.ClickException(str(exc)) from exc

    return len(data)


def _write_text_export(output_path: Path | None, content: str) -> int:
    """Write normalized text content to destination file or standard output."""
    normalized = content if content.endswith(("\n", "\r\n")) else f"{content}\n"
    if output_path is None:
        click.echo(normalized, nl=False)
        return len(normalized.encode("utf-8"))

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(normalized, encoding="utf-8")
    except OSError as exc:
        print_error(f"Failed to write output file {output_path}: {exc}")
        raise click.ClickException(str(exc)) from exc

    return len(normalized.encode("utf-8"))


def _write_export_output(
    output_path: Path | None,
    content: str | bytes,
    resolved_format: str,
    games_count: int,
) -> None:
    """Write serialized content to file or standard output."""
    if isinstance(content, bytes):
        byte_size = _write_binary_export(output_path, content)
    else:
        byte_size = _write_text_export(output_path, content)

    if output_path is None:
        return

    panel_msg = (
        f"Format: [bold #fec923]{resolved_format.upper()}[/bold #fec923]\n"
        f"Destination: [bold white]{output_path.resolve()}[/bold white]\n"
        f"File Size: [cyan]{byte_size:,} bytes[/cyan]\n"
        f"Total Games Available: [bold green]{games_count}[/bold green]"
    )
    print_panel(panel_msg, title="[bold #fec923]Export Successful[/bold #fec923]")


@click.command("export")
@click.option(
    "--format",
    "-f",
    "export_format",
    type=click.Choice(["ics", "json", "csv", "html", "pdf"], case_sensitive=False),
    default=None,
    help=(
        "Output serialization format (auto-detected from "
        "--output file extension, defaults to ics)."
    ),
)
@click.option(
    "--output",
    "-o",
    "output_path",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    default=None,
    help="Destination file path (if omitted, writes to standard output).",
)
@click.option(
    "--season",
    default=None,
    help="Optional season filter (e.g., '2026-2027').",
)
@click.option(
    "--opponent",
    default=None,
    help="Filter games by opponent team name substring.",
)
@click.option(
    "--home-only",
    is_flag=True,
    default=False,
    help="Filter games to only home matchups hosted by ECU.",
)
@click.option(
    "--status",
    "status_query",
    default=None,
    help="Filter games by status (e.g., 'scheduled', 'final', 'cancelled').",
)
@click.option(
    "--embed",
    is_flag=True,
    default=False,
    help="Export lightweight embeddable widget HTML view instead of full schedule.",
)
@click.option(
    "--include-past/--future-only",
    default=True,
    help="Include completed/historical fixtures in export (defaults to all games).",
)
@click.option(
    "--db-url",
    envvar="DATABASE_URL",
    default=None,
    help="Database connection URL override (defaults to local SQLite or DATABASE_URL).",
)
def export_command(  # noqa: PLR0913 # pylint: disable=too-many-arguments,too-many-locals
    *,
    export_format: str | None,
    output_path: Path | None,
    season: str | None,
    opponent: str | None,
    home_only: bool,
    status_query: str | None,
    embed: bool,
    include_past: bool,
    db_url: str | None,
) -> None:
    """Export schedule to RFC 5545 iCalendar (.ics), JSON, CSV, HTML, or PDF file."""
    resolved_format = _detect_format(export_format, output_path, embed=embed)

    db_url_resolved = get_sync_database_url(db_url)
    engine = create_sync_engine(db_url_resolved)
    try:
        Base.metadata.create_all(engine)
        with get_sync_session(engine) as session:
            games = _load_games(session, season=season)
    except Exception as exc:
        print_error(f"Failed to query games from database: {exc}")
        raise click.ClickException(str(exc)) from exc

    content = _serialize_schedule(
        games,
        resolved_format,
        season=season,
        opponent=opponent,
        home_only=home_only,
        status_query=status_query,
        include_past=include_past,
        embed=embed,
    )
    format_label = (
        "HTML (Embed)"
        if (resolved_format == "html" and embed)
        else resolved_format.upper()
    )
    _write_export_output(output_path, content, format_label, len(games))

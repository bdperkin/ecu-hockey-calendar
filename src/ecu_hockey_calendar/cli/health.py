"""Implementation of the 'ecu-hockey health' CLI command.

Inspects and reports system liveness, database connectivity, and data source
scraper operational readiness in local or remote deployment modes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import rich_click as click
from click.exceptions import Exit
from rich.panel import Panel
from rich.text import Text
from sqlalchemy import select

from ecu_hockey_calendar.api.client import RemoteApiClient, RemoteApiError
from ecu_hockey_calendar.api.routes.health import (
    DEFAULT_SCRAPERS,
    _probe_database,
    format_uptime,
)
from ecu_hockey_calendar.cli.console import (
    get_console,
    print_banner,
    print_error,
)
from ecu_hockey_calendar.cli.status import _render_sources_table
from ecu_hockey_calendar.cli.sync import _resolve_remote_credentials
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.engine import (
    create_sync_engine,
    get_sync_database_url,
    get_sync_session,
)
from ecu_hockey_calendar.storage.models import DataSourceModel
from ecu_hockey_calendar.version import __version__

if TYPE_CHECKING:
    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

__all__ = [
    "_fetch_local_sources",
    "_fetch_remote_health",
    "_format_db_badge",
    "_format_health_badge",
    "_format_scrapers_badge",
    "_probe_local_health",
    "_render_health_panel",
    "health_command",
]


def _format_health_badge(status_str: str) -> Text:
    """Format overall health status string with rich styles."""
    norm = status_str.upper()
    if norm == "HEALTHY":
        return Text("HEALTHY", style="bold green")

    if norm == "DEGRADED":
        return Text("DEGRADED", style="bold yellow")

    return Text("UNHEALTHY", style="bold red")


def _format_db_badge(connected: bool, dialect: str) -> Text:
    """Format database connectivity status badge."""
    badge = Text()
    if connected:
        badge.append("Connected", style="bold green")
    else:
        badge.append("Disconnected", style="bold red")

    badge.append(f" ({dialect})")
    return badge


def _format_scrapers_badge(status_str: str) -> Text:
    """Format scrapers operational status badge."""
    if status_str.upper() == "OPERATIONAL":
        return Text("Operational", style="bold green")

    return Text("Degraded", style="bold yellow")


def _render_health_panel(
    health_data: dict[str, Any],
    target_display: str,
    *,
    target_label: str = "Target: ",
) -> Panel:
    """Render overall system health and component status panel."""
    status_str = str(health_data.get("status", "unknown"))
    db_comp = health_data.get("components", {}).get("database", {})
    scrapers_comp = health_data.get("components", {}).get("scrapers", {})

    panel_text = Text()
    panel_text.append(target_label, style="bold")
    panel_text.append(f"{target_display}\n", style="dim")
    panel_text.append("Overall Status: ", style="bold")
    panel_text.append(_format_health_badge(status_str))
    panel_text.append("\n")
    panel_text.append("Service Version: ", style="bold")
    panel_text.append(f"{health_data.get('version', 'unknown')}\n", style="cyan")

    uptime = health_data.get("uptime_seconds")
    if uptime is not None:
        panel_text.append("Uptime: ", style="bold")
        panel_text.append(f"{format_uptime(float(uptime))}\n", style="green")

    panel_text.append("Database Connectivity: ", style="bold")
    db_conn = bool(db_comp.get("connected"))
    db_dialect = str(db_comp.get("dialect", "unknown"))
    panel_text.append(_format_db_badge(db_conn, db_dialect))
    panel_text.append("\n")
    panel_text.append("Scraper Subsystem: ", style="bold")
    panel_text.append(
        _format_scrapers_badge(str(scrapers_comp.get("status", "unknown"))),
    )
    panel_text.append("\n")

    return Panel(
        panel_text,
        title="[bold #fec923]Service Health & Readiness[/bold #fec923]",
        border_style="#592a8a",
    )


def _fetch_local_sources(session: Session) -> list[dict[str, Any]]:
    """Query data source status models from relational database."""
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
            "last_scraped_at": (
                s.last_scraped_at.isoformat() if s.last_scraped_at else None
            ),
        }
        for s in sources
    ]


def _probe_local_health(engine: Engine) -> dict[str, Any]:
    """Inspect local database connectivity and active scraper sources."""
    Base.metadata.create_all(engine)
    db_result = _probe_database(engine)
    with get_sync_session(engine) as session:
        sources = _fetch_local_sources(session)

    is_healthy = bool(db_result.get("connected"))
    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "service": "ecu-hockey-calendar",
        "version": __version__,
        "timestamp": datetime.now(UTC).isoformat(),
        "uptime_seconds": 0.0,
        "components": {
            "database": db_result,
            "scrapers": {
                "status": "operational" if is_healthy else "degraded",
                "sources": sources,
            },
        },
    }


def _fetch_remote_health(api_url: str, token: str | None) -> dict[str, Any]:
    """Fetch health diagnostics dictionary from remote HTTP API."""
    client = RemoteApiClient(api_url, token=token)
    try:
        return client.get_health()
    except RemoteApiError as exc:
        print_error(f"Failed to fetch health diagnostics from remote API: {exc}")
        raise click.ClickException(str(exc)) from exc


@click.command("health")
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
    "--json",
    "-j",
    "as_json",
    is_flag=True,
    default=False,
    help="Output health diagnostics as formatted JSON.",
)
@click.pass_context
def health_command(
    ctx: click.Context | None,
    *,
    db_url: str | None,
    api_url: str | None = None,
    token: str | None = None,
    as_json: bool = False,
) -> None:
    """Inspect service health, database state, and scraper telemetry."""
    console = get_console()
    api_url, token = _resolve_remote_credentials(ctx, api_url, token)

    if api_url:
        target_display = f"Remote API ({api_url})"
        target_label = "Remote API: "
        data = _fetch_remote_health(api_url, token)
    else:
        db_url_resolved = get_sync_database_url(db_url)
        target_display = db_url_resolved
        target_label = "Database URL: "
        engine = create_sync_engine(db_url_resolved)
        try:
            data = _probe_local_health(engine)
        except Exception as exc:
            print_error(f"Failed to query health from database: {exc}")
            raise click.ClickException(str(exc)) from exc

    if as_json:
        console.print_json(data=data)
    else:
        print_banner("SERVICE HEALTH & DIAGNOSTIC READINESS")
        console.print(
            _render_health_panel(data, target_display, target_label=target_label),
        )
        console.print()
        scrapers_comp = data.get("components", {}).get("scrapers", {})
        sources = scrapers_comp.get("sources", [])
        console.print(_render_sources_table(sources))

    if data.get("status") == "unhealthy":
        raise Exit(1)

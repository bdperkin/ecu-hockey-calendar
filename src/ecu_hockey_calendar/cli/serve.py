"""Implementation of the 'ecu-hockey serve' CLI command.

Launches the local FastAPI calendar and REST data service with Uvicorn.
"""

from __future__ import annotations

import os

import click
from rich.panel import Panel
from rich.text import Text

from ecu_hockey_calendar.api.server import run_server
from ecu_hockey_calendar.cli.console import get_console, print_banner


@click.command("serve")
@click.option(
    "--host",
    "-h",
    default="127.0.0.1",
    show_default=True,
    help="Network interface host to bind the server.",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=8000,
    show_default=True,
    help="TCP port number to listen on.",
)
@click.option(
    "--reload/--no-reload",
    default=False,
    show_default=True,
    help="Enable auto-reload on filesystem changes (development mode).",
)
@click.option(
    "--db-url",
    envvar="DATABASE_URL",
    default=None,
    help="Database connection URL override (defaults to local SQLite or DATABASE_URL).",
)
def serve_command(
    host: str,
    port: int,
    reload: bool,
    db_url: str | None,
) -> None:
    """Launch the FastAPI web server locally with Uvicorn."""
    console = get_console()
    print_banner("FASTAPI CALENDAR & DATA API SERVICE")

    if db_url:
        os.environ["DATABASE_URL"] = db_url

    base_url = f"http://{host}:{port}"
    banner_text = Text()
    banner_text.append(
        "Serving ECU Men's Ice Hockey Calendar Service\n\n",
        style="bold #fec923",
    )
    banner_text.append("Endpoints:\n", style="bold white")
    banner_text.append(
        f"  • iCalendar (.ics):   {base_url}/calendar.ics\n",
        style="cyan",
    )
    banner_text.append(
        f"  • Master JSON Feed:   {base_url}/api/schedule.json\n",
        style="cyan",
    )
    banner_text.append(
        f"  • Master CSV Feed:    {base_url}/api/schedule.csv\n",
        style="cyan",
    )
    banner_text.append(f"  • Interactive Docs:   {base_url}/docs\n", style="cyan")
    banner_text.append(
        f"  • Health & Status:    {base_url}/api/v1/sync/status\n\n",
        style="cyan",
    )
    banner_text.append("Press Ctrl+C to stop the server.", style="dim")

    console.print(
        Panel(
            banner_text,
            title=f"[bold #592a8a]Local Server Running at {base_url}[/bold #592a8a]",
            border_style="#592a8a",
            expand=False,
        ),
    )

    run_server(
        host=host,
        port=port,
        reload=reload,
    )

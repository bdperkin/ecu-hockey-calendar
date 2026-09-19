"""Root Click command group and main entry point for the ECU Hockey CLI."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click

from ecu_hockey_calendar.cli.conflicts import conflicts_command
from ecu_hockey_calendar.cli.export import export_command
from ecu_hockey_calendar.cli.health import health_command
from ecu_hockey_calendar.cli.notify import notify_command
from ecu_hockey_calendar.cli.opponent import opponent_group
from ecu_hockey_calendar.cli.scrape import scrape_command
from ecu_hockey_calendar.cli.serve import serve_command
from ecu_hockey_calendar.cli.status import status_command
from ecu_hockey_calendar.cli.sync import sync_command
from ecu_hockey_calendar.version import __version__

if TYPE_CHECKING:
    from collections.abc import Sequence


@click.group(
    name="ecu-hockey",
    help="ECU Men's Ice Hockey calendar synchronization, inspection, and export CLI.",
)
@click.version_option(
    version=__version__,
    package_name="ecu-hockey-calendar",
    prog_name="ecu-hockey",
)
@click.option(
    "--api-url",
    envvar="ECU_HOCKEY_API_URL",
    default=None,
    help="Remote ECU Hockey API base URL (e.g. 'https://ecu-hockey-api.onrender.com').",
)
@click.option(
    "--token",
    envvar="ECU_HOCKEY_ADMIN_TOKEN",
    default=None,
    help="Administrative authentication Bearer token for protected remote endpoints.",
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
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable verbose output and scrape discovery statistics.",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable full HTTP wire tracing and diagnostic inspection.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    *,
    api_url: str | None = None,
    token: str | None = None,
    opponents_config: str | None = None,
    verbose: bool = False,
    debug: bool = False,
) -> None:
    """ECU Men's Ice Hockey calendar synchronization and export CLI."""
    ctx.ensure_object(dict)
    ctx.obj["api_url"] = api_url
    ctx.obj["token"] = token
    ctx.obj["opponents_config"] = opponents_config
    ctx.obj["verbose"] = verbose
    ctx.obj["debug"] = debug


# Register subcommands
cli.add_command(sync_command, "sync")
cli.add_command(scrape_command, "scrape")
cli.add_command(scrape_command, "crawl")
cli.add_command(status_command, "status")
cli.add_command(health_command, "health")
cli.add_command(export_command, "export")
cli.add_command(conflicts_command, "conflicts")
cli.add_command(serve_command, "serve")
cli.add_command(notify_command, "notify")
cli.add_command(opponent_group, "opponent")


def _handle_exit(exc: Exception | SystemExit) -> int:
    """Handle Click and SystemExit exceptions and extract status code."""
    if isinstance(exc, click.ClickException):
        exc.show()
        return exc.exit_code

    if isinstance(exc, click.exceptions.Exit):
        return exc.exit_code

    code = getattr(exc, "code", 0)
    return int(code) if code is not None else 0


def main(args: Sequence[str] | None = None) -> int:
    """Execute the ECU Hockey CLI entry point.

    Args:
        args: Optional command-line argument list (defaults to sys.argv[1:]).

    Returns:
        Process exit code integer.
    """
    cmd_args = list(args) if args is not None else None
    exit_code = 0
    try:
        cli.main(
            args=cmd_args,
            prog_name="ecu-hockey",
            standalone_mode=False,
        )
    except (click.ClickException, click.exceptions.Exit, SystemExit) as exc:
        exit_code = _handle_exit(exc)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())

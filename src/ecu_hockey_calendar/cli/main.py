"""Root Click command group and main entry point for the ECU Hockey CLI."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click

from ecu_hockey_calendar.cli.conflicts import conflicts_command
from ecu_hockey_calendar.cli.export import export_command
from ecu_hockey_calendar.cli.serve import serve_command
from ecu_hockey_calendar.cli.status import status_command
from ecu_hockey_calendar.cli.sync import sync_command

if TYPE_CHECKING:
    from collections.abc import Sequence


@click.group(
    name="ecu-hockey",
    help="ECU Men's Ice Hockey calendar synchronization, inspection, and export CLI.",
)
@click.version_option(package_name="ecu-hockey-calendar", prog_name="ecu-hockey")
def cli() -> None:
    """ECU Men's Ice Hockey calendar synchronization and export CLI."""


# Register subcommands
cli.add_command(sync_command, "sync")
cli.add_command(status_command, "status")
cli.add_command(export_command, "export")
cli.add_command(conflicts_command, "conflicts")
cli.add_command(serve_command, "serve")


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

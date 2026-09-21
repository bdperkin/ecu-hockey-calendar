"""Terminal styling and output utilities for the ECU Hockey CLI.

This module provides a configured Rich Console, reusable table formatting helpers,
and color-coded status badges for terminal output.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import rich_click as click
from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from collections.abc import Sequence

# Primary application console singleton
console = Console()
error_console = Console(stderr=True)

ECU_PURPLE = "#592a8a"
ECU_GOLD = "#fec923"


def get_console() -> Console:
    """Return the active standard output console.

    Returns:
        Rich Console instance.
    """
    return console


def print_banner(
    title: str,
    subtitle: str | None = None,
    *,
    custom_console: Console | None = None,
) -> None:
    """Display a stylized header banner.

    Args:
        title: Main banner title text.
        subtitle: Optional subtitle or description.
        custom_console: Optional console target override.
    """
    target = custom_console or console
    banner_text = Text()
    banner_text.append("ECU MEN'S ICE HOCKEY\n", style="bold #592a8a")
    banner_text.append(title, style="bold #fec923")
    if subtitle:
        banner_text.append(f"\n{subtitle}", style="dim")

    target.print(Panel(banner_text, border_style="#592a8a", expand=False))


def format_severity_badge(severity: str) -> Text:
    """Return a colorized Rich Text badge for conflict severity levels.

    Args:
        severity: Severity string (e.g., 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW').

    Returns:
        Styled Rich Text badge.
    """
    norm = severity.strip().upper()
    if norm == "CRITICAL":
        return Text("CRITICAL", style="bold red on black")

    if norm == "HIGH":
        return Text("HIGH", style="bold red")

    if norm == "MEDIUM":
        return Text("MEDIUM", style="bold yellow")

    if norm == "LOW":
        return Text("LOW", style="bold cyan")

    return Text(norm, style="dim")


def format_status_badge(status_val: str) -> Text:
    """Return a colorized Rich Text badge for sync and game statuses.

    Args:
        status_val: Status name string.

    Returns:
        Styled Rich Text badge.
    """
    norm = status_val.strip().upper()
    if norm in ("SUCCESS", "FINAL", "CONFIRMED", "ACTIVE"):
        return Text(norm, style="bold green")

    if norm in ("FAILURE", "CANCELLED", "CANCELED", "ERROR"):
        return Text(norm, style="bold red")

    if norm in ("PARTIAL", "POSTPONED", "SYNCING", "IN_PROGRESS"):
        return Text(norm, style="bold yellow")

    if norm in ("SCHEDULED", "IDLE"):
        return Text(norm, style="bold blue")

    return Text(norm, style="dim")


def create_table(
    title: str,
    columns: Sequence[tuple[str, str]],
    *,
    border_style: str = "#592a8a",
) -> Table:
    """Construct a styled Rich Table.

    Args:
        title: Table header title.
        columns: Sequence of (column_name, column_style) tuples.
        border_style: Color or style for table borders.

    Returns:
        Configured Table instance ready for row population.
    """
    table = Table(
        title=title,
        title_style="bold #fec923",
        border_style=border_style,
        header_style="bold white on #592a8a",
        show_lines=True,
    )
    for col_name, col_style in columns:
        table.add_column(col_name, style=col_style)

    return table


def print_success(
    message: str,
    *,
    custom_console: Console | None = None,
) -> None:
    """Print a success message with green checkmark indicator.

    Args:
        message: Informational success message text.
        custom_console: Optional console target override.
    """
    target = custom_console or console
    target.print(f"[bold green]✓[/bold green] {message}")


def print_warning(
    message: str,
    *,
    custom_console: Console | None = None,
) -> None:
    """Print a warning message with yellow alert indicator.

    Args:
        message: Warning message text.
        custom_console: Optional console target override.
    """
    target = custom_console or console
    target.print(f"[bold yellow]![/bold yellow] {message}")


def print_error(
    message: str,
    *,
    custom_console: Console | None = None,
) -> None:
    """Print an error message with red cross indicator to stderr.

    Args:
        message: Error message text.
        custom_console: Optional console target override.
    """
    target = custom_console or error_console
    target.print(f"[bold red]✗[/bold red] {message}")


def print_panel(
    renderable: RenderableType,
    title: str | None = None,
    *,
    border_style: str = "#592a8a",
    custom_console: Console | None = None,
) -> None:
    """Render content inside a Rich Panel.

    Args:
        renderable: Content to display inside panel.
        title: Optional panel title.
        border_style: Border styling string.
        custom_console: Optional console target override.
    """
    target = custom_console or console
    target.print(
        Panel(
            renderable,
            title=title,
            title_align="left",
            border_style=border_style,
            expand=False,
        ),
    )


def _expand_dual_path_groups(
    groups: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Ensure group definitions match both bare command names and prefixed paths.

    Args:
        groups: Mapping of command names or paths to panel definitions.

    Returns:
        Dictionary expanded with 'ecu-hockey ' prefixed command paths.
    """
    expanded: dict[str, list[dict[str, Any]]] = {}
    for key, val in groups.items():
        expanded[key] = val
        if key != "ecu-hockey" and not key.startswith("ecu-hockey "):
            expanded[f"ecu-hockey {key}"] = val

    return expanded


def get_rich_click_command_groups() -> dict[str, list[dict[str, Any]]]:
    """Return command groupings for rich-click help display."""
    base_groups = {
        "ecu-hockey": [
            {
                "name": "Schedule Management & Conflicts",
                "commands": ["status", "conflicts"],
            },
            {
                "name": "Data Ingestion & Pipeline",
                "commands": ["sync", "scrape", "opponent"],
            },
            {
                "name": "Export & Syndication",
                "commands": ["export", "notify"],
            },
            {
                "name": "Services & Diagnostics",
                "commands": ["serve", "health"],
            },
        ],
        "conflicts": [
            {
                "name": "Inspection & Diagnostics",
                "commands": ["list", "get"],
            },
            {
                "name": "Reconciliation & Resolution",
                "commands": ["resolve"],
            },
        ],
        "sync": [
            {
                "name": "Operations",
                "commands": ["trigger", "status"],
            },
        ],
        "opponent": [
            {
                "name": "Opponent Operations",
                "commands": ["discover"],
            },
        ],
    }
    return _expand_dual_path_groups(base_groups)


def _get_root_and_sync_option_groups() -> dict[str, list[dict[str, Any]]]:
    """Return option groups for root, sync, and scrape commands."""
    sync_opts = [
        {
            "name": "Target & Environment Options",
            "options": [
                "--db-url",
                "--api-url",
                "--token",
                "--prod",
                "--method",
            ],
        },
        {
            "name": "Ingestion & Filter Options",
            "options": [
                "--source",
                "--verify-opponents",
                "--season",
                "--opponents-config",
            ],
        },
        {
            "name": "Execution & Notifications",
            "options": [
                "--dry-run",
                "--notify",
                "--notify-individual",
                "--verbose",
                "--debug",
            ],
        },
    ]
    return {
        "ecu-hockey": [
            {
                "name": "Target & Remote API Options",
                "options": ["--api-url", "--token", "--prod"],
            },
            {
                "name": "Configuration & Diagnostics",
                "options": ["--opponents-config", "--verbose", "--debug"],
            },
        ],
        "sync": sync_opts,
        "sync trigger": sync_opts,
        "sync status": [
            {
                "name": "Format & Output",
                "options": ["--json"],
            },
            {
                "name": "Target & Environment Options",
                "options": ["--db-url", "--api-url", "--token", "--prod"],
            },
        ],
        "scrape": [
            {
                "name": "Ingestion Sources & Filters",
                "options": [
                    "--source",
                    "--season",
                    "--subseasons",
                    "--opponents-config",
                    "--save",
                    "--db-url",
                ],
            },
            {
                "name": "Format & Diagnostics",
                "options": ["--json", "--verbose", "--debug"],
            },
        ],
    }


def _get_feature_option_groups() -> dict[str, list[dict[str, Any]]]:
    """Return option groups for status, conflicts, export, and services."""
    conflicts_list_opts = [
        {
            "name": "Filter & Scope Options",
            "options": [
                "--severity",
                "--game-id",
                "--field",
                "--requires-review",
                "--limit",
                "--offset",
            ],
        },
        {
            "name": "Format & Output",
            "options": ["--json"],
        },
        {
            "name": "Target & Environment Options",
            "options": ["--db-url", "--api-url", "--token", "--prod"],
        },
    ]
    return {
        "status": [
            {
                "name": "Filter Options",
                "options": [
                    "--season",
                ],
            },
            {
                "name": "Target & Environment Options",
                "options": ["--db-url", "--api-url", "--token"],
            },
        ],
        "conflicts": conflicts_list_opts,
        "conflicts list": conflicts_list_opts,
        "conflicts get": [
            {
                "name": "Format & Output",
                "options": ["--json"],
            },
            {
                "name": "Target & Environment Options",
                "options": ["--db-url", "--api-url", "--token", "--prod"],
            },
        ],
        "conflicts resolve": [
            {
                "name": "Resolution Strategy & Attributes",
                "options": [
                    "--field",
                    "--value",
                    "--accept-source",
                    "--notes",
                    "--resolved-by",
                ],
            },
            {
                "name": "Target & Environment Options",
                "options": ["--db-url", "--api-url", "--token", "--prod"],
            },
            {
                "name": "Format & Output",
                "options": ["--json"],
            },
        ],
        "export": [
            {
                "name": "Output Destination & Format",
                "options": ["--format", "--output", "--embed"],
            },
            {
                "name": "Data Filters",
                "options": [
                    "--season",
                    "--opponent",
                    "--home-only",
                    "--status",
                    "--include-past",
                ],
            },
            {
                "name": "Environment & Source Options",
                "options": ["--db-url", "--api-url", "--token"],
            },
        ],
        "health": [
            {
                "name": "Format & Output",
                "options": ["--json"],
            },
            {
                "name": "Target Environment Options",
                "options": ["--db-url", "--api-url", "--token", "--prod"],
            },
        ],
        "serve": [
            {
                "name": "Server Binding & Networking",
                "options": ["--host", "--port", "--reload"],
            },
            {
                "name": "Database & Lifecycle",
                "options": ["--db-url", "--migrate"],
            },
        ],
        "notify": [
            {
                "name": "Webhook Targets & Payload",
                "options": [
                    "--discord-webhook",
                    "--slack-webhook",
                    "--telegram-bot-token",
                    "--telegram-chat-id",
                    "--message",
                ],
            },
        ],
        "opponent discover": [
            {
                "name": "Target & Discovery Options",
                "options": [
                    "--append-to",
                    "--max-pages",
                    "--division",
                    "--conference",
                    "--enabled",
                ],
            },
            {
                "name": "Format & Output",
                "options": ["--json"],
            },
        ],
    }


def get_rich_click_option_groups() -> dict[str, list[dict[str, Any]]]:
    """Return consolidated option groups for rich-click help formatting."""
    groups = _get_root_and_sync_option_groups()
    groups.update(_get_feature_option_groups())
    return _expand_dual_path_groups(groups)


def _apply_rich_click_theme() -> None:
    """Apply ECU Hockey branding and formatting rules to rich-click."""
    click.rich_click.TEXT_MARKUP = "markdown"
    click.rich_click.SHOW_ARGUMENTS = True
    click.rich_click.GROUP_ARGUMENTS_OPTIONS = True
    click.rich_click.STYLE_OPTIONS_PANEL_BORDER = ECU_PURPLE
    click.rich_click.STYLE_COMMANDS_PANEL_BORDER = ECU_PURPLE
    click.rich_click.STYLE_ERRORS_PANEL_BORDER = "bold red"
    click.rich_click.ERRORS_PANEL_TITLE = "ECU Hockey CLI Error"
    click.rich_click.STYLE_OPTIONS_TABLE_BOX = "ROUNDED"
    click.rich_click.STYLE_COMMANDS_TABLE_BOX = "ROUNDED"
    click.rich_click.STYLE_ERRORS_PANEL_BOX = "ROUNDED"
    click.rich_click.STYLE_HEADER_TEXT = f"bold {ECU_GOLD}"
    click.rich_click.STYLE_OPTION = f"bold {ECU_GOLD}"
    click.rich_click.STYLE_ARGUMENT = f"bold {ECU_GOLD}"
    click.rich_click.STYLE_COMMAND = f"bold {ECU_GOLD}"
    click.rich_click.STYLE_HELPTEXT_FIRST_LINE = "bold white"
    click.rich_click.STYLE_HELPTEXT = "white"
    click.rich_click.STYLE_USAGE = f"bold {ECU_PURPLE}"
    click.rich_click.STYLE_USAGE_COMMAND = f"bold {ECU_GOLD}"
    click.rich_click.STYLE_METAVAR = "bold cyan"
    click.rich_click.STYLE_OPTION_DEFAULT = "dim"
    click.rich_click.STYLE_OPTION_ENVVAR = "dim italic"
    click.rich_click.COMMAND_GROUPS = cast("Any", get_rich_click_command_groups())
    click.rich_click.OPTION_GROUPS = cast("Any", get_rich_click_option_groups())


def configure_rich_click() -> None:
    """Configure global rich-click formatting, ECU styling, and command groups."""
    _apply_rich_click_theme()


# Initialize rich-click styling on module load
configure_rich_click()

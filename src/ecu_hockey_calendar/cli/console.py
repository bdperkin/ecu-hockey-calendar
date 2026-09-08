"""Terminal styling and output utilities for the ECU Hockey CLI.

This module provides a configured Rich Console, reusable table formatting helpers,
and color-coded status badges for terminal output.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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

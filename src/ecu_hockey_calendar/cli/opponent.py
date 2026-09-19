"""Implementation of the 'ecu-hockey opponent' CLI commands.

Provides discovery and auto-detection tools to spider opponent websites and
generate schedule feed configuration entries.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import click
import httpx
from rich.panel import Panel
from rich.syntax import Syntax

from ecu_hockey_calendar.cli.console import (
    create_table,
    format_severity_badge,
    get_console,
    print_banner,
    print_error,
    print_success,
)
from ecu_hockey_calendar.ingestion.opponent_config import OpponentConfigError
from ecu_hockey_calendar.ingestion.opponent_discovery import (
    DiscoveredOpponent,
    OpponentDiscoverySpider,
    append_opponent_to_yaml_file,
)

if TYPE_CHECKING:
    from rich.table import Table


def _format_aliases_display(aliases: tuple[str, ...]) -> str:
    """Format tuple of aliases into clean display string."""
    return ", ".join(aliases) if aliases else "(none)"


def _build_detection_table(discovered: DiscoveredOpponent) -> Table:
    """Build a Rich table displaying discovered configuration attributes."""
    table = create_table(
        f"Discovered Opponent: {discovered.canonical_name}",
        [
            ("Attribute", "bold cyan"),
            ("Detected Value", "white"),
            ("Confidence", "bold"),
        ],
    )
    conf = discovered.confidence_scores

    fields: list[tuple[str, str, str]] = [
        (
            "Canonical Name",
            discovered.canonical_name,
            conf.get("canonical_name", "LOW"),
        ),
        (
            "Feed URL",
            discovered.feed_url,
            conf.get("feed_url", "LOW"),
        ),
        (
            "Feed Type",
            discovered.feed_type.value,
            conf.get("feed_type", "LOW"),
        ),
        (
            "Home Venue",
            discovered.home_venue,
            conf.get("home_venue", "LOW"),
        ),
        (
            "Website",
            discovered.website or "None",
            conf.get("website", "HIGH"),
        ),
        (
            "Aliases",
            _format_aliases_display(discovered.aliases),
            conf.get("aliases", "LOW"),
        ),
        ("Division", discovered.division, "HIGH"),
        ("Conference", discovered.conference, "HIGH"),
        ("Enabled", str(discovered.enabled), "HIGH"),
    ]

    for label, val, confidence in fields:
        table.add_row(label, val, format_severity_badge(confidence))

    return table


def _render_interactive_discovery(
    discovered: DiscoveredOpponent,
    base_url: str,
) -> None:
    """Render interactive Rich discovery summary, table, and YAML snippet."""
    out = get_console()
    print_banner("OPPONENT DISCOVERY", f"Spider target: {base_url}")

    table = _build_detection_table(discovered)
    out.print(table)
    out.print()

    page_count = len(discovered.pages_crawled)
    out.print(
        f"[dim]Spidered [bold]{page_count}[/] page(s) within "
        f"[cyan]{discovered.website}[/].[/dim]\n",
    )

    yaml_text = discovered.to_yaml_snippet()
    syntax = Syntax(yaml_text, "yaml", theme="monokai", line_numbers=False)
    panel = Panel(
        syntax,
        title="[bold #fec923]Candidate opponents.yaml Entry[/]",
        subtitle="[dim]Copy and paste into your opponents.yaml file[/]",
        border_style="#592a8a",
    )
    out.print(panel)


def _handle_append_target(
    filepath: Path,
    discovered: DiscoveredOpponent,
) -> None:
    """Append candidate configuration to specified target file."""
    try:
        append_opponent_to_yaml_file(filepath, discovered)
        print_success(
            f"Successfully appended '{discovered.canonical_name}' to {filepath}",
        )
    except (OpponentConfigError, OSError) as exc:
        print_error(f"Failed to append configuration: {exc}")
        raise click.ClickException(str(exc)) from exc


async def _run_spider(
    base_url: str,
    max_pages: int,
    division: str,
    conference: str,
    *,
    enabled: bool,
) -> DiscoveredOpponent:
    """Execute spider discovery traversal asynchronously."""
    spider = OpponentDiscoverySpider(max_pages=max_pages)
    return await spider.discover(
        base_url,
        division=division,
        conference=conference,
        enabled=enabled,
    )


def _handle_discovery_error(exc: Exception, *, as_json: bool) -> NoReturn:
    """Output discovery failure in requested format and abort."""
    if as_json:
        click.echo(json.dumps({"error": str(exc)}, indent=2))
        raise SystemExit(1)

    print_error(f"Discovery failed: {exc}")
    raise click.ClickException(str(exc)) from exc


def _present_discovery_result(
    discovered: DiscoveredOpponent,
    base_url: str,
    *,
    as_json: bool,
    append_to: Path | None,
) -> None:
    """Output discovered opponent results in JSON or interactive format."""
    if as_json:
        click.echo(json.dumps(discovered.to_dict(), indent=2))
    else:
        _render_interactive_discovery(discovered, base_url)

    if append_to is not None:
        _handle_append_target(append_to, discovered)


@click.group(
    name="opponent",
    help="Opponent team inspection, configuration, and website discovery.",
)
def opponent_group() -> None:
    """Opponent team inspection and discovery commands."""


@opponent_group.command(
    name="discover",
    help="Spider an opponent website to auto-detect schedule configuration.",
)
@click.argument("base_url")
@click.option(
    "--append-to",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    default=None,
    help="Append candidate configuration to an existing YAML file.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output candidate configuration as JSON for automated pipelines.",
)
@click.option(
    "--max-pages",
    default=10,
    show_default=True,
    type=click.IntRange(min=1, max=50),
    help="Maximum number of website pages to spider within target domain.",
)
@click.option(
    "--division",
    default="ACHA M2",
    show_default=True,
    help="League division for the discovered opponent.",
)
@click.option(
    "--conference",
    default="ACCHL",
    show_default=True,
    help="Conference for the discovered opponent.",
)
@click.option(
    "--enabled/--disabled",
    default=True,
    show_default=True,
    help="Enable or disable the opponent entry in generated configuration.",
)
def discover_command(  # pylint: disable=too-many-arguments
    base_url: str,
    *,
    append_to: Path | None = None,
    as_json: bool = False,
    max_pages: int = 10,
    division: str = "ACHA M2",
    conference: str = "ACCHL",
    enabled: bool = True,
) -> None:
    """Spider an opponent website and auto-detect schedule configuration."""
    if not base_url.strip():
        msg = "Base URL cannot be empty."
        raise click.UsageError(msg)

    try:
        discovered = asyncio.run(
            _run_spider(
                base_url,
                max_pages,
                division,
                conference,
                enabled=enabled,
            ),
        )
    except (
        httpx.HTTPError,
        OSError,
        ValueError,
        RuntimeError,
        click.ClickException,
    ) as exc:
        _handle_discovery_error(exc, as_json=as_json)

    _present_discovery_result(
        discovered,
        base_url,
        as_json=as_json,
        append_to=append_to,
    )

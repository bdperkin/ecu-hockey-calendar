"""Implementation of the 'ecu-hockey scrape' (and 'crawl') CLI command.

Directly runs schedule ingestion scrapers and crawlers with configurable output
verbosity, live telemetry, and debugging inspection.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

import click
from rich.console import Console

from ecu_hockey_calendar.cli.console import (
    create_table,
    format_status_badge,
    get_console,
    print_banner,
    print_error,
    print_success,
    print_warning,
)
from ecu_hockey_calendar.ingestion.acchockey_crawler import ACCHockeyCrawler
from ecu_hockey_calendar.ingestion.client import ResilientHttpClient
from ecu_hockey_calendar.ingestion.ecuhockey_crawler import ECUHockeyCrawler
from ecu_hockey_calendar.ingestion.instagram_crawler import InstagramCrawler
from ecu_hockey_calendar.ingestion.opponent_crawler import (
    OpponentCrawler,
    get_default_opponent_directory,
)
from ecu_hockey_calendar.ingestion.telemetry import (
    ConsoleScrapeObserver,
    ScrapeObserver,
)
from ecu_hockey_calendar.ingestion.tickets_crawler import TicketsCrawler
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.engine import (
    create_sync_engine,
    get_sync_database_url,
    get_sync_session,
)

if TYPE_CHECKING:
    from rich.table import Table
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

    from ecu_hockey_calendar.ingestion.html_parser import ParsedGameRecord

__all__ = [
    "ScrapeResult",
    "_execute_scrapes",
    "_json_sanitize",
    "_render_scrape_summary",
    "_run_scraper_pipeline",
    "_serialize_record",
    "scrape_command",
]


class ScrapeResult:
    """Telemetry and extracted records for a scraped source."""

    def __init__(
        self,
        source_code: str,
        name: str,
        status: str,
        records: list[Any],
        duration: float,
        *,
        error_message: str | None = None,
    ) -> None:
        """Initialize scraper source execution result.

        Args:
            source_code: Canonical identifier code of the data source.
            name: Human-readable name of the source.
            status: Status string (e.g. 'SUCCESS', 'EMPTY', 'ERROR').
            records: Collection of parsed record objects.
            duration: Elapsed execution time in seconds.
            error_message: Optional error message string if failed.
        """
        self.source_code = source_code
        self.name = name
        self.status = status
        self.records = records
        self.duration = duration
        self.error_message = error_message

    def to_dict(self) -> dict[str, Any]:
        """Convert result metadata to serializable dictionary."""
        return {
            "source_code": self.source_code,
            "name": self.name,
            "status": self.status,
            "record_count": len(self.records),
            "duration": self.duration,
            "error_message": self.error_message,
        }


def _sanitize_container(
    data: dict[str, object] | list[object] | tuple[object, ...],
) -> object:
    """Recursively sanitize container elements."""
    if isinstance(data, dict):
        return {k: _json_sanitize(v) for k, v in data.items()}

    return [_json_sanitize(item) for item in data]


def _json_sanitize(data: object) -> object:
    """Recursively convert datetimes, enums, and objects to JSON-safe primitives."""
    if isinstance(data, (dict, list, tuple)):
        return _sanitize_container(data)

    if isinstance(data, datetime):
        return data.isoformat()

    if isinstance(data, Enum):
        return data.value

    return data


def _is_object_dataclass(val: object) -> bool:
    """Check if value is a dataclass instance."""
    return is_dataclass(val) and not isinstance(val, type)


def _serialize_record(record: object) -> object:
    """Serialize a parsed game, post, or fixture record to JSON-compatible data."""
    if hasattr(record, "to_dict") and callable(record.to_dict):
        return _json_sanitize(record.to_dict())

    if _is_object_dataclass(record):
        return _json_sanitize(asdict(cast("Any", record)))

    if isinstance(record, dict):
        return _json_sanitize(record)

    return str(record)


async def _scrape_ecuhockey(
    observer: ScrapeObserver | None = None,
) -> ScrapeResult:
    """Execute ECU Hockey official schedule crawler."""
    t0 = datetime.now(UTC)
    crawler = ECUHockeyCrawler(observer=observer)
    try:
        records, _, _, _ = await crawler.crawl()
        dur = (datetime.now(UTC) - t0).total_seconds()
        status = "SUCCESS" if records else "EMPTY"
        return ScrapeResult("ecuhockey", "ECU Hockey Official", status, records, dur)
    except Exception as exc:  # pylint: disable=broad-except # noqa: BLE001
        dur = (datetime.now(UTC) - t0).total_seconds()
        return ScrapeResult(
            "ecuhockey",
            "ECU Hockey Official",
            "ERROR",
            [],
            dur,
            error_message=str(exc),
        )


async def _crawl_acchockey_subseasons(
    crawler: ACCHockeyCrawler,
    subseasons: str,
) -> list[ParsedGameRecord]:
    """Crawl fixtures across explicitly specified ACCHL subseasons."""
    subseason_list = [s.strip() for s in subseasons.split(",") if s.strip()]
    all_records: list[ParsedGameRecord] = []
    for sub_id in subseason_list:
        if sub_id.startswith(("http://", "https://")):
            target_url = sub_id
        else:
            target_url = (
                "https://www.acchockey.com/schedule/team_instance/"
                f"10282704?subseason={sub_id}"
            )

        sub_records, _, _, _ = await crawler.crawl(url=target_url)
        all_records.extend(sub_records)

    return all_records


async def _scrape_acchockey(
    observer: ScrapeObserver | None = None,
    subseasons: str | None = None,
) -> ScrapeResult:
    """Execute ACC Hockey League crawler with optional subseason fixtures."""
    t0 = datetime.now(UTC)
    crawler = ACCHockeyCrawler(observer=observer)
    try:
        if subseasons:
            all_records = await _crawl_acchockey_subseasons(crawler, subseasons)
        else:
            records, _, _, _ = await crawler.crawl()
            all_records = records

        dur = (datetime.now(UTC) - t0).total_seconds()
        status = "SUCCESS" if all_records else "EMPTY"
        return ScrapeResult("acchockey", "ACC Hockey League", status, all_records, dur)
    except Exception as exc:  # pylint: disable=broad-except # noqa: BLE001
        dur = (datetime.now(UTC) - t0).total_seconds()
        return ScrapeResult(
            "acchockey",
            "ACC Hockey League",
            "ERROR",
            [],
            dur,
            error_message=str(exc),
        )


async def _scrape_instagram(
    observer: ScrapeObserver | None = None,
    season: str = "2026-2027",
) -> ScrapeResult:
    """Execute ECU Hockey Instagram announcements crawler."""
    del season
    t0 = datetime.now(UTC)
    client = ResilientHttpClient(observer=observer)
    crawler = InstagramCrawler(http_client=client)
    try:
        posts, _, _, _ = await crawler.fetch_posts()
        dur = (datetime.now(UTC) - t0).total_seconds()
        status = "SUCCESS" if posts else "EMPTY"
        return ScrapeResult("instagram", "ECU Hockey Instagram", status, posts, dur)
    except Exception as exc:  # pylint: disable=broad-except # noqa: BLE001
        dur = (datetime.now(UTC) - t0).total_seconds()
        return ScrapeResult(
            "instagram",
            "ECU Hockey Instagram",
            "ERROR",
            [],
            dur,
            error_message=str(exc),
        )


async def _scrape_opponent(
    observer: ScrapeObserver | None = None,
) -> ScrapeResult:
    """Execute Opponent Schedule Feeds crawler across registered endpoints."""
    t0 = datetime.now(UTC)
    dir_inst = get_default_opponent_directory()
    client = ResilientHttpClient(observer=observer)
    crawler = OpponentCrawler(http_client=client, directory=dir_inst)
    all_fixtures: list[Any] = []
    try:
        for config in dir_inst.list_endpoints():
            fixtures, _, _, _ = await crawler.fetch_opponent_schedule(
                config.canonical_name,
                use_cache=False,
            )
            all_fixtures.extend(fixtures)

        dur = (datetime.now(UTC) - t0).total_seconds()
        status = "SUCCESS" if all_fixtures else "EMPTY"
        return ScrapeResult(
            "opponent",
            "Opponent Schedule Feeds",
            status,
            all_fixtures,
            dur,
        )
    except Exception as exc:  # pylint: disable=broad-except # noqa: BLE001
        dur = (datetime.now(UTC) - t0).total_seconds()
        return ScrapeResult(
            "opponent",
            "Opponent Schedule Feeds",
            "ERROR",
            [],
            dur,
            error_message=str(exc),
        )


async def _scrape_tickets(
    observer: ScrapeObserver | None = None,
    season: str = "2026-2027",
) -> ScrapeResult:
    """Execute ECU Hockey ticketing listings crawler."""
    t0 = datetime.now(UTC)
    client = ResilientHttpClient(observer=observer)
    crawler = TicketsCrawler(http_client=client)
    try:
        records, _, _, _ = await crawler.crawl(season=season)
        dur = (datetime.now(UTC) - t0).total_seconds()
        status = "SUCCESS" if records else "EMPTY"
        return ScrapeResult("tickets", "ECU Hockey Tickets", status, records, dur)
    except Exception as exc:  # pylint: disable=broad-except # noqa: BLE001
        dur = (datetime.now(UTC) - t0).total_seconds()
        return ScrapeResult(
            "tickets",
            "ECU Hockey Tickets",
            "ERROR",
            [],
            dur,
            error_message=str(exc),
        )


async def _execute_primary_scrapes(
    target: str,
    observer: ScrapeObserver | None,
    subseasons: str | None,
) -> list[ScrapeResult]:
    """Execute ECU Hockey and ACC Hockey schedule crawlers."""
    res: list[ScrapeResult] = []
    if target in {"all", "ecuhockey"}:
        res.append(await _scrape_ecuhockey(observer=observer))

    if target in {"all", "acchockey"}:
        res.append(await _scrape_acchockey(observer=observer, subseasons=subseasons))

    return res


async def _execute_secondary_scrapes(
    target: str,
    observer: ScrapeObserver | None,
    season: str,
) -> list[ScrapeResult]:
    """Execute Instagram, ticketing, and opponent feed scrapers."""
    res: list[ScrapeResult] = []
    if target in {"all", "instagram", "social"}:
        res.append(await _scrape_instagram(observer=observer, season=season))

    if target in {"all", "tickets"}:
        res.append(await _scrape_tickets(observer=observer, season=season))

    if target == "opponent":
        res.append(await _scrape_opponent(observer=observer))

    return res


async def _execute_scrapes(
    source_code: str,
    *,
    observer: ScrapeObserver | None = None,
    subseasons: str | None = None,
    season: str | None = None,
) -> list[ScrapeResult]:
    """Execute target scrapers according to source code filter."""
    target = source_code.lower()
    season_val = season or "2026-2027"
    primary = await _execute_primary_scrapes(target, observer, subseasons)
    secondary = await _execute_secondary_scrapes(target, observer, season_val)
    return primary + secondary


def _persist_primary_source(session: Session, res: ScrapeResult) -> bool:
    """Persist primary league or official schedule fixtures."""
    if res.source_code == "ecuhockey":
        asyncio.run(ECUHockeyCrawler().crawl_and_sync(session))
        return True

    if res.source_code == "acchockey":
        asyncio.run(ACCHockeyCrawler().crawl_and_sync(session))
        return True

    return False


def _persist_single_source(
    session: Session,
    res: ScrapeResult,
    season: str,
) -> None:
    """Persist fixtures for a single recognized scraper source."""
    if _persist_primary_source(session, res):
        return

    if res.source_code == "tickets":
        asyncio.run(TicketsCrawler().crawl_and_sync(session, season=season))
    elif res.source_code == "instagram":
        asyncio.run(InstagramCrawler().sync(session, season=season))
    elif res.source_code == "opponent":
        asyncio.run(OpponentCrawler().sync(session, season=season))


def _persist_scraped_results(
    engine: Engine,
    results: list[ScrapeResult],
    season: str | None = None,
) -> None:
    """Persist scraped results into the database when --save is enabled."""
    Base.metadata.create_all(engine)
    season_val = season or "2026-2027"

    with get_sync_session(engine) as session:
        for res in results:
            if res.status == "SUCCESS" and res.records:
                _persist_single_source(session, res, season_val)


def _build_summary_table(results: list[ScrapeResult]) -> tuple[Table, int, float]:
    """Construct Rich table displaying scraper metrics."""
    table = create_table(
        "Scraper Execution Summary",
        [
            ("Source", "bold cyan"),
            ("Records Extracted", "bold"),
            ("Status", "bold"),
            ("Elapsed Time", "dim"),
        ],
    )
    total_records = 0
    total_duration = 0.0
    for res in results:
        total_records += len(res.records)
        total_duration += res.duration
        table.add_row(
            res.name,
            str(len(res.records)),
            format_status_badge(res.status),
            f"{res.duration:.2f}s",
        )

    return table, total_records, total_duration


def _print_error_messages(results: list[ScrapeResult]) -> list[ScrapeResult]:
    """Print formatted error messages for failed scrapers."""
    errors = [res for res in results if res.status == "ERROR" and res.error_message]
    for err in errors:
        print_error(f"[{err.name}] Scraper error: {err.error_message}")

    return errors


def _render_scrape_summary(
    results: list[ScrapeResult],
    console: Console,
) -> None:
    """Render Rich summary table with scraper execution metrics."""
    table, total_records, total_duration = _build_summary_table(results)
    console.print(table)
    console.print()

    errors = _print_error_messages(results)
    msg = (
        f"Scraped {total_records} record(s) across {len(results)} "
        f"source(s) in {total_duration:.2f}s."
    )
    if errors:
        print_warning(msg)
    else:
        print_success(msg)


def _init_scrape_observer(
    verbose: bool,
    debug: bool,
    console: Console,
) -> ScrapeObserver | None:
    """Construct ConsoleScrapeObserver when verbose or debug is active."""
    if verbose or debug:
        return ConsoleScrapeObserver(console=console, verbose=verbose, debug=debug)

    return None


def _print_scraper_banner(
    console: Console,
    debug: bool,
    verbose: bool,
    source_code: str,
    save: bool,
) -> None:
    """Print scraper execution banner and configuration parameters."""
    print_banner("SCHEDULE INGESTION SCRAPER")
    if debug:
        mode_label = "[bold red]DEBUG[/bold red]"
    elif verbose:
        mode_label = "[bold yellow]VERBOSE[/bold yellow]"
    else:
        mode_label = "[dim]MINIMAL[/dim]"

    console.print(
        f"Mode: {mode_label} | "
        f"Source: [bold cyan]{source_code}[/bold cyan] | "
        f"Save: [dim]{save}[/dim]\n",
    )


def _format_json_payload(results: list[ScrapeResult]) -> str:
    """Format scrape results dictionary into formatted JSON string."""
    payload = {
        "sources": [r.to_dict() for r in results],
        "total_records": sum(len(r.records) for r in results),
        "records": {
            r.source_code: [_serialize_record(rec) for rec in r.records]
            for r in results
        },
    }
    return json.dumps(payload, indent=2)


def _save_scraped_data(
    results: list[ScrapeResult],
    db_url: str | None,
    season: str | None,
    as_json: bool,
) -> None:
    """Save scraped results to relational database storage."""
    db_resolved = get_sync_database_url(db_url)
    engine = create_sync_engine(db_resolved)
    _persist_scraped_results(engine, results, season=season)
    if not as_json:
        print_success(f"Persisted scraped fixtures to database ({db_resolved}).")


def _run_scraper_pipeline(  # pylint: disable=too-many-arguments
    *,
    source_code: str,
    verbose: bool,
    debug: bool,
    subseasons: str | None,
    season: str | None,
    as_json: bool,
    save: bool,
    db_url: str | None,
) -> None:
    """Execute scraping pipeline with configured observer and output formatter."""
    out_console = get_console()
    telemetry_console = Console(stderr=True) if as_json else out_console
    observer = _init_scrape_observer(verbose, debug, telemetry_console)

    if not as_json:
        _print_scraper_banner(out_console, debug, verbose, source_code, save)

    results = asyncio.run(
        _execute_scrapes(
            source_code,
            observer=observer,
            subseasons=subseasons,
            season=season,
        ),
    )

    if save:
        _save_scraped_data(results, db_url, season, as_json)

    if as_json:
        click.echo(_format_json_payload(results))
    else:
        _render_scrape_summary(results, out_console)


def _get_context_obj(ctx: click.Context | None) -> dict[str, Any]:
    """Extract dict object from Click context if present."""
    if ctx and isinstance(ctx.obj, dict):
        return ctx.obj

    return {}


def _resolve_scrape_cli_flags(
    ctx: click.Context | None,
    verbose: bool,
    debug: bool,
    db_url: str | None,
) -> tuple[bool, bool, str | None]:
    """Resolve verbose, debug, and db_url overrides from CLI and context."""
    obj = _get_context_obj(ctx)
    db_val = db_url or obj.get("db_url")
    resolved_db = str(db_val) if db_val else None
    return (
        verbose or bool(obj.get("verbose")),
        debug or bool(obj.get("debug")),
        resolved_db,
    )


@click.command(
    "scrape",
    help="Directly run schedule scrapers and crawlers with live telemetry.",
)
@click.option(
    "--source",
    "-s",
    "source_code",
    type=click.Choice(
        ["all", "ecuhockey", "acchockey", "instagram", "opponent", "tickets", "social"],
        case_sensitive=False,
    ),
    default="all",
    show_default=True,
    help="Target scraper or crawler to execute.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="List URLs being scraped and discovery statistics.",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Display all HTTP wire requests, responses, headers, and body snippets.",
)
@click.option(
    "--subseasons",
    default=None,
    help="Comma-separated subseason IDs or URLs for league crawlers.",
)
@click.option(
    "--season",
    default=None,
    help="Collegiate hockey athletic season (e.g., '2026-2027').",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output extracted fixtures as formatted JSON to stdout.",
)
@click.option(
    "--save/--no-save",
    is_flag=True,
    default=False,
    help="Persist raw snapshots and fixtures into relational storage.",
)
@click.option(
    "--db-url",
    envvar="DATABASE_URL",
    default=None,
    help="Database connection URL override when --save is enabled.",
)
@click.pass_context
def scrape_command(  # noqa: PLR0913 # pylint: disable=too-many-arguments
    ctx: click.Context | None,
    *,
    source_code: str = "all",
    verbose: bool = False,
    debug: bool = False,
    subseasons: str | None = None,
    season: str | None = None,
    as_json: bool = False,
    save: bool = False,
    db_url: str | None = None,
) -> None:
    """Directly execute schedule scrapers with live telemetry."""
    is_verbose, is_debug, resolved_db_url = _resolve_scrape_cli_flags(
        ctx,
        verbose,
        debug,
        db_url,
    )
    _run_scraper_pipeline(
        source_code=source_code,
        verbose=is_verbose,
        debug=is_debug,
        subseasons=subseasons,
        season=season,
        as_json=as_json,
        save=save,
        db_url=resolved_db_url,
    )

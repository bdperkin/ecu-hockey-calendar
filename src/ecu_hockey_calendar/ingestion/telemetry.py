"""Ingestion scraper telemetry, event models, and observer interfaces.

Supports multi-tiered output granularity (minimal, verbose, debug) for scraper
and synchronization workflows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from rich.console import Console

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass
class ScrapeEvent:
    """Telemetry event recording individual URL scraping activity and findings.

    Attributes:
        url: The web URL or API endpoint scraped.
        status_code: HTTP response status code.
        records_found: Number of fixture or game records extracted.
        sublinks_found: Number of pagination or subseason links discovered.
        details: Optional contextual description (e.g. season or feed name).
        source_code: Short code identifier for the scraper source.
    """

    url: str
    status_code: int = 200
    records_found: int = 0
    sublinks_found: int = 0
    details: str = ""
    source_code: str = ""


@dataclass
class HttpWireEvent:
    """Wire-level telemetry event capturing detailed HTTP request/response metrics.

    Attributes:
        method: HTTP request method (e.g. 'GET', 'POST').
        url: Target HTTP URL.
        status_code: HTTP response status code, or None if connection failed.
        duration_ms: Round-trip request latency in milliseconds.
        request_headers: Outgoing request headers.
        response_headers: Incoming response headers.
        request_body: Serialized request body payload, if applicable.
        response_body_snippet: Truncated excerpt of the response content body.
        response_size_bytes: Size of response payload in bytes.
        attempt: Zero-based or one-based retry attempt number.
        is_error: True if request resulted in an exception or retryable error.
        error_message: Optional error message string describing connection failure.
    """

    method: str
    url: str
    status_code: int | None = None
    duration_ms: float = 0.0
    request_headers: Mapping[str, str] = field(default_factory=dict)
    response_headers: Mapping[str, str] = field(default_factory=dict)
    request_body: str | None = None
    response_body_snippet: str | None = None
    response_size_bytes: int = 0
    attempt: int = 1
    is_error: bool = False
    error_message: str | None = None


@runtime_checkable
class ScrapeObserver(Protocol):
    """Protocol defining callback interfaces for scraper and HTTP events."""

    def on_scrape(self, event: ScrapeEvent) -> None:
        """Handle higher-level crawler URL scraping and item discovery events."""

    def on_http_request(self, event: HttpWireEvent) -> None:
        """Handle low-level HTTP wire request initiation events."""

    def on_http_response(self, event: HttpWireEvent) -> None:
        """Handle low-level HTTP wire response completion events."""


class NullScrapeObserver:
    """Default no-op observer discarding all telemetry events."""

    def on_scrape(self, event: ScrapeEvent) -> None:
        """Discard scraper discovery event.

        Args:
            event: The ScrapeEvent payload.
        """

    def on_http_request(self, event: HttpWireEvent) -> None:
        """Discard HTTP request event.

        Args:
            event: The HttpWireEvent payload.
        """

    def on_http_response(self, event: HttpWireEvent) -> None:
        """Discard HTTP response event.

        Args:
            event: The HttpWireEvent payload.
        """


def _format_scrape_stats(event: ScrapeEvent) -> str:
    """Format record and sublink counts into summary string."""
    rec_label = "record" if event.records_found == 1 else "records"
    stats_parts: list[str] = [
        f"Status: {event.status_code}",
        f"Found {event.records_found} {rec_label}",
    ]
    if event.sublinks_found:
        sub_label = "sublink" if event.sublinks_found == 1 else "sublinks"
        stats_parts.append(f"{event.sublinks_found} {sub_label}")

    if event.details:
        stats_parts.append(f"({event.details})")

    return " | ".join(stats_parts)


class ConsoleScrapeObserver:
    """Rich console observer streaming scraper discovery and HTTP wire logs.

    Formats output according to verbose and debug granularity configurations.
    """

    def __init__(
        self,
        console: Console | None = None,
        *,
        verbose: bool = False,
        debug: bool = False,
    ) -> None:
        """Initialize console telemetry observer.

        Args:
            console: Optional target Rich Console (defaults to global Console).
            verbose: If True, stream URL scraping and record count statistics.
            debug: If True, stream full wire-level HTTP requests and responses.
        """
        self.console = console or Console()
        self.verbose = verbose or debug
        self.debug = debug

    def on_http_request(self, event: HttpWireEvent) -> None:
        """Format and stream outgoing HTTP request wire logs in debug mode.

        Args:
            event: The HttpWireEvent containing request metadata.
        """
        if not self.debug:
            return

        attempt_suffix = f" (attempt {event.attempt})" if event.attempt > 1 else ""
        self.console.print(
            f"[dim cyan]DEBUG \\[http][/dim cyan] [bold cyan]>[/bold cyan] "
            f"[bold]{event.method}[/bold] {event.url}{attempt_suffix}",
            highlight=False,
        )
        if event.request_headers:
            headers_repr = dict(event.request_headers)
            self.console.print(
                f"[dim cyan]DEBUG \\[http][/dim cyan] [cyan]>[/cyan] "
                f"Headers: [dim]{headers_repr}[/dim]",
                highlight=False,
            )

        if event.request_body:
            self.console.print(
                f"[dim cyan]DEBUG \\[http][/dim cyan] [cyan]>[/cyan] "
                f"Body: [dim]{event.request_body}[/dim]",
                highlight=False,
            )

    def _print_response_error(self, event: HttpWireEvent) -> None:
        """Print formatted error response wire log."""
        err_msg = event.error_message or "Request failed"
        self.console.print(
            f"[dim cyan]DEBUG \\[http][/dim cyan] [bold red]<[/bold red] "
            f"ERROR ({event.duration_ms:.1f}ms): {err_msg}",
            highlight=False,
        )

    def _print_response_success(self, event: HttpWireEvent) -> None:
        """Print formatted successful HTTP wire response with headers and body."""
        status = event.status_code or 0
        status_style = "green" if status < 400 else "yellow"  # noqa: PLR2004
        self.console.print(
            f"[dim cyan]DEBUG \\[http][/dim cyan] "
            f"[bold {status_style}]<[/bold {status_style}] "
            f"[{status_style}]{status}[/{status_style}] "
            f"({event.duration_ms:.1f}ms) {event.url}",
            highlight=False,
        )
        if event.response_headers:
            self.console.print(
                f"[dim cyan]DEBUG \\[http][/dim cyan] [cyan]<[/cyan] "
                f"Headers: [dim]{dict(event.response_headers)}[/dim]",
                highlight=False,
            )

        if event.response_body_snippet:
            self.console.print(
                f"[dim cyan]DEBUG \\[http][/dim cyan] [cyan]<[/cyan] "
                f"Body ({event.response_size_bytes} bytes): "
                f"[dim]{event.response_body_snippet}[/dim]",
                highlight=False,
            )

    def on_http_response(self, event: HttpWireEvent) -> None:
        """Format and stream incoming HTTP response wire logs in debug mode.

        Args:
            event: The HttpWireEvent containing response metadata and timing.
        """
        if not self.debug:
            return

        if event.is_error or event.status_code is None:
            self._print_response_error(event)
            return

        self._print_response_success(event)

    def on_scrape(self, event: ScrapeEvent) -> None:
        """Format and stream high-level URL scraping discovery in verbose mode.

        Args:
            event: The ScrapeEvent containing URL and discovered record counts.
        """
        if not self.verbose:
            return

        stats_summary = _format_scrape_stats(event)
        self.console.print(
            f"[bold #fec923][*][/bold #fec923] [bold]Scraping:[/bold] {event.url}\n"
            f"    [dim]->[/dim] {stats_summary}",
            highlight=False,
        )


__all__ = [
    "ConsoleScrapeObserver",
    "HttpWireEvent",
    "NullScrapeObserver",
    "ScrapeEvent",
    "ScrapeObserver",
]

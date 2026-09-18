"""Tests for ingestion telemetry, observers, and event formatting."""

from __future__ import annotations

import io

from rich.console import Console

from ecu_hockey_calendar.ingestion.telemetry import (
    ConsoleScrapeObserver,
    HttpWireEvent,
    NullScrapeObserver,
    ScrapeEvent,
)


def test_scrape_event_attributes() -> None:
    """Verify ScrapeEvent data class properties and default values."""
    ev = ScrapeEvent(
        url="https://example.com/schedule",
        status_code=200,
        records_found=15,
        sublinks_found=3,
        details="Team schedule",
        source_code="acchockey",
    )
    assert ev.url == "https://example.com/schedule"
    assert ev.status_code == 200
    assert ev.records_found == 15
    assert ev.sublinks_found == 3
    assert ev.details == "Team schedule"
    assert ev.source_code == "acchockey"

    ev_default = ScrapeEvent(url="https://example.com")
    assert ev_default.status_code == 200
    assert ev_default.records_found == 0
    assert ev_default.sublinks_found == 0
    assert ev_default.details == ""
    assert ev_default.source_code == ""


def test_http_wire_event_attributes() -> None:
    """Verify HttpWireEvent properties and defaults."""
    ev = HttpWireEvent(
        method="GET",
        url="https://example.com/api",
        status_code=200,
        duration_ms=45.2,
        request_headers={"Accept": "application/json"},
        response_headers={"Content-Type": "application/json"},
        request_body=None,
        response_body_snippet='{"status": "ok"}',
        response_size_bytes=16,
        attempt=1,
        is_error=False,
        error_message=None,
    )
    assert ev.method == "GET"
    assert ev.url == "https://example.com/api"
    assert ev.status_code == 200
    assert ev.duration_ms == 45.2
    assert ev.request_headers == {"Accept": "application/json"}
    assert ev.response_headers == {"Content-Type": "application/json"}
    assert ev.response_size_bytes == 16
    assert ev.attempt == 1
    assert not ev.is_error
    assert ev.error_message is None

    ev_default = HttpWireEvent(method="POST", url="https://example.com")
    assert ev_default.status_code is None
    assert ev_default.duration_ms == 0.0
    assert ev_default.request_headers == {}
    assert ev_default.response_headers == {}


def test_null_scrape_observer() -> None:
    """Verify NullScrapeObserver safely absorbs all event callbacks."""
    observer = NullScrapeObserver()
    scrape_ev = ScrapeEvent(url="https://example.com")
    wire_ev = HttpWireEvent(method="GET", url="https://example.com")

    # Should execute cleanly without side-effects or errors
    observer.on_scrape(scrape_ev)
    observer.on_http_request(wire_ev)
    observer.on_http_response(wire_ev)


def test_console_scrape_observer_minimal_mode() -> None:
    """Verify ConsoleScrapeObserver emits nothing when verbose and debug are off."""
    buf = io.StringIO()
    console = Console(file=buf, color_system=None)
    observer = ConsoleScrapeObserver(console=console, verbose=False, debug=False)

    scrape_ev = ScrapeEvent(url="https://example.com", records_found=5)
    wire_ev = HttpWireEvent(method="GET", url="https://example.com", status_code=200)

    observer.on_scrape(scrape_ev)
    observer.on_http_request(wire_ev)
    observer.on_http_response(wire_ev)

    output = buf.getvalue()
    assert output == ""


def test_console_scrape_observer_verbose_mode() -> None:
    """Verify ConsoleScrapeObserver outputs scrape events in verbose mode."""
    buf = io.StringIO()
    console = Console(file=buf, color_system=None)
    observer = ConsoleScrapeObserver(console=console, verbose=True, debug=False)

    ev1 = ScrapeEvent(
        url="https://example.com/page1",
        status_code=200,
        records_found=10,
        sublinks_found=2,
        details="Page 1",
    )
    ev2 = ScrapeEvent(
        url="https://example.com/page2",
        status_code=404,
        records_found=0,
    )
    wire_ev = HttpWireEvent(method="GET", url="https://example.com", status_code=200)

    observer.on_scrape(ev1)
    observer.on_scrape(ev2)
    observer.on_http_request(wire_ev)
    observer.on_http_response(wire_ev)

    output = buf.getvalue()
    assert "https://example.com/page1" in output
    assert "10 records" in output
    assert "2 sublinks" in output
    assert "Page 1" in output
    assert "https://example.com/page2" in output
    assert "404" in output
    # Wire events should not be logged in verbose-only mode
    assert "DEBUG [http]" not in output


def test_console_scrape_observer_debug_mode() -> None:
    """Verify ConsoleScrapeObserver outputs HTTP request/response wire traces."""
    buf = io.StringIO()
    console = Console(file=buf, color_system=None, width=200)
    observer = ConsoleScrapeObserver(console=console, verbose=False, debug=True)

    req_ev = HttpWireEvent(
        method="POST",
        url="https://example.com/api/query",
        request_headers={"Content-Type": "application/json", "Authorization": "Secret"},
        request_body='{"query": "games"}',
        attempt=2,
    )
    resp_ev = HttpWireEvent(
        method="POST",
        url="https://example.com/api/query",
        status_code=200,
        duration_ms=125.4,
        response_headers={"Content-Length": "42"},
        response_body_snippet='{"result": [1, 2]}',
        attempt=2,
    )

    observer.on_http_request(req_ev)
    observer.on_http_response(resp_ev)

    output = buf.getvalue()
    assert "DEBUG [http] > POST https://example.com/api/query (attempt 2)" in output
    assert "'Content-Type': 'application/json'" in output
    assert "'Authorization': 'Secret'" in output
    assert '{"query": "games"}' in output
    assert "DEBUG [http] < 200 (125.4ms)" in output
    assert "'Content-Length': '42'" in output
    assert '{"result": [1, 2]}' in output


def test_console_scrape_observer_debug_error_response() -> None:
    """Verify ConsoleScrapeObserver handles HTTP failure wire traces."""
    buf = io.StringIO()
    console = Console(file=buf, color_system=None)
    observer = ConsoleScrapeObserver(console=console, verbose=True, debug=True)

    err_ev = HttpWireEvent(
        method="GET",
        url="https://example.com/broken",
        status_code=500,
        duration_ms=300.0,
        is_error=True,
        error_message="Internal Server Error: Connection reset",
        response_headers={},
    )

    observer.on_http_response(err_ev)

    output = buf.getvalue()
    assert "DEBUG [http] < ERROR (300.0ms)" in output
    assert "Internal Server Error: Connection reset" in output


def test_console_scrape_observer_default_console() -> None:
    """Verify ConsoleScrapeObserver instantiates default Console if not supplied."""
    observer = ConsoleScrapeObserver(verbose=True)
    assert observer.console is not None
    assert observer.verbose is True
    assert observer.debug is False


def test_console_scrape_observer_branches() -> None:
    """Verify ConsoleScrapeObserver coverage across all formatting branches."""
    buf = io.StringIO()
    console = Console(file=buf, color_system=None, width=200)
    observer = ConsoleScrapeObserver(console=console, verbose=True, debug=True)

    # 1. Request with attempt=1, no headers, no body
    req_ev = HttpWireEvent(
        method="GET",
        url="https://example.com/simple",
        attempt=1,
        request_headers={},
        request_body=None,
    )
    observer.on_http_request(req_ev)

    # 2. Response with 404 (status_style=yellow), no headers, no body snippet
    resp_ev = HttpWireEvent(
        method="GET",
        url="https://example.com/simple",
        status_code=404,
        duration_ms=50.0,
        response_headers={},
        response_body_snippet=None,
    )
    observer.on_http_response(resp_ev)

    # 3. Scrape event with no details and no sublinks
    scrape_ev = ScrapeEvent(
        url="https://example.com/simple",
        status_code=200,
        records_found=3,
        sublinks_found=0,
        details="",
    )
    observer.on_scrape(scrape_ev)

    out = buf.getvalue()
    assert "DEBUG [http] > GET https://example.com/simple" in out
    assert "(attempt" not in out
    assert "DEBUG [http] < 404 (50.0ms)" in out
    assert "3 records" in out

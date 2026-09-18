"""Tests for resilient asynchronous HTTP client."""

from __future__ import annotations

import asyncio
import hashlib
from typing import override

import httpx
import pytest

from ecu_hockey_calendar.ingestion.client import (
    ResilientHttpClient,
    _format_body_snippet,
    compute_content_hash,
)
from ecu_hockey_calendar.ingestion.telemetry import HttpWireEvent, ScrapeObserver


def test_compute_content_hash() -> None:
    """Verify SHA-256 calculation on strings and bytes."""
    h1 = compute_content_hash("hello world")
    h2 = compute_content_hash(b"hello world")
    assert h1 == h2
    assert len(h1) == 64
    assert h1 == hashlib.sha256(b"hello world").hexdigest()


def test_client_fetch_text_and_json() -> None:
    """Verify successful GET text and JSON responses with content hashes."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Handle mock requests."""
        if "text-endpoint" in str(request.url):
            return httpx.Response(200, text="<html><body>Schedule</body></html>")

        if "json-endpoint" in str(request.url):
            return httpx.Response(200, json={"status": "ok", "games": [1, 2]})

        return httpx.Response(404, text="Not Found")

    transport = httpx.MockTransport(handler)

    async def _run() -> None:
        """Run async tests."""
        async with ResilientHttpClient(
            transport=transport,
            backoff_factor=0.01,
        ) as client:
            text, text_hash = await client.fetch_text(
                "https://example.com/text-endpoint",
                headers={"X-Custom": "val"},
            )
            assert "<html>" in text
            assert text_hash == compute_content_hash(text)

            json_data, json_hash = await client.fetch_json(
                "https://example.com/json-endpoint",
            )
            assert json_data["status"] == "ok"
            assert json_data["games"] == [1, 2]
            assert json_hash is not None

    asyncio.run(_run())


def test_client_post_json() -> None:
    """Verify successful POST with JSON body."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Echo request body in mock response."""
        return httpx.Response(200, json={"received": request.read().decode("utf-8")})

    transport = httpx.MockTransport(handler)

    async def _run() -> None:
        """Run async post test."""
        client = ResilientHttpClient(transport=transport, backoff_factor=0.01)
        res, post_hash = await client.post_json(
            "https://example.com/api/query",
            json_data={"query": "test"},
        )
        assert "query" in res["received"]
        assert post_hash is not None
        await client.close()

    asyncio.run(_run())


def test_client_retry_and_recovery() -> None:
    """Verify retry logic recovers from transient 503 and 429 status codes."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Fail on first attempt and succeed on second."""
        del request
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="Service Unavailable")

        return httpx.Response(200, text="Recovered")

    transport = httpx.MockTransport(handler)

    async def _run() -> None:
        """Run retry recovery test."""
        async with ResilientHttpClient(
            transport=transport,
            max_retries=2,
            backoff_factor=0.01,
        ) as client:
            text, _ = await client.fetch_text("https://example.com/flaky")
            assert text == "Recovered"
            assert attempts == 2

    asyncio.run(_run())


def test_client_retry_exhaustion_raises_error() -> None:
    """Verify HTTPStatusError is raised after retry attempts are exhausted."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Consistently return 500 error."""
        del request
        return httpx.Response(500, text="Internal Error")

    transport = httpx.MockTransport(handler)

    async def _run() -> None:
        """Run retry failure test."""
        async with ResilientHttpClient(
            transport=transport,
            max_retries=2,
            backoff_factor=0.01,
        ) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await client.fetch_text("https://example.com/error")

    asyncio.run(_run())


def test_client_network_error_retry_and_exhaustion() -> None:
    """Verify network connection errors trigger retry and eventual exception."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Simulate connect error."""
        del request
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("Connection refused")

    transport = httpx.MockTransport(handler)

    async def _run() -> None:
        """Run connect error test."""
        async with ResilientHttpClient(
            transport=transport,
            max_retries=2,
            backoff_factor=0.01,
        ) as client:
            with pytest.raises(httpx.ConnectError):
                await client.fetch_text("https://example.com/network-error")

        assert attempts == 3

    asyncio.run(_run())


def test_client_unexpected_state() -> None:
    """Verify negative retries raises RuntimeError."""
    transport = httpx.MockTransport(lambda _: httpx.Response(200))

    async def _run() -> None:
        """Execute client unexpected state test."""
        client = ResilientHttpClient(transport=transport, max_retries=-1)
        with pytest.raises(RuntimeError, match="Unexpected request failure state"):
            await client.fetch_text("https://example.com")

        await client.close()

    asyncio.run(_run())


def test_client_observer_wire_events() -> None:
    """Verify ResilientHttpClient dispatches wire events to configured observer."""
    requests: list[HttpWireEvent] = []
    responses: list[HttpWireEvent] = []

    class MockObserver(ScrapeObserver):
        """Mock scrape observer capturing wire events."""

        @override
        def on_scrape(self, event: object) -> None:
            """Handle scrape event."""

        @override
        def on_http_request(self, event: HttpWireEvent) -> None:
            """Handle http request event."""
            requests.append(event)

        @override
        def on_http_response(self, event: HttpWireEvent) -> None:
            """Handle http response event."""
            responses.append(event)

    def handler(request: httpx.Request) -> httpx.Response:
        if "fail" in str(request.url):
            raise httpx.ConnectError("Connection dropped")

        return httpx.Response(200, json={"message": "Success response body"})

    transport = httpx.MockTransport(handler)
    obs = MockObserver()

    async def _run() -> None:
        async with ResilientHttpClient(
            transport=transport,
            observer=obs,
            max_retries=1,
            backoff_factor=0.01,
        ) as client:
            await client.fetch_text(
                "https://example.com/ok",
                headers={"Accept": "text/html"},
            )
            assert len(requests) == 1
            assert requests[0].url == "https://example.com/ok"
            assert len(responses) == 1
            assert responses[0].status_code == 200
            assert "Success response body" in str(responses[0].response_body_snippet)

            # Test POST with dict json_data
            await client.post_json(
                "https://example.com/post",
                json_data={"foo": "bar"},
            )
            assert requests[-1].request_body == '{"foo": "bar"}'

            # Test POST with str json_data
            await client.post_json(
                "https://example.com/post-str",
                json_data="plain-str",
            )
            assert requests[-1].request_body == "plain-str"

            with pytest.raises(httpx.ConnectError):
                await client.fetch_text("https://example.com/fail")

            # Failed attempts should record errors on observer
            failed_resps = [r for r in responses if r.is_error]
            assert len(failed_resps) >= 1
            assert "Connection dropped" in str(failed_resps[0].error_message)

    asyncio.run(_run())

    # Direct unit test for _format_body_snippet
    assert _format_body_snippet(b"hello bytes") == "hello bytes"
    assert _format_body_snippet("a" * 300, max_len=50).endswith("...")
    assert (
        _format_body_snippet(b"\xff\xfe invalid utf", max_len=50) == "<binary 14 bytes>"
    )

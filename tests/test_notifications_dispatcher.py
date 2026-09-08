"""Unit tests for multi-platform webhook notification dispatcher."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest import mock

import httpx

from ecu_hockey_calendar.notifications.dispatcher import (
    NotificationDispatcher,
    _calculate_backoff_delay,
    _extract_retry_after_header,
    _extract_retry_after_json,
    _format_channel_payload,
    _resolve_channel_url,
)
from ecu_hockey_calendar.notifications.models import (
    NotificationChannel,
    NotificationConfig,
    NotificationMessage,
)
from ecu_hockey_calendar.reconciliation.models import (
    ChangeDetectionCycleResult,
    GameChangeRecord,
    GameStateTransition,
)


def test_extract_retry_after_header() -> None:
    """Test parsing Retry-After headers."""
    req = httpx.Request("POST", "https://example.com")

    resp_valid = httpx.Response(429, request=req, headers={"Retry-After": "4.5"})
    assert _extract_retry_after_header(resp_valid) == 4.5

    resp_clamped_high = httpx.Response(
        429,
        request=req,
        headers={"Retry-After": "120.0"},
    )
    assert _extract_retry_after_header(resp_clamped_high) == 60.0

    resp_clamped_low = httpx.Response(
        429,
        request=req,
        headers={"Retry-After": "0.0001"},
    )
    assert _extract_retry_after_header(resp_clamped_low) == 0.01

    resp_invalid = httpx.Response(
        429,
        request=req,
        headers={"Retry-After": "not-a-number"},
    )
    assert _extract_retry_after_header(resp_invalid) is None

    resp_missing = httpx.Response(429, request=req)
    assert _extract_retry_after_header(resp_missing) is None


def test_extract_retry_after_json() -> None:
    """Test extracting retry delays from Discord and Telegram JSON error responses."""
    req = httpx.Request("POST", "https://example.com")

    # Discord format
    resp_discord = httpx.Response(429, request=req, json={"retry_after": 2.5})
    assert _extract_retry_after_json(resp_discord) == 2.5

    # Telegram format
    resp_telegram = httpx.Response(
        429,
        request=req,
        json={"parameters": {"retry_after": 7.0}},
    )
    assert _extract_retry_after_json(resp_telegram) == 7.0

    # Non-dict JSON
    resp_list = httpx.Response(429, request=req, text="[1, 2, 3]")
    assert _extract_retry_after_json(resp_list) is None

    # Invalid JSON
    resp_invalid = httpx.Response(429, request=req, text="<error>Not JSON</error>")
    assert _extract_retry_after_json(resp_invalid) is None

    # Missing keys
    resp_empty = httpx.Response(429, request=req, json={"ok": False})
    assert _extract_retry_after_json(resp_empty) is None

    # Unparsable value
    resp_unparseable = httpx.Response(429, request=req, json={"retry_after": "invalid"})
    assert _extract_retry_after_json(resp_unparseable) is None

    # Non-scalar value
    resp_non_scalar = httpx.Response(429, request=req, json={"retry_after": [1, 2]})
    assert _extract_retry_after_json(resp_non_scalar) is None


def test_calculate_backoff_delay() -> None:
    """Test backoff calculation for 429 and other error responses."""
    req = httpx.Request("POST", "https://example.com")

    # 429 with header
    resp_header = httpx.Response(429, request=req, headers={"Retry-After": "3.0"})
    assert _calculate_backoff_delay(resp_header, 0, 0.5) == 3.0

    # 429 with json
    resp_json = httpx.Response(429, request=req, json={"retry_after": 1.5})
    assert _calculate_backoff_delay(resp_json, 0, 0.5) == 1.5

    # 429 fallback
    resp_429 = httpx.Response(429, request=req, text="rate limit")
    assert _calculate_backoff_delay(resp_429, 1, 0.5) == 1.0

    # 500 error
    resp_500 = httpx.Response(500, request=req)
    assert _calculate_backoff_delay(resp_500, 2, 0.5) == 2.0

    # Network error (None response)
    assert _calculate_backoff_delay(None, 3, 0.5) == 4.0


def test_resolve_channel_url() -> None:
    """Test resolving endpoint URLs for channels."""
    config = NotificationConfig(
        discord_webhook_url="https://discord.com/api/webhooks/test",
        slack_webhook_url="https://hooks.slack.com/services/test",
        telegram_bot_token="token123",
        telegram_chat_id="chat456",
    )

    assert (
        _resolve_channel_url(NotificationChannel.DISCORD, config)
        == "https://discord.com/api/webhooks/test"
    )
    assert (
        _resolve_channel_url(NotificationChannel.SLACK, config)
        == "https://hooks.slack.com/services/test"
    )
    assert (
        _resolve_channel_url(NotificationChannel.TELEGRAM, config)
        == "https://api.telegram.org/bottoken123/sendMessage"
    )

    # Incomplete telegram config
    config_bad_tg = NotificationConfig(telegram_bot_token="token123")
    assert _resolve_channel_url(NotificationChannel.TELEGRAM, config_bad_tg) == ""


def test_format_channel_payload() -> None:
    """Test formatting channel payloads."""
    config = NotificationConfig(
        telegram_chat_id="chat999",
        parse_mode="HTML",
    )
    msg = NotificationMessage(title="Title", summary="Summary")

    discord_payload = _format_channel_payload(
        NotificationChannel.DISCORD,
        msg,
        config,
    )
    assert "embeds" in discord_payload

    slack_payload = _format_channel_payload(
        NotificationChannel.SLACK,
        msg,
        config,
    )
    assert "blocks" in slack_payload

    telegram_payload = _format_channel_payload(
        NotificationChannel.TELEGRAM,
        msg,
        config,
    )
    assert telegram_payload["chat_id"] == "chat999"
    assert telegram_payload["parse_mode"] == "HTML"


def test_dispatcher_no_channels_configured() -> None:
    """Test dispatcher behavior when no channels are configured."""

    async def _run() -> None:
        """Execute async test logic."""
        empty_config = NotificationConfig()
        dispatcher = NotificationDispatcher(config=empty_config)
        msg = NotificationMessage(
            title="Test",
            summary="Summary",
            cycle_id="cycle-0",
        )

        # Async dispatch
        summary_async = await dispatcher.async_dispatch(msg)
        assert len(summary_async.results) == 0
        assert summary_async.cycle_id == "cycle-0"

        # Sync dispatch
        summary_sync = dispatcher.dispatch(msg)
        assert len(summary_sync.results) == 0

    asyncio.run(_run())


def test_async_dispatch_success_across_channels() -> None:
    """Test successful async dispatch across all three channels."""

    async def _run() -> None:
        """Execute async test logic."""
        config = NotificationConfig(
            discord_webhook_url="https://discord.com/webhook",
            slack_webhook_url="https://slack.com/webhook",
            telegram_bot_token="token123",
            telegram_chat_id="chat123",
        )

        requests_made: list[str] = []

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            """Handle mocked HTTP request."""
            requests_made.append(str(request.url))
            if "discord" in str(request.url):
                return httpx.Response(204)

            return httpx.Response(200, json={"ok": True})

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        dispatcher = NotificationDispatcher(config=config, async_client=mock_client)

        msg = NotificationMessage(title="Success Alert", summary="All OK")
        summary = await dispatcher.async_dispatch(msg)

        assert len(summary.results) == 3
        assert summary.all_successful is True
        assert len(requests_made) == 3
        await mock_client.aclose()

    asyncio.run(_run())


def test_sync_dispatch_success_across_channels() -> None:
    """Test successful sync dispatch across all three channels."""
    config = NotificationConfig(
        discord_webhook_url="https://discord.com/webhook",
        slack_webhook_url="https://slack.com/webhook",
        telegram_bot_token="token123",
        telegram_chat_id="chat123",
    )

    def mock_handler(request: httpx.Request) -> httpx.Response:
        """Handle mocked HTTP request."""
        if "discord" in str(request.url):
            return httpx.Response(204)

        return httpx.Response(200, json={"ok": True})

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    dispatcher = NotificationDispatcher(config=config, sync_client=mock_client)

    msg = NotificationMessage(title="Success Alert", summary="All OK")
    summary = dispatcher.dispatch(msg)

    assert len(summary.results) == 3
    assert summary.all_successful is True
    mock_client.close()


def test_async_dispatch_rate_limit_retry_and_recovery() -> None:
    """Test async handling of 429 rate limit with Retry-After header and recovery."""

    async def _run() -> None:
        """Execute async test logic."""
        config = NotificationConfig(
            discord_webhook_url="https://discord.com/webhook",
            max_retries=3,
            backoff_factor=0.1,
        )

        attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            """Record sleep delay."""
            delays.append(delay)

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            """Handle mocked HTTP request."""
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(
                    429,
                    request=request,
                    headers={"Retry-After": "0.25"},
                )

            return httpx.Response(204, request=request)

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        dispatcher = NotificationDispatcher(
            config=config,
            async_client=mock_client,
            async_sleep_func=fake_sleep,
        )

        msg = NotificationMessage(title="Rate Limit Test", summary="Test")
        summary = await dispatcher.async_dispatch(msg)

        assert summary.all_successful is True
        assert attempts == 2
        assert delays == [0.25]
        await mock_client.aclose()

    asyncio.run(_run())


def test_sync_dispatch_rate_limit_exhausted() -> None:
    """Test sync handling of 429 rate limit exhausting all retries."""
    config = NotificationConfig(
        slack_webhook_url="https://slack.com/webhook",
        max_retries=2,
        backoff_factor=0.1,
    )

    attempts = 0
    delays: list[float] = []

    def fake_sleep(delay: float) -> None:
        """Record sleep delay."""
        delays.append(delay)

    def mock_handler(request: httpx.Request) -> httpx.Response:
        """Handle mocked HTTP request."""
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            429,
            request=request,
            text="rate limit exceeded",
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    dispatcher = NotificationDispatcher(
        config=config,
        sync_client=mock_client,
        sync_sleep_func=fake_sleep,
    )

    msg = NotificationMessage(title="Rate Limit Exhausted", summary="Test")
    summary = dispatcher.dispatch(msg)

    assert summary.all_successful is False
    assert attempts == 2
    assert summary.results[0].status_code == 429
    assert len(delays) == 1
    mock_client.close()


def test_async_dispatch_server_error_500_recovery() -> None:
    """Test async handling of 500 error with retry recovery."""

    async def _run() -> None:
        """Execute async test logic."""
        config = NotificationConfig(
            discord_webhook_url="https://discord.com/webhook",
            max_retries=3,
            backoff_factor=0.1,
        )

        attempts = 0

        async def fake_sleep(_delay: float) -> None:
            """Simulate sleep."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            """Handle mocked HTTP request."""
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(500, request=request, text="Internal Error")

            return httpx.Response(204, request=request)

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        dispatcher = NotificationDispatcher(
            config=config,
            async_client=mock_client,
            async_sleep_func=fake_sleep,
        )

        msg = NotificationMessage(title="Server Recovery", summary="Test")
        summary = await dispatcher.async_dispatch(msg)

        assert summary.all_successful is True
        assert attempts == 2
        await mock_client.aclose()

    asyncio.run(_run())


def test_sync_dispatch_client_error_400_no_retry() -> None:
    """Test that non-retryable 400 client error does not retry."""
    config = NotificationConfig(
        discord_webhook_url="https://discord.com/webhook",
        max_retries=3,
    )

    attempts = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        """Handle mocked HTTP request."""
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, request=request, text="Bad Request Payload")

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    dispatcher = NotificationDispatcher(config=config, sync_client=mock_client)

    msg = NotificationMessage(title="Bad Request", summary="Test")
    summary = dispatcher.dispatch(msg)

    assert summary.all_successful is False
    assert attempts == 1
    assert summary.results[0].status_code == 400
    mock_client.close()


def test_async_dispatch_network_exception_retry() -> None:
    """Test network error retry and eventual exhaustion."""

    async def _run() -> None:
        """Execute async test logic."""
        config = NotificationConfig(
            discord_webhook_url="https://discord.com/webhook",
            max_retries=2,
            backoff_factor=0.1,
        )

        attempts = 0

        async def fake_sleep(_delay: float) -> None:
            """Simulate sleep."""

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            """Handle mocked HTTP request."""
            nonlocal attempts
            attempts += 1
            raise httpx.ConnectError("Connection refused", request=request)

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        dispatcher = NotificationDispatcher(
            config=config,
            async_client=mock_client,
            async_sleep_func=fake_sleep,
        )

        msg = NotificationMessage(title="Network Error", summary="Test")
        summary = await dispatcher.async_dispatch(msg)

        assert summary.all_successful is False
        assert attempts == 2
        assert summary.results[0].status_code is None
        assert "Network error after 2 attempts" in (
            summary.results[0].error_message or ""
        )
        await mock_client.aclose()

    asyncio.run(_run())


def test_sync_dispatch_network_exception_retry() -> None:
    """Test sync network error retry and eventual exhaustion."""
    config = NotificationConfig(
        slack_webhook_url="https://slack.com/webhook",
        max_retries=2,
        backoff_factor=0.1,
    )

    attempts = 0

    def fake_sleep(_delay: float) -> None:
        """Simulate sleep."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        """Handle mocked HTTP request."""
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectTimeout("Connection timed out", request=request)

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    dispatcher = NotificationDispatcher(
        config=config,
        sync_client=mock_client,
        sync_sleep_func=fake_sleep,
    )

    msg = NotificationMessage(title="Timeout Error", summary="Test")
    summary = dispatcher.dispatch(msg)

    assert summary.all_successful is False
    assert attempts == 2
    assert summary.results[0].status_code is None
    assert "Network error after 2 attempts" in (summary.results[0].error_message or "")
    mock_client.close()


def test_async_dispatch_change_and_cycle() -> None:
    """Test async_dispatch_change and async_dispatch_cycle."""

    async def _run() -> None:
        """Execute async test logic."""
        config = NotificationConfig(
            discord_webhook_url="https://discord.com/webhook",
        )

        async def mock_handler(_request: httpx.Request) -> httpx.Response:
            """Handle mocked HTTP request."""
            return httpx.Response(204)

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        dispatcher = NotificationDispatcher(config=config, async_client=mock_client)

        # Dispatch single change
        change = GameChangeRecord(
            canonical_game_id="game-1",
            state_transition=GameStateTransition.CREATED,
            current_snapshot={"opponent_name": "UNC"},
        )
        res_change = await dispatcher.async_dispatch_change(change, cycle_id="c1")
        assert res_change.all_successful is True

        # Dispatch cycle without individual changes
        change_unchanged = GameChangeRecord(
            canonical_game_id="game-2",
            state_transition=GameStateTransition.UNCHANGED,
        )
        cycle = ChangeDetectionCycleResult(
            cycle_id="cycle-main",
            changes=[change, change_unchanged],
        )
        summaries = await dispatcher.async_dispatch_cycle(
            cycle,
            individual_changes=False,
        )
        assert len(summaries) == 1

        # Dispatch cycle with individual changes
        summaries_ind = await dispatcher.async_dispatch_cycle(
            cycle,
            individual_changes=True,
        )
        # 1 cycle summary + 1 created change (unchanged is skipped)
        assert len(summaries_ind) == 2

        await mock_client.aclose()

    asyncio.run(_run())


def test_sync_dispatch_change_and_cycle() -> None:
    """Test dispatch_change and dispatch_cycle."""
    config = NotificationConfig(
        slack_webhook_url="https://slack.com/webhook",
    )

    def mock_handler(_request: httpx.Request) -> httpx.Response:
        """Handle mocked HTTP request."""
        return httpx.Response(200, json={"ok": True})

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    dispatcher = NotificationDispatcher(config=config, sync_client=mock_client)

    # Dispatch single change
    change = GameChangeRecord(
        canonical_game_id="game-1",
        state_transition=GameStateTransition.UPDATED,
        current_snapshot={"opponent_name": "NC State"},
    )
    res_change = dispatcher.dispatch_change(change, cycle_id="c1")
    assert res_change.all_successful is True

    # Dispatch cycle with individual changes
    change_unchanged = GameChangeRecord(
        canonical_game_id="game-2",
        state_transition=GameStateTransition.UNCHANGED,
    )
    cycle = ChangeDetectionCycleResult(
        cycle_id="cycle-main",
        changes=[change, change_unchanged],
    )
    summaries = dispatcher.dispatch_cycle(cycle, individual_changes=True)
    assert len(summaries) == 2
    mock_client.close()


def test_default_client_lifecycle() -> None:
    """Test that dispatcher creates and cleans up default clients when none provided."""

    async def _run() -> None:
        """Execute async test logic."""
        config = NotificationConfig(
            discord_webhook_url="https://discord.com/webhook",
        )
        dispatcher = NotificationDispatcher(config=config)
        msg = NotificationMessage(title="Auto Client", summary="Test")

        calls = []

        async def mock_post(
            _self: Any,
            url: str,
            **_kwargs: Any,
        ) -> httpx.Response:
            """Mock async post handler."""
            calls.append(url)
            return httpx.Response(204)

        with mock.patch.object(httpx.AsyncClient, "post", mock_post):
            summary_async = await dispatcher.async_dispatch(msg)
            assert summary_async.all_successful is True

        def mock_sync_post(
            _self: Any,
            url: str,
            **_kwargs: Any,
        ) -> httpx.Response:
            """Mock sync post handler."""
            calls.append(url)
            return httpx.Response(204)

        with mock.patch.object(httpx.Client, "post", mock_sync_post):
            summary_sync = dispatcher.dispatch(msg)
            assert summary_sync.all_successful is True

    asyncio.run(_run())


def test_determine_target_channels_with_requested_subset() -> None:
    """Test channel filtering when explicit subset is requested."""
    config = NotificationConfig(
        discord_webhook_url="https://discord.com/webhook",
        # slack not configured
    )
    dispatcher = NotificationDispatcher(config=config)
    targets = dispatcher._determine_target_channels(  # pylint: disable=protected-access
        {NotificationChannel.DISCORD, NotificationChannel.SLACK},
    )
    assert targets == {NotificationChannel.DISCORD}


def test_async_dispatch_zero_retries() -> None:
    """Test async dispatch when max_retries is 0."""

    async def _run() -> None:
        """Execute async test logic."""
        config = NotificationConfig(
            discord_webhook_url="https://discord.com/webhook",
            max_retries=0,
        )
        mock_client_async = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
        dispatcher_async = NotificationDispatcher(
            config=config,
            async_client=mock_client_async,
        )
        msg = NotificationMessage(title="Zero Retries", summary="Test")
        res_async = await dispatcher_async.async_dispatch(msg)
        assert len(res_async.results) == 1
        assert res_async.results[0].success is False
        assert "Exhausted 0 retries" in (res_async.results[0].error_message or "")
        await mock_client_async.aclose()

    asyncio.run(_run())


def test_sync_dispatch_zero_retries() -> None:
    """Test sync dispatch when max_retries is 0."""
    config = NotificationConfig(
        discord_webhook_url="https://discord.com/webhook",
        max_retries=0,
    )
    mock_client_sync = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    )
    dispatcher_sync = NotificationDispatcher(
        config=config,
        sync_client=mock_client_sync,
    )
    msg = NotificationMessage(title="Zero Retries", summary="Test")
    res_sync = dispatcher_sync.dispatch(msg)
    assert len(res_sync.results) == 1
    assert res_sync.results[0].success is False
    assert "Exhausted 0 retries" in (res_sync.results[0].error_message or "")
    mock_client_sync.close()


def test_async_dispatch_rate_limit_exhausted() -> None:
    """Test async handling of 429 rate limit exhausting all retries."""

    async def _run() -> None:
        """Execute async test logic."""
        config = NotificationConfig(
            discord_webhook_url="https://discord.com/webhook",
            max_retries=2,
            backoff_factor=0.1,
        )

        attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            """Record sleep delay."""
            delays.append(delay)

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            """Handle mocked HTTP request."""
            nonlocal attempts
            attempts += 1
            return httpx.Response(
                429,
                request=request,
                text="rate limit exceeded",
            )

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
        dispatcher = NotificationDispatcher(
            config=config,
            async_client=mock_client,
            async_sleep_func=fake_sleep,
        )

        msg = NotificationMessage(title="Rate Limit Exhausted Async", summary="Test")
        summary = await dispatcher.async_dispatch(msg)

        assert summary.all_successful is False
        assert attempts == 2
        assert summary.results[0].status_code == 429
        assert len(delays) == 1
        await mock_client.aclose()

    asyncio.run(_run())


def test_sync_dispatch_cycle_no_individual_changes() -> None:
    """Test sync dispatch_cycle with individual_changes=False."""
    config = NotificationConfig(
        discord_webhook_url="https://discord.com/webhook",
    )

    def mock_handler(_request: httpx.Request) -> httpx.Response:
        """Handle mocked HTTP request."""
        return httpx.Response(204)

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    dispatcher = NotificationDispatcher(config=config, sync_client=mock_client)

    cycle = ChangeDetectionCycleResult(
        cycle_id="cycle-summary-only",
        changes=[],
    )
    summaries = dispatcher.dispatch_cycle(cycle, individual_changes=False)
    assert len(summaries) == 1
    mock_client.close()

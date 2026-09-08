"""Multi-platform webhook notification dispatcher for schedule alerts and updates."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

import httpx

from ecu_hockey_calendar.notifications.formatters import (
    format_discord_payload,
    format_slack_payload,
    format_telegram_payload,
)
from ecu_hockey_calendar.notifications.models import (
    DispatchResult,
    MultiChannelDispatchSummary,
    NotificationChannel,
    NotificationConfig,
    NotificationMessage,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ecu_hockey_calendar.reconciliation.models import (
        ChangeDetectionCycleResult,
        GameChangeRecord,
    )

logger = logging.getLogger(__name__)

HTTP_STATUS_OK = 200
HTTP_STATUS_MULTIPLE_CHOICES = 300
HTTP_STATUS_TOO_MANY_REQUESTS = 429

RETRYABLE_STATUS_CODES = {HTTP_STATUS_TOO_MANY_REQUESTS, 500, 502, 503, 504}
MAX_RETRY_DELAY_SECONDS = 60.0
MIN_RETRY_DELAY_SECONDS = 0.01


def _extract_retry_after_header(response: httpx.Response) -> float | None:
    """Attempt to parse standard Retry-After header."""
    header_val = response.headers.get("Retry-After")
    if not header_val:
        return None

    try:
        val = float(header_val)
        return min(max(val, MIN_RETRY_DELAY_SECONDS), MAX_RETRY_DELAY_SECONDS)
    except ValueError:
        return None


def _parse_retry_val(val: object) -> float | None:
    """Safely cast numeric value to bounded retry seconds."""
    if not isinstance(val, (int, float, str)):
        return None

    try:
        fval = float(val)
        return float(min(max(fval, MIN_RETRY_DELAY_SECONDS), MAX_RETRY_DELAY_SECONDS))
    except ValueError:
        return None


def _extract_retry_after_json(response: httpx.Response) -> float | None:
    """Extract retry delay from Discord or Telegram JSON error responses."""
    try:
        data = response.json()
    except (ValueError, TypeError):
        return None

    if not isinstance(data, dict):
        return None

    if "retry_after" in data:
        return _parse_retry_val(data["retry_after"])

    params = data.get("parameters")
    if isinstance(params, dict):
        return _parse_retry_val(params.get("retry_after"))

    return None


def _calculate_backoff_delay(
    response: httpx.Response | None,
    attempt: int,
    backoff_factor: float,
) -> float:
    """Calculate backoff delay respecting Retry-After header and provider JSON."""
    if response is not None and response.status_code == HTTP_STATUS_TOO_MANY_REQUESTS:
        from_header = _extract_retry_after_header(response)
        if from_header is not None:
            return from_header

        from_json = _extract_retry_after_json(response)
        if from_json is not None:
            return from_json

    calc_delay: float = float(backoff_factor * (2**attempt))
    return float(min(max(calc_delay, MIN_RETRY_DELAY_SECONDS), MAX_RETRY_DELAY_SECONDS))


def _telegram_url(config: NotificationConfig) -> str:
    """Format telegram sendMessage endpoint URL if credentials exist."""
    if not (config.telegram_bot_token and config.telegram_chat_id):
        return ""

    return f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"


def _resolve_channel_url(
    channel: NotificationChannel,
    config: NotificationConfig,
) -> str:
    """Resolve endpoint URL for the designated notification channel."""
    if channel == NotificationChannel.DISCORD:
        return config.discord_webhook_url or ""

    if channel == NotificationChannel.SLACK:
        return config.slack_webhook_url or ""

    return _telegram_url(config)


def _format_channel_payload(
    channel: NotificationChannel,
    message: NotificationMessage,
    config: NotificationConfig,
) -> dict[str, Any]:
    """Format payload dictionary according to the destination platform."""
    if channel == NotificationChannel.DISCORD:
        return format_discord_payload(message)

    if channel == NotificationChannel.SLACK:
        return format_slack_payload(message)

    chat_id = config.telegram_chat_id or ""
    return format_telegram_payload(
        message,
        chat_id,
        parse_mode=config.parse_mode,
    )


def _handle_response_outcome(
    response: httpx.Response,
    channel: NotificationChannel,
    attempt: int,
    *,
    is_last: bool,
    backoff_factor: float,
) -> tuple[float | None, DispatchResult | None]:
    """Determine if response triggers retry (delay) or finishes (DispatchResult)."""
    if HTTP_STATUS_OK <= response.status_code < HTTP_STATUS_MULTIPLE_CHOICES:
        return None, DispatchResult(
            channel=channel,
            success=True,
            status_code=response.status_code,
            attempts=attempt + 1,
        )

    if response.status_code in RETRYABLE_STATUS_CODES and not is_last:
        delay = _calculate_backoff_delay(response, attempt, backoff_factor)
        return delay, None

    error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
    return None, DispatchResult(
        channel=channel,
        success=False,
        status_code=response.status_code,
        attempts=attempt + 1,
        error_message=error_msg,
    )


async def _async_send_attempt(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
    channel: NotificationChannel,
    config: NotificationConfig,
    *,
    attempt: int,
    sleep_func: Callable[[float], Awaitable[None]],
) -> tuple[bool, DispatchResult | None]:
    """Perform a single asynchronous HTTP dispatch attempt."""
    is_last = attempt + 1 >= config.max_retries
    try:
        response = await client.post(url, json=payload, timeout=config.timeout_seconds)
    except httpx.RequestError as exc:
        if is_last:
            err_text = f"Network error after {config.max_retries} attempts: {exc}"
            res = DispatchResult(
                channel=channel,
                success=False,
                attempts=attempt + 1,
                error_message=err_text,
            )
            return False, res

        delay = _calculate_backoff_delay(None, attempt, config.backoff_factor)
        await sleep_func(delay)
        return True, None

    delay, result = _handle_response_outcome(
        response,
        channel,
        attempt,
        is_last=is_last,
        backoff_factor=config.backoff_factor,
    )
    if delay is not None:
        await sleep_func(delay)
        return True, None

    return False, result


async def _async_send_with_retry(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
    channel: NotificationChannel,
    config: NotificationConfig,
    *,
    sleep_func: Callable[[float], Awaitable[None]],
) -> DispatchResult:
    """Send webhook payload asynchronously with retries and throttling backoff."""
    for attempt in range(config.max_retries):
        should_continue, result = await _async_send_attempt(
            client,
            url,
            payload,
            channel,
            config,
            attempt=attempt,
            sleep_func=sleep_func,
        )
        if not should_continue and result is not None:
            return result

    return DispatchResult(
        channel=channel,
        success=False,
        attempts=config.max_retries,
        error_message=f"Exhausted {config.max_retries} retries",
    )


def _sync_send_attempt(
    client: httpx.Client,
    url: str,
    payload: dict[str, Any],
    channel: NotificationChannel,
    config: NotificationConfig,
    *,
    attempt: int,
    sleep_func: Callable[[float], None],
) -> tuple[bool, DispatchResult | None]:
    """Perform a single synchronous HTTP dispatch attempt."""
    is_last = attempt + 1 >= config.max_retries
    try:
        response = client.post(url, json=payload, timeout=config.timeout_seconds)
    except httpx.RequestError as exc:
        if is_last:
            res = DispatchResult(
                channel=channel,
                success=False,
                attempts=attempt + 1,
                error_message=(
                    f"Network error after {config.max_retries} attempts: {exc}"
                ),
            )
            return False, res

        delay = _calculate_backoff_delay(None, attempt, config.backoff_factor)
        sleep_func(delay)
        return True, None

    delay, result = _handle_response_outcome(
        response,
        channel,
        attempt,
        is_last=is_last,
        backoff_factor=config.backoff_factor,
    )
    if delay is not None:
        sleep_func(delay)
        return True, None

    return False, result


def _sync_send_with_retry(
    client: httpx.Client,
    url: str,
    payload: dict[str, Any],
    channel: NotificationChannel,
    config: NotificationConfig,
    *,
    sleep_func: Callable[[float], None],
) -> DispatchResult:
    """Send webhook payload synchronously with retries and throttling backoff."""
    for attempt in range(config.max_retries):
        should_continue, result = _sync_send_attempt(
            client,
            url,
            payload,
            channel,
            config,
            attempt=attempt,
            sleep_func=sleep_func,
        )
        if not should_continue and result is not None:
            return result

    return DispatchResult(
        channel=channel,
        success=False,
        attempts=config.max_retries,
        error_message=f"Exhausted {config.max_retries} retries",
    )


class NotificationDispatcher:
    """Dispatcher for broadcasting alerts across Discord, Slack, and Telegram."""

    def __init__(
        self,
        config: NotificationConfig | None = None,
        *,
        async_client: httpx.AsyncClient | None = None,
        sync_client: httpx.Client | None = None,
        async_sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
        sync_sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize the NotificationDispatcher.

        Args:
            config: NotificationConfig instance (loads from env if None).
            async_client: Optional pre-configured httpx.AsyncClient.
            sync_client: Optional pre-configured httpx.Client.
            async_sleep_func: Async sleep coroutine for retry backoff.
            sync_sleep_func: Sync sleep callable for retry backoff.
        """
        self.config = config or NotificationConfig.from_env()
        self._async_client = async_client
        self._sync_client = sync_client
        self._async_sleep_func = async_sleep_func
        self._sync_sleep_func = sync_sleep_func

    def _determine_target_channels(
        self,
        requested_channels: set[NotificationChannel] | None = None,
    ) -> set[NotificationChannel]:
        """Resolve the set of channels to notify."""
        if requested_channels is not None:
            return {
                ch for ch in requested_channels if self.config.is_channel_configured(ch)
            }

        return self.config.configured_channels

    async def async_dispatch(
        self,
        message: NotificationMessage,
        channels: set[NotificationChannel] | None = None,
    ) -> MultiChannelDispatchSummary:
        """Asynchronously dispatch notification message to all configured channels.

        Args:
            message: Populated NotificationMessage to broadcast.
            channels: Optional explicit set of channels to target.

        Returns:
            MultiChannelDispatchSummary aggregating per-channel outcomes.
        """
        targets = self._determine_target_channels(channels)
        results: list[DispatchResult] = []

        if not targets:
            logger.info("No active notification channels configured.")
            return MultiChannelDispatchSummary(
                results=[],
                cycle_id=message.cycle_id,
                message_title=message.title,
            )

        owns_client = self._async_client is None
        client = self._async_client or httpx.AsyncClient()

        try:
            for ch in targets:
                url = _resolve_channel_url(ch, self.config)
                payload = _format_channel_payload(ch, message, self.config)
                res = await _async_send_with_retry(
                    client,
                    url,
                    payload,
                    ch,
                    self.config,
                    sleep_func=self._async_sleep_func,
                )
                results.append(res)
        finally:
            if owns_client:
                await client.aclose()

        return MultiChannelDispatchSummary(
            results=results,
            cycle_id=message.cycle_id,
            message_title=message.title,
        )

    def dispatch(
        self,
        message: NotificationMessage,
        channels: set[NotificationChannel] | None = None,
    ) -> MultiChannelDispatchSummary:
        """Synchronously dispatch notification message to all configured channels.

        Args:
            message: Populated NotificationMessage to broadcast.
            channels: Optional explicit set of channels to target.

        Returns:
            MultiChannelDispatchSummary aggregating per-channel outcomes.
        """
        targets = self._determine_target_channels(channels)
        results: list[DispatchResult] = []

        if not targets:
            logger.info("No active notification channels configured.")
            return MultiChannelDispatchSummary(
                results=[],
                cycle_id=message.cycle_id,
                message_title=message.title,
            )

        owns_client = self._sync_client is None
        client = self._sync_client or httpx.Client()

        try:
            for ch in targets:
                url = _resolve_channel_url(ch, self.config)
                payload = _format_channel_payload(ch, message, self.config)
                res = _sync_send_with_retry(
                    client,
                    url,
                    payload,
                    ch,
                    self.config,
                    sleep_func=self._sync_sleep_func,
                )
                results.append(res)
        finally:
            if owns_client:
                client.close()

        return MultiChannelDispatchSummary(
            results=results,
            cycle_id=message.cycle_id,
            message_title=message.title,
        )

    async def async_dispatch_change(
        self,
        change: GameChangeRecord,
        *,
        cycle_id: str | None = None,
        channels: set[NotificationChannel] | None = None,
    ) -> MultiChannelDispatchSummary:
        """Asynchronously dispatch notification for a single GameChangeRecord.

        Args:
            change: Atomic game change record.
            cycle_id: Optional sync cycle identifier.
            channels: Optional explicit channels to notify.

        Returns:
            MultiChannelDispatchSummary for the change event.
        """
        message = NotificationMessage.from_change_record(change, cycle_id=cycle_id)
        return await self.async_dispatch(message, channels=channels)

    def dispatch_change(
        self,
        change: GameChangeRecord,
        *,
        cycle_id: str | None = None,
        channels: set[NotificationChannel] | None = None,
    ) -> MultiChannelDispatchSummary:
        """Synchronously dispatch notification for a single GameChangeRecord.

        Args:
            change: Atomic game change record.
            cycle_id: Optional sync cycle identifier.
            channels: Optional explicit channels to notify.

        Returns:
            MultiChannelDispatchSummary for the change event.
        """
        message = NotificationMessage.from_change_record(change, cycle_id=cycle_id)
        return self.dispatch(message, channels=channels)

    async def async_dispatch_cycle(
        self,
        cycle: ChangeDetectionCycleResult,
        *,
        individual_changes: bool = False,
        channels: set[NotificationChannel] | None = None,
    ) -> list[MultiChannelDispatchSummary]:
        """Asynchronously dispatch notifications for a synchronization cycle.

        Args:
            cycle: Synchronization cycle result.
            individual_changes: If True, dispatch alerts for each individual change
                in addition to the cycle summary.
            channels: Optional explicit channels to notify.

        Returns:
            List of MultiChannelDispatchSummary instances.
        """
        summaries: list[MultiChannelDispatchSummary] = []
        summary_msg = NotificationMessage.from_cycle_result(cycle)
        summaries.append(await self.async_dispatch(summary_msg, channels=channels))

        if individual_changes:
            for change in cycle.changes:
                if change.state_transition == change.state_transition.UNCHANGED:
                    continue

                summaries.append(
                    await self.async_dispatch_change(
                        change,
                        cycle_id=cycle.cycle_id,
                        channels=channels,
                    ),
                )

        return summaries

    def dispatch_cycle(
        self,
        cycle: ChangeDetectionCycleResult,
        *,
        individual_changes: bool = False,
        channels: set[NotificationChannel] | None = None,
    ) -> list[MultiChannelDispatchSummary]:
        """Synchronously dispatch notifications for a synchronization cycle.

        Args:
            cycle: Synchronization cycle result.
            individual_changes: If True, dispatch alerts for each individual change
                in addition to the cycle summary.
            channels: Optional explicit channels to notify.

        Returns:
            List of MultiChannelDispatchSummary instances.
        """
        summaries: list[MultiChannelDispatchSummary] = []
        summary_msg = NotificationMessage.from_cycle_result(cycle)
        summaries.append(self.dispatch(summary_msg, channels=channels))

        if individual_changes:
            for change in cycle.changes:
                if change.state_transition == change.state_transition.UNCHANGED:
                    continue

                summaries.append(
                    self.dispatch_change(
                        change,
                        cycle_id=cycle.cycle_id,
                        channels=channels,
                    ),
                )

        return summaries


__all__ = [
    "HTTP_STATUS_MULTIPLE_CHOICES",
    "HTTP_STATUS_OK",
    "HTTP_STATUS_TOO_MANY_REQUESTS",
    "MAX_RETRY_DELAY_SECONDS",
    "MIN_RETRY_DELAY_SECONDS",
    "RETRYABLE_STATUS_CODES",
    "NotificationDispatcher",
]

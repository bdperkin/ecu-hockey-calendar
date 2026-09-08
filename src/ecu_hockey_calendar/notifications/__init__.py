"""Multi-channel notification and webhook dispatch package."""

from __future__ import annotations

from ecu_hockey_calendar.notifications.dispatcher import (
    MAX_RETRY_DELAY_SECONDS,
    MIN_RETRY_DELAY_SECONDS,
    RETRYABLE_STATUS_CODES,
    NotificationDispatcher,
)
from ecu_hockey_calendar.notifications.formatters import (
    DISCORD_COLOR_AMBER,
    DISCORD_COLOR_BLUE,
    DISCORD_COLOR_GREEN,
    DISCORD_COLOR_ORANGE,
    DISCORD_COLOR_PURPLE,
    DISCORD_COLOR_RED,
    DISCORD_SEVERITY_COLORS,
    DISCORD_TRANSITION_COLORS,
    format_discord_payload,
    format_slack_payload,
    format_telegram_payload,
)
from ecu_hockey_calendar.notifications.models import (
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_MAX_RETRIES,
    DEFAULT_NOTIFICATION_FOOTER,
    DEFAULT_TELEGRAM_PARSE_MODE,
    DEFAULT_TIMEOUT_SECONDS,
    DispatchResult,
    MultiChannelDispatchSummary,
    NotificationChannel,
    NotificationConfig,
    NotificationField,
    NotificationMessage,
    NotificationSeverity,
)

__all__ = [
    "DEFAULT_BACKOFF_FACTOR",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_NOTIFICATION_FOOTER",
    "DEFAULT_TELEGRAM_PARSE_MODE",
    "DEFAULT_TIMEOUT_SECONDS",
    "DISCORD_COLOR_AMBER",
    "DISCORD_COLOR_BLUE",
    "DISCORD_COLOR_GREEN",
    "DISCORD_COLOR_ORANGE",
    "DISCORD_COLOR_PURPLE",
    "DISCORD_COLOR_RED",
    "DISCORD_SEVERITY_COLORS",
    "DISCORD_TRANSITION_COLORS",
    "MAX_RETRY_DELAY_SECONDS",
    "MIN_RETRY_DELAY_SECONDS",
    "RETRYABLE_STATUS_CODES",
    "DispatchResult",
    "MultiChannelDispatchSummary",
    "NotificationChannel",
    "NotificationConfig",
    "NotificationDispatcher",
    "NotificationField",
    "NotificationMessage",
    "NotificationSeverity",
    "format_discord_payload",
    "format_slack_payload",
    "format_telegram_payload",
]

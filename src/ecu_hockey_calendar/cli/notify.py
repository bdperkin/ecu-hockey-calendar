"""Implementation of the 'ecu-hockey notify' CLI command.

Dispatches custom notification alerts and failure reports to configured
webhook platforms (Discord, Slack, Telegram).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from ecu_hockey_calendar.cli.console import (
    create_table,
    format_status_badge,
    get_console,
    print_banner,
    print_error,
    print_success,
    print_warning,
)
from ecu_hockey_calendar.notifications.dispatcher import NotificationDispatcher
from ecu_hockey_calendar.notifications.models import (
    NotificationChannel,
    NotificationConfig,
    NotificationField,
    NotificationMessage,
    NotificationSeverity,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rich.table import Table

    from ecu_hockey_calendar.notifications.models import (
        MultiChannelDispatchSummary,
    )


class NotificationDispatchError(Exception):
    """Raised when notification delivery fails on one or more channels."""


SEVERITY_MAP: dict[str, NotificationSeverity] = {
    "info": NotificationSeverity.INFO,
    "success": NotificationSeverity.SUCCESS,
    "warning": NotificationSeverity.WARNING,
    "alert": NotificationSeverity.ALERT,
    "error": NotificationSeverity.ALERT,
}


def _build_notification_message(
    title: str,
    message: str,
    severity: str,
    details: str | None,
    url: str | None,
) -> NotificationMessage:
    """Construct a NotificationMessage from CLI arguments.

    Args:
        title: Notification header title.
        message: Primary notification summary.
        severity: String severity level.
        details: Optional extended details or error text.
        url: Optional action or workflow URL.

    Returns:
        Configured NotificationMessage instance.
    """
    resolved_severity = SEVERITY_MAP.get(
        severity.lower(),
        NotificationSeverity.INFO,
    )
    fields: list[NotificationField] = []
    if url:
        fields.append(NotificationField("URL", url, inline=False))

    return NotificationMessage(
        title=title,
        summary=message,
        details=details or "",
        severity=resolved_severity,
        fields=fields,
        event_url=url,
    )


def _resolve_target_channels(
    channels: Sequence[str] | None,
) -> set[NotificationChannel] | None:
    """Resolve target channel set from CLI sequence.

    Args:
        channels: Optional sequence of channel string names.

    Returns:
        Set of NotificationChannel enums, or None if unspecified.
    """
    if not channels:
        return None

    return {NotificationChannel(c.lower()) for c in channels}


def _render_dispatch_table(summary: MultiChannelDispatchSummary) -> Table:
    """Construct Rich Table displaying per-channel dispatch results.

    Args:
        summary: Aggregated multi-channel dispatch summary.

    Returns:
        Populated Rich Table instance.
    """
    table = create_table(
        "Notification Dispatch Telemetry",
        [
            ("Channel", "bold cyan"),
            ("Status", "bold"),
            ("Attempts", "dim"),
            ("Details", "dim"),
        ],
    )
    for res in summary.results:
        status_text = "SUCCESS" if res.success else "FAILURE"
        badge = format_status_badge(status_text)
        detail_msg = res.error_message or "Delivered"
        table.add_row(
            res.channel.value.capitalize(),
            badge,
            str(res.attempts),
            detail_msg,
        )

    return table


def _handle_dispatch_summary(summary: MultiChannelDispatchSummary) -> None:
    """Evaluate dispatch outcome and raise ClickException on failure.

    Args:
        summary: Aggregated multi-channel dispatch summary.

    Raises:
        click.ClickException: If any targeted channel failed delivery.
    """
    if summary.all_successful:
        print_success("Notification successfully dispatched to all target channels.")
        return

    failed = ", ".join(c.value for c in summary.failed_channels)
    print_error(f"Failed to dispatch notification to channels: {failed}")
    exc = NotificationDispatchError(f"Notification dispatch failed for: {failed}")
    raise click.ClickException(str(exc)) from exc


@click.command("notify")
@click.option(
    "--message",
    "-m",
    required=True,
    help="Primary notification summary or message body.",
)
@click.option(
    "--title",
    "-t",
    default="ECU Hockey Notification",
    show_default=True,
    help="Title for the notification embed or message header.",
)
@click.option(
    "--severity",
    "-s",
    type=click.Choice(
        ["info", "success", "warning", "alert", "error"],
        case_sensitive=False,
    ),
    default="info",
    show_default=True,
    help="Urgency and severity level.",
)
@click.option(
    "--details",
    "-d",
    default=None,
    help="Extended details, context, or error trace.",
)
@click.option(
    "--url",
    default=None,
    help="Associated action or workflow URL.",
)
@click.option(
    "--channel",
    "-c",
    "channels",
    multiple=True,
    type=click.Choice(
        ["discord", "slack", "telegram"],
        case_sensitive=False,
    ),
    help="Restrict dispatch to specific channel(s) (defaults to all configured).",
)
def notify_command(
    *,
    message: str,
    title: str,
    severity: str,
    details: str | None,
    url: str | None,
    channels: Sequence[str] | None,
) -> None:
    """Dispatch custom notification alerts to webhook channels."""
    console = get_console()
    print_banner("NOTIFICATION DISPATCH", subtitle=f"Severity: {severity.upper()}")

    msg = _build_notification_message(title, message, severity, details, url)
    target_channels = _resolve_target_channels(channels)

    config = NotificationConfig.from_env()
    dispatcher = NotificationDispatcher(config=config)
    summary = dispatcher.dispatch(msg, channels=target_channels)

    if not summary.results:
        print_warning(
            "No active notification channels configured (set DISCORD_WEBHOOK_URL, "
            "SLACK_WEBHOOK_URL, or TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).",
        )
        return

    console.print(_render_dispatch_table(summary))
    console.print()
    _handle_dispatch_summary(summary)

"""Payload formatting and rich embed builders for Discord, Slack, and Telegram."""

from __future__ import annotations

import html
from typing import Any

from ecu_hockey_calendar.notifications.models import (
    NotificationMessage,
    NotificationSeverity,
)
from ecu_hockey_calendar.reconciliation.models import GameStateTransition

# Discord embed color constants
DISCORD_COLOR_GREEN = 3066993  # 0x2ECC71
DISCORD_COLOR_BLUE = 3447003  # 0x3498DB
DISCORD_COLOR_RED = 15158332  # 0xE74C3C
DISCORD_COLOR_ORANGE = 15105570  # 0xE67E22
DISCORD_COLOR_AMBER = 15965202  # 0xF39C12
DISCORD_COLOR_PURPLE = 5843594  # 0x592A8A (ECU Purple)

DISCORD_TRANSITION_COLORS: dict[GameStateTransition, int] = {
    GameStateTransition.CREATED: DISCORD_COLOR_GREEN,
    GameStateTransition.UPDATED: DISCORD_COLOR_BLUE,
    GameStateTransition.DELETED: DISCORD_COLOR_RED,
    GameStateTransition.CONFLICT_DETECTED: DISCORD_COLOR_ORANGE,
    GameStateTransition.UNCHANGED: DISCORD_COLOR_PURPLE,
}

DISCORD_SEVERITY_COLORS: dict[NotificationSeverity, int] = {
    NotificationSeverity.SUCCESS: DISCORD_COLOR_GREEN,
    NotificationSeverity.INFO: DISCORD_COLOR_PURPLE,
    NotificationSeverity.WARNING: DISCORD_COLOR_AMBER,
    NotificationSeverity.ALERT: DISCORD_COLOR_RED,
}


def _resolve_discord_color(message: NotificationMessage) -> int:
    """Resolve embed color integer based on transition or severity."""
    if message.transition and message.transition in DISCORD_TRANSITION_COLORS:
        return DISCORD_TRANSITION_COLORS[message.transition]

    return DISCORD_SEVERITY_COLORS.get(message.severity, DISCORD_COLOR_PURPLE)


def _build_discord_description(message: NotificationMessage) -> str:
    """Combine summary and details for Discord embed description."""
    if message.details:
        return f"{message.summary}\n\n{message.details}"

    return message.summary


def format_discord_payload(message: NotificationMessage) -> dict[str, Any]:
    """Format NotificationMessage into a Discord Webhook embed payload.

    Args:
        message: NotificationMessage instance to format.

    Returns:
        JSON-serializable Discord Webhook dictionary payload.
    """
    fields = [
        {"name": f.title, "value": f.value, "inline": f.inline} for f in message.fields
    ]

    embed: dict[str, Any] = {
        "title": message.title,
        "description": _build_discord_description(message),
        "color": _resolve_discord_color(message),
        "fields": fields,
        "footer": {"text": message.footer},
        "timestamp": message.timestamp.isoformat(),
    }

    if message.event_url:
        embed["url"] = message.event_url

    return {
        "username": "ECU Hockey Bot",
        "embeds": [embed],
    }


def _build_slack_blocks(message: NotificationMessage) -> list[dict[str, Any]]:
    """Construct Slack Block Kit blocks array."""
    desc = message.summary
    if message.details:
        desc = f"{desc}\n\n{message.details}"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": message.title[:150],
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": desc,
            },
        },
    ]

    if message.fields:
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*{f.title}:*\n{f.value}",
                    }
                    for f in message.fields[:10]
                ],
            },
        )

    blocks.append({"type": "divider"})

    context_text = message.footer
    if message.cycle_id:
        context_text = f"Cycle: `{message.cycle_id}` • {context_text}"

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": context_text,
                },
            ],
        },
    )

    return blocks


def format_slack_payload(message: NotificationMessage) -> dict[str, Any]:
    """Format NotificationMessage into a Slack Webhook Block Kit payload.

    Args:
        message: NotificationMessage instance to format.

    Returns:
        JSON-serializable Slack Webhook dictionary payload.
    """
    return {
        "text": f"{message.title}: {message.summary}",
        "blocks": _build_slack_blocks(message),
    }


def _escape_telegram_markdown(text: str) -> str:
    """Escape standard characters for Telegram Markdown parsing."""
    replacements = [
        ("_", "\\_"),
        ("*", "\\*"),
        ("[", "\\["),
        ("]", "\\]"),
        ("`", "\\`"),
    ]
    escaped = text
    for char, target in replacements:
        escaped = escaped.replace(char, target)

    return escaped


def _build_telegram_html_text(message: NotificationMessage) -> str:
    """Format message into Telegram HTML markup."""
    lines = [
        f"<b>{html.escape(message.title)}</b>",
        "",
        html.escape(message.summary),
    ]

    if message.details:
        lines.extend(["", html.escape(message.details)])

    if message.fields:
        lines.append("")
        lines.extend(
            f"• <b>{html.escape(f.title)}:</b> {html.escape(f.value)}"
            for f in message.fields
        )

    lines.extend(["", f"<i>{html.escape(message.footer)}</i>"])
    return "\n".join(lines)


def _escape_markdown_telegram(text: str) -> str:
    """Escape Telegram Markdown characters."""
    return _escape_telegram_markdown(text)


def _build_telegram_markdown_text(message: NotificationMessage) -> str:
    """Format message into Telegram Markdown markup."""
    lines = [
        f"*{_escape_markdown_telegram(message.title)}*",
        "",
        _escape_markdown_telegram(message.summary),
    ]

    if message.details:
        lines.extend(["", _escape_markdown_telegram(message.details)])

    if message.fields:
        lines.append("")
        lines.extend(
            f"• *{_escape_markdown_telegram(f.title)}:* "
            f"{_escape_markdown_telegram(f.value)}"
            for f in message.fields
        )

    lines.extend(["", f"_{_escape_markdown_telegram(message.footer)}_"])
    return "\n".join(lines)


def format_telegram_payload(
    message: NotificationMessage,
    chat_id: str,
    *,
    parse_mode: str = "HTML",
) -> dict[str, Any]:
    """Format NotificationMessage into a Telegram Bot sendMessage payload.

    Args:
        message: NotificationMessage instance to format.
        chat_id: Destination Telegram chat ID or channel username.
        parse_mode: Markup parsing mode ("HTML" or "Markdown").

    Returns:
        JSON-serializable Telegram sendMessage dictionary payload.
    """
    if parse_mode.upper() == "MARKDOWN":
        text = _build_telegram_markdown_text(message)
        mode = "Markdown"
    else:
        text = _build_telegram_html_text(message)
        mode = "HTML"

    return {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": mode,
        "disable_web_page_preview": True,
    }


__all__ = [
    "DISCORD_COLOR_AMBER",
    "DISCORD_COLOR_BLUE",
    "DISCORD_COLOR_GREEN",
    "DISCORD_COLOR_ORANGE",
    "DISCORD_COLOR_PURPLE",
    "DISCORD_COLOR_RED",
    "DISCORD_SEVERITY_COLORS",
    "DISCORD_TRANSITION_COLORS",
    "format_discord_payload",
    "format_slack_payload",
    "format_telegram_payload",
]

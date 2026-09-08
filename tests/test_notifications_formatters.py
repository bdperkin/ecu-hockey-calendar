"""Unit tests for Discord, Slack, and Telegram payload formatters."""

from __future__ import annotations

from datetime import UTC, datetime

from ecu_hockey_calendar.notifications.formatters import (
    DISCORD_COLOR_BLUE,
    DISCORD_COLOR_GREEN,
    DISCORD_COLOR_ORANGE,
    DISCORD_COLOR_PURPLE,
    DISCORD_COLOR_RED,
    format_discord_payload,
    format_slack_payload,
    format_telegram_payload,
)
from ecu_hockey_calendar.notifications.models import (
    NotificationField,
    NotificationMessage,
    NotificationSeverity,
)
from ecu_hockey_calendar.reconciliation.models import GameStateTransition


def test_format_discord_payload_transitions() -> None:
    """Test Discord embed color mapping for all transitions."""
    now = datetime.now(UTC)

    # CREATED -> Green
    msg_created = NotificationMessage(
        title="Created",
        summary="Created Summary",
        transition=GameStateTransition.CREATED,
        timestamp=now,
    )
    payload_created = format_discord_payload(msg_created)
    assert payload_created["embeds"][0]["color"] == DISCORD_COLOR_GREEN

    # UPDATED -> Blue
    msg_updated = NotificationMessage(
        title="Updated",
        summary="Updated Summary",
        transition=GameStateTransition.UPDATED,
        timestamp=now,
    )
    payload_updated = format_discord_payload(msg_updated)
    assert payload_updated["embeds"][0]["color"] == DISCORD_COLOR_BLUE

    # DELETED -> Red
    msg_deleted = NotificationMessage(
        title="Deleted",
        summary="Deleted Summary",
        transition=GameStateTransition.DELETED,
        timestamp=now,
    )
    payload_deleted = format_discord_payload(msg_deleted)
    assert payload_deleted["embeds"][0]["color"] == DISCORD_COLOR_RED

    # CONFLICT_DETECTED -> Orange
    msg_conflict = NotificationMessage(
        title="Conflict",
        summary="Conflict Summary",
        transition=GameStateTransition.CONFLICT_DETECTED,
        timestamp=now,
    )
    payload_conflict = format_discord_payload(msg_conflict)
    assert payload_conflict["embeds"][0]["color"] == DISCORD_COLOR_ORANGE

    # UNCHANGED -> Purple
    msg_unchanged = NotificationMessage(
        title="Unchanged",
        summary="Unchanged Summary",
        transition=GameStateTransition.UNCHANGED,
        timestamp=now,
    )
    payload_unchanged = format_discord_payload(msg_unchanged)
    assert payload_unchanged["embeds"][0]["color"] == DISCORD_COLOR_PURPLE


def test_format_discord_payload_details_and_url() -> None:
    """Test Discord embed details, fields, and event_url."""
    msg = NotificationMessage(
        title="Detailed Alert",
        summary="Summary Line",
        details="Detail line 1\nDetail line 2",
        severity=NotificationSeverity.WARNING,
        fields=[
            NotificationField("Field 1", "Value 1", inline=True),
            NotificationField("Field 2", "Value 2", inline=False),
        ],
        event_url="https://ecuhockey.com/game/123",
        footer="Custom Footer",
    )

    payload = format_discord_payload(msg)
    embed = payload["embeds"][0]
    assert embed["title"] == "Detailed Alert"
    assert embed["description"] == "Summary Line\n\nDetail line 1\nDetail line 2"
    assert embed["url"] == "https://ecuhockey.com/game/123"
    assert embed["footer"] == {"text": "Custom Footer"}
    assert len(embed["fields"]) == 2
    assert embed["fields"][0] == {
        "name": "Field 1",
        "value": "Value 1",
        "inline": True,
    }


def test_format_slack_payload() -> None:
    """Test Slack Block Kit payload formatting."""
    long_title = "A" * 200
    msg = NotificationMessage(
        title=long_title,
        summary="Short Summary",
        details="Detailed bullet point",
        cycle_id="cycle-456",
        fields=[NotificationField(f"K{i}", f"V{i}") for i in range(12)],
    )

    payload = format_slack_payload(msg)
    assert payload["text"].startswith(long_title)

    blocks = payload["blocks"]
    assert blocks[0]["type"] == "header"
    assert len(blocks[0]["text"]["text"]) <= 150

    assert blocks[1]["type"] == "section"
    assert "Short Summary\n\nDetailed bullet point" in blocks[1]["text"]["text"]

    # Fields block exists and capped at 10
    assert blocks[2]["type"] == "section"
    assert len(blocks[2]["fields"]) == 10

    # Divider & Context
    assert blocks[3]["type"] == "divider"
    assert blocks[4]["type"] == "context"
    assert "Cycle: `cycle-456`" in blocks[4]["elements"][0]["text"]


def test_format_slack_payload_without_fields_or_cycle() -> None:
    """Test Slack payload when fields and cycle_id are omitted."""
    msg = NotificationMessage(
        title="Simple Alert",
        summary="Simple summary without fields",
    )
    payload = format_slack_payload(msg)
    blocks = payload["blocks"]

    # Block 0: Header, Block 1: Section, Block 2: Divider, Block 3: Context
    assert len(blocks) == 4
    assert blocks[0]["type"] == "header"
    assert blocks[1]["type"] == "section"
    assert blocks[2]["type"] == "divider"
    assert blocks[3]["type"] == "context"
    assert "Cycle:" not in blocks[3]["elements"][0]["text"]


def test_format_telegram_payload_html() -> None:
    """Test Telegram payload generation with HTML formatting and escaping."""
    msg = NotificationMessage(
        title="Game <Alert> & Update",
        summary="ECU vs UNC <Special Event>",
        details="Location <changed>",
        fields=[
            NotificationField("Field <A>", "Value & B"),
        ],
        footer="ECU Hockey <2026>",
    )

    payload = format_telegram_payload(msg, chat_id="123456", parse_mode="HTML")
    assert payload["chat_id"] == "123456"
    assert payload["parse_mode"] == "HTML"
    text = payload["text"]
    assert "<b>Game &lt;Alert&gt; &amp; Update</b>" in text
    assert "ECU vs UNC &lt;Special Event&gt;" in text
    assert "Location &lt;changed&gt;" in text
    assert "• <b>Field &lt;A&gt;:</b> Value &amp; B" in text
    assert "<i>ECU Hockey &lt;2026&gt;</i>" in text


def test_format_telegram_payload_markdown() -> None:
    """Test Telegram payload generation with Markdown formatting and escaping."""
    msg = NotificationMessage(
        title="Game [Alert] *bold*",
        summary="ECU `code` and _italic_",
        details="Details *here*",
        fields=[
            NotificationField("Field_1", "Value_2"),
        ],
        footer="Footer_Text",
    )

    payload = format_telegram_payload(
        msg,
        chat_id="@channel",
        parse_mode="Markdown",
    )
    assert payload["chat_id"] == "@channel"
    assert payload["parse_mode"] == "Markdown"
    text = payload["text"]
    assert "\\[Alert\\]" in text
    assert "\\*bold\\*" in text
    assert "\\_italic\\_" in text
    assert "\\`code\\`" in text
    assert "• *Field\\_1:* Value\\_2" in text


def test_format_telegram_payload_markdown_empty_details_and_fields() -> None:
    """Test Telegram Markdown formatting when details and fields are omitted."""
    msg = NotificationMessage(
        title="Simple Markdown Alert",
        summary="Short summary only",
    )
    payload = format_telegram_payload(
        msg,
        chat_id="123",
        parse_mode="Markdown",
    )
    text = payload["text"]
    assert "*Simple Markdown Alert*" in text
    assert "Short summary only" in text
    assert "•" not in text

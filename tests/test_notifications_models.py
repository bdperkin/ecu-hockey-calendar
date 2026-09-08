"""Unit tests for notification models, configuration, and message builders."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ecu_hockey_calendar.notifications.models import (
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    DispatchResult,
    MultiChannelDispatchSummary,
    NotificationChannel,
    NotificationConfig,
    NotificationField,
    NotificationMessage,
    NotificationSeverity,
    _extract_game_metadata,
    _format_datetime_human,
)
from ecu_hockey_calendar.reconciliation.models import (
    ChangeDetectionCycleResult,
    ConflictField,
    ConflictSeverity,
    DetectedConflict,
    DiscrepancyRecord,
    FieldDiff,
    GameChangeRecord,
    GameStateTransition,
)


def test_notification_enums() -> None:
    """Test notification channels and severities."""
    assert NotificationChannel.DISCORD.value == "discord"
    assert NotificationChannel.SLACK.value == "slack"
    assert NotificationChannel.TELEGRAM.value == "telegram"

    assert NotificationSeverity.INFO.value == "INFO"
    assert NotificationSeverity.SUCCESS.value == "SUCCESS"
    assert NotificationSeverity.WARNING.value == "WARNING"
    assert NotificationSeverity.ALERT.value == "ALERT"


def test_notification_field_to_dict() -> None:
    """Test NotificationField serialization."""
    field = NotificationField(title="Opponent", value="NC State", inline=True)
    d = field.to_dict()
    assert d == {"title": "Opponent", "value": "NC State", "inline": True}


def test_notification_config_defaults_and_env(
    monkeypatch: Any,
) -> None:
    """Test NotificationConfig default values and from_env population."""
    config_default = NotificationConfig()
    assert config_default.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert config_default.max_retries == DEFAULT_MAX_RETRIES
    assert config_default.backoff_factor == DEFAULT_BACKOFF_FACTOR
    assert not config_default.is_channel_configured(NotificationChannel.DISCORD)

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/abc")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100987654")
    monkeypatch.setenv("NOTIFICATION_TIMEOUT", "12.5")
    monkeypatch.setenv("NOTIFICATION_MAX_RETRIES", "5")
    monkeypatch.setenv("NOTIFICATION_BACKOFF_FACTOR", "1.2")
    monkeypatch.setenv("TELEGRAM_PARSE_MODE", "Markdown")

    config_env = NotificationConfig.from_env()
    assert config_env.discord_webhook_url == "https://discord.com/api/webhooks/123"
    assert config_env.slack_webhook_url == "https://hooks.slack.com/services/abc"
    assert config_env.telegram_bot_token == "123456:ABC"
    assert config_env.telegram_chat_id == "-100987654"
    assert config_env.timeout_seconds == 12.5
    assert config_env.max_retries == 5
    assert config_env.backoff_factor == 1.2
    assert config_env.parse_mode == "Markdown"

    assert config_env.is_channel_configured(NotificationChannel.DISCORD)
    assert config_env.is_channel_configured(NotificationChannel.SLACK)
    assert config_env.is_channel_configured(NotificationChannel.TELEGRAM)
    assert config_env.configured_channels == {
        NotificationChannel.DISCORD,
        NotificationChannel.SLACK,
        NotificationChannel.TELEGRAM,
    }


def test_notification_config_partial_and_filtering() -> None:
    """Test channel filtering and partial Telegram credentials."""
    # Telegram only token
    config_partial = NotificationConfig(telegram_bot_token="token_only")
    assert not config_partial.is_channel_configured(NotificationChannel.TELEGRAM)

    # Telegram only chat id
    config_partial2 = NotificationConfig(telegram_chat_id="chat_only")
    assert not config_partial2.is_channel_configured(
        NotificationChannel.TELEGRAM,
    )

    # Enabled channels subset
    config = NotificationConfig(
        discord_webhook_url="https://discord.com/webhook",
        slack_webhook_url="https://slack.com/webhook",
        enabled_channels={NotificationChannel.DISCORD},
    )
    assert config.configured_channels == {NotificationChannel.DISCORD}


def test_format_datetime_human() -> None:
    """Test datetime human-friendly formatting."""
    assert _format_datetime_human(None) == "TBD"

    dt = datetime(2026, 10, 9, 19, 30, tzinfo=UTC)
    formatted = _format_datetime_human(dt)
    assert "Fri, Oct 9, 2026 @" in formatted
    assert "7:30 PM" in formatted

    iso_str = "2026-10-09T19:30:00+00:00"
    assert _format_datetime_human(iso_str) == formatted

    invalid_str = "not-a-valid-datetime"
    assert _format_datetime_human(invalid_str) == "not-a-valid-datetime"


def test_extract_game_metadata() -> None:
    """Test game metadata extraction helper."""
    opp, is_home, venue, status, start_time = _extract_game_metadata(None)
    assert opp == "Unknown Opponent"
    assert is_home is True
    assert venue == "TBD"
    assert status == "SCHEDULED"
    assert start_time == "TBD"

    snapshot = {
        "opponent_name": "UNC Tar Heels",
        "is_home": False,
        "venue": "Orange County Sportsplex",
        "status": "FINAL",
        "start_time": "2026-10-10T19:00:00+00:00",
    }
    opp2, is_home2, venue2, status2, start2 = _extract_game_metadata(snapshot)
    assert opp2 == "UNC Tar Heels"
    assert is_home2 is False
    assert venue2 == "Orange County Sportsplex"
    assert status2 == "FINAL"
    assert "Oct 10, 2026" in start2


def test_build_created_message() -> None:
    """Test message construction for CREATED transition."""
    change = GameChangeRecord(
        canonical_game_id="ecu-unc-20261010",
        state_transition=GameStateTransition.CREATED,
        current_snapshot={
            "opponent_name": "UNC Tar Heels",
            "is_home": True,
            "venue": "The Factory Wake Forest",
            "status": "SCHEDULED",
            "start_time": "2026-10-10T19:00:00+00:00",
        },
    )

    msg = NotificationMessage.from_change_record(change, cycle_id="cycle-001")
    assert "New Game Scheduled: vs UNC Tar Heels" in msg.title
    assert "added to the ECU Hockey schedule" in msg.summary
    assert msg.severity == NotificationSeverity.SUCCESS
    assert msg.transition == GameStateTransition.CREATED
    assert msg.canonical_game_id == "ecu-unc-20261010"
    assert msg.cycle_id == "cycle-001"
    assert any(f.title == "Opponent" and f.value == "UNC Tar Heels" for f in msg.fields)


def test_build_updated_message() -> None:
    """Test message construction for UPDATED transition."""
    diff = FieldDiff(
        field_name="start_time",
        old_value="19:00",
        new_value="20:30",
        human_description="Start time shifted from 7:00 PM to 8:30 PM",
    )
    change = GameChangeRecord(
        canonical_game_id="ecu-ncstate-20261017",
        state_transition=GameStateTransition.UPDATED,
        field_diffs=[diff],
        current_snapshot={
            "opponent_name": "NC State Icepack",
            "is_home": False,
            "venue": "Invisalign Arena",
            "status": "SCHEDULED",
            "start_time": "2026-10-17T20:30:00+00:00",
        },
    )

    msg = NotificationMessage.from_change_record(change)
    assert "Schedule Update: @ NC State Icepack" in msg.title
    assert "Start time shifted" in msg.details
    assert msg.severity == NotificationSeverity.INFO
    assert msg.transition == GameStateTransition.UPDATED
    assert any(
        f.title == "Changes" and "Start time shifted" in f.value for f in msg.fields
    )

    # Empty diffs fallback to human_summary
    change_empty_diffs = GameChangeRecord(
        canonical_game_id="ecu-ncstate-20261017",
        state_transition=GameStateTransition.UPDATED,
        field_diffs=[],
        human_summary="Updated via fallback summary",
        previous_snapshot={
            "opponent_name": "NC State Icepack",
            "is_home": True,
        },
    )
    msg2 = NotificationMessage.from_change_record(change_empty_diffs)
    assert msg2.details == "Updated via fallback summary"


def test_build_deleted_message() -> None:
    """Test message construction for DELETED transition."""
    change = GameChangeRecord(
        canonical_game_id="ecu-duke-20261024",
        state_transition=GameStateTransition.DELETED,
        previous_snapshot={
            "opponent_name": "Duke Blue Devils",
            "is_home": True,
            "venue": "The Factory",
            "status": "CANCELLED",
            "start_time": "2026-10-24T19:00:00+00:00",
        },
    )

    msg = NotificationMessage.from_change_record(change)
    assert "Game Cancelled / Postponed: vs Duke Blue Devils" in msg.title
    assert msg.severity == NotificationSeverity.ALERT
    assert msg.transition == GameStateTransition.DELETED
    assert any(f.title == "Original Date" for f in msg.fields)


def test_build_conflict_message() -> None:
    """Test message construction for CONFLICT_DETECTED transition."""
    conflict = DetectedConflict(
        conflict_id="conf-1",
        game_key="game-key",
        field=ConflictField.START_TIME,
        severity=ConflictSeverity.HIGH,
        discrepancies=[
            DiscrepancyRecord(
                field=ConflictField.START_TIME,
                source_a="ecuhockey",
                source_b="acchockey",
                value_a="19:00",
                value_b="20:00",
            ),
        ],
    )
    change = GameChangeRecord(
        canonical_game_id="ecu-vt-20261101",
        state_transition=GameStateTransition.CONFLICT_DETECTED,
        detected_conflicts=[conflict],
        current_snapshot={
            "opponent_name": "Virginia Tech",
            "is_home": True,
            "venue": "The Factory",
            "start_time": "2026-11-01T19:00:00+00:00",
        },
    )

    msg = NotificationMessage.from_change_record(change)
    assert "Schedule Conflict Detected: vs Virginia Tech" in msg.title
    assert msg.severity == NotificationSeverity.WARNING
    assert "Conflict on 'start_time':" in msg.details
    assert "ecuhockey (19:00) vs acchockey (20:00)" in msg.details

    # Empty conflicts fallback
    change_no_conf = GameChangeRecord(
        canonical_game_id="ecu-vt-20261101",
        state_transition=GameStateTransition.CONFLICT_DETECTED,
        human_summary="Manual conflict summary",
        detected_conflicts=[],
        previous_snapshot={"opponent_name": "Virginia Tech"},
    )
    msg2 = NotificationMessage.from_change_record(change_no_conf)
    assert msg2.details == "Manual conflict summary"


def test_build_unchanged_message() -> None:
    """Test message construction for UNCHANGED transition."""
    change = GameChangeRecord(
        canonical_game_id="ecu-unc-20261010",
        state_transition=GameStateTransition.UNCHANGED,
        current_snapshot={"opponent_name": "UNC Tar Heels"},
    )
    msg = NotificationMessage.from_change_record(change)
    assert "Game Unchanged: vs UNC Tar Heels" in msg.title
    assert msg.severity == NotificationSeverity.INFO


def test_from_cycle_result() -> None:
    """Test message construction from ChangeDetectionCycleResult."""
    # With conflicts
    conflict_change = GameChangeRecord(
        canonical_game_id="g1",
        state_transition=GameStateTransition.CONFLICT_DETECTED,
    )
    cycle_with_conflict = ChangeDetectionCycleResult(
        cycle_id="cycle-conf",
        changes=[conflict_change],
    )
    msg_conf = NotificationMessage.from_cycle_result(cycle_with_conflict)
    assert msg_conf.severity == NotificationSeverity.WARNING
    assert "1 Change(s)" in msg_conf.title

    # With changes only (success)
    created_change = GameChangeRecord(
        canonical_game_id="g2",
        state_transition=GameStateTransition.CREATED,
    )
    cycle_created = ChangeDetectionCycleResult(
        cycle_id="cycle-succ",
        changes=[created_change],
    )
    msg_succ = NotificationMessage.from_cycle_result(cycle_created)
    assert msg_succ.severity == NotificationSeverity.SUCCESS

    # With 0 changes (info)
    unchanged_change = GameChangeRecord(
        canonical_game_id="g3",
        state_transition=GameStateTransition.UNCHANGED,
    )
    cycle_unchanged = ChangeDetectionCycleResult(
        cycle_id="cycle-info",
        changes=[unchanged_change],
    )
    msg_info = NotificationMessage.from_cycle_result(cycle_unchanged)
    assert msg_info.severity == NotificationSeverity.INFO


def test_notification_message_to_dict() -> None:
    """Test NotificationMessage serialization."""
    msg = NotificationMessage(
        title="Title",
        summary="Summary",
        details="Details",
        transition=GameStateTransition.CREATED,
        severity=NotificationSeverity.SUCCESS,
        fields=[NotificationField("Key", "Value")],
        event_url="https://ecuhockey.com",
        cycle_id="cycle-1",
        canonical_game_id="game-1",
    )
    d = msg.to_dict()
    assert d["title"] == "Title"
    assert d["summary"] == "Summary"
    assert d["details"] == "Details"
    assert d["transition"] == "CREATED"
    assert d["severity"] == "SUCCESS"
    assert d["event_url"] == "https://ecuhockey.com"
    assert d["cycle_id"] == "cycle-1"
    assert d["canonical_game_id"] == "game-1"
    assert len(d["fields"]) == 1


def test_dispatch_result_and_summary_to_dict() -> None:
    """Test DispatchResult and MultiChannelDispatchSummary."""
    res_disc = DispatchResult(
        channel=NotificationChannel.DISCORD,
        success=True,
        status_code=204,
        attempts=1,
    )
    res_slack = DispatchResult(
        channel=NotificationChannel.SLACK,
        success=False,
        status_code=500,
        attempts=3,
        error_message="Server error",
    )

    summary = MultiChannelDispatchSummary(
        results=[res_disc, res_slack],
        cycle_id="cycle-99",
        message_title="Alert Title",
    )

    assert summary.successful_channels == [NotificationChannel.DISCORD]
    assert summary.failed_channels == [NotificationChannel.SLACK]
    assert summary.all_successful is False

    d = summary.to_dict()
    assert d["cycle_id"] == "cycle-99"
    assert d["message_title"] == "Alert Title"
    assert d["all_successful"] is False
    assert d["successful_channels"] == ["discord"]
    assert d["failed_channels"] == ["slack"]
    assert len(d["results"]) == 2

    # All successful case
    summary_all = MultiChannelDispatchSummary(results=[res_disc])
    assert summary_all.all_successful is True

    # Empty results case
    summary_empty = MultiChannelDispatchSummary(results=[])
    assert summary_empty.all_successful is False

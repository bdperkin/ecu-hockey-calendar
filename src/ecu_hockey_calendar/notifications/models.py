"""Domain models and configuration dataclasses for multi-platform notifications."""

from __future__ import annotations

import os
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ecu_hockey_calendar.reconciliation.models import (
    ChangeDetectionCycleResult,
    GameChangeRecord,
    GameStateTransition,
)

if TYPE_CHECKING:
    from ecu_hockey_calendar.reconciliation.models import (
        DetectedConflict,
        FieldDiff,
    )

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 0.5
DEFAULT_TELEGRAM_PARSE_MODE = "HTML"
DEFAULT_NOTIFICATION_FOOTER = "ECU Hockey Schedule Aggregator"


class NotificationChannel(StrEnum):
    """Supported multi-platform notification channels."""

    DISCORD = "discord"
    SLACK = "slack"
    TELEGRAM = "telegram"


class NotificationSeverity(StrEnum):
    """Urgency and severity level for dispatched notifications."""

    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ALERT = "ALERT"


@dataclass(frozen=True)
class NotificationField:
    """Key-value pair for structured embed and block fields."""

    title: str
    value: str
    inline: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize notification field to dictionary representation.

        Returns:
            Dictionary with title, value, and inline properties.
        """
        return {"title": self.title, "value": self.value, "inline": self.inline}


@dataclass
class NotificationConfig:
    """Configuration settings and credentials for multi-channel webhook alerting."""

    discord_webhook_url: str | None = None
    slack_webhook_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR
    enabled_channels: set[NotificationChannel] | None = None
    parse_mode: str = DEFAULT_TELEGRAM_PARSE_MODE

    @classmethod
    def from_env(cls) -> NotificationConfig:
        """Construct configuration instance populated from environment variables.

        Returns:
            Configured NotificationConfig instance.
        """
        raw_timeout = os.environ.get("NOTIFICATION_TIMEOUT")
        timeout = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_SECONDS

        raw_retries = os.environ.get("NOTIFICATION_MAX_RETRIES")
        retries = int(raw_retries) if raw_retries else DEFAULT_MAX_RETRIES

        raw_backoff = os.environ.get("NOTIFICATION_BACKOFF_FACTOR")
        backoff = float(raw_backoff) if raw_backoff else DEFAULT_BACKOFF_FACTOR

        return cls(
            discord_webhook_url=os.environ.get("DISCORD_WEBHOOK_URL"),
            slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL"),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
            timeout_seconds=timeout,
            max_retries=retries,
            backoff_factor=backoff,
            parse_mode=os.environ.get(
                "TELEGRAM_PARSE_MODE",
                DEFAULT_TELEGRAM_PARSE_MODE,
            ),
        )

    def is_channel_configured(self, channel: NotificationChannel) -> bool:
        """Verify whether credentials and endpoints exist for a specific channel.

        Args:
            channel: Target notification channel.

        Returns:
            True if all required credentials exist, False otherwise.
        """
        if channel == NotificationChannel.DISCORD:
            return bool(self.discord_webhook_url)

        if channel == NotificationChannel.SLACK:
            return bool(self.slack_webhook_url)

        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def configured_channels(self) -> set[NotificationChannel]:
        """Return subset of channels that are both configured and enabled.

        Returns:
            Set of active NotificationChannel enums.
        """
        active: set[NotificationChannel] = set()
        for ch in NotificationChannel:
            if not self.is_channel_configured(ch):
                continue

            if self.enabled_channels is not None and ch not in self.enabled_channels:
                continue

            active.add(ch)

        return active


def _format_datetime_human(dt_val: datetime | str | None) -> str:
    """Format datetime cleanly for notification readability."""
    if dt_val is None:
        return "TBD"

    parsed_dt: datetime
    if isinstance(dt_val, str):
        try:
            parsed_dt = datetime.fromisoformat(dt_val)
        except ValueError:
            return dt_val
    else:
        parsed_dt = dt_val

    month = parsed_dt.strftime("%b")
    weekday = parsed_dt.strftime("%a")
    day = parsed_dt.day
    year = parsed_dt.year
    hour = parsed_dt.strftime("%I").lstrip("0") or "12"
    minute = parsed_dt.strftime("%M")
    am_pm = parsed_dt.strftime("%p")
    return f"{weekday}, {month} {day}, {year} @ {hour}:{minute} {am_pm}"


def _extract_game_metadata(
    snapshot: dict[str, Any] | None,
) -> tuple[str, bool, str, str, str]:
    """Extract standard attributes from game snapshot dictionary."""
    if not snapshot:
        return "Unknown Opponent", True, "TBD", "SCHEDULED", "TBD"

    opponent = str(snapshot.get("opponent_name", "Unknown Opponent"))
    is_home = bool(snapshot.get("is_home", True))
    venue = str(snapshot.get("venue", "TBD"))
    status = str(snapshot.get("status", "SCHEDULED"))
    start_time = _format_datetime_human(snapshot.get("start_time"))
    return opponent, is_home, venue, status, start_time


def _build_created_message(
    change: GameChangeRecord,
    cycle_id: str | None,
) -> NotificationMessage:
    """Build notification message for newly created game."""
    opponent, is_home, venue, status, start_time = _extract_game_metadata(
        change.current_snapshot,
    )
    loc_prefix = "vs" if is_home else "@"
    loc_name = "Home" if is_home else "Away"

    fields = [
        NotificationField("Opponent", opponent, inline=True),
        NotificationField("Date & Time", start_time, inline=True),
        NotificationField("Location", loc_name, inline=True),
        NotificationField("Venue", venue, inline=False),
        NotificationField("Status", status, inline=True),
    ]

    return NotificationMessage(
        title=f"🆕 New Game Scheduled: {loc_prefix} {opponent}",
        summary=(
            f"A new game against {opponent} has been added to the ECU Hockey schedule."
        ),
        transition=GameStateTransition.CREATED,
        severity=NotificationSeverity.SUCCESS,
        fields=fields,
        canonical_game_id=change.canonical_game_id,
        cycle_id=cycle_id,
        timestamp=change.recorded_at,
    )


def _format_diff_details(
    diffs: list[FieldDiff],
    fallback: str,
) -> tuple[str, str]:
    """Format human details and diff summary string."""
    if not diffs:
        return fallback, ""

    details = "\n".join(f"• {d.human_description}" for d in diffs)
    summary = "; ".join(d.human_description for d in diffs)
    return details, summary


def _build_updated_message(
    change: GameChangeRecord,
    cycle_id: str | None,
) -> NotificationMessage:
    """Build notification message for updated game."""
    snapshot = change.current_snapshot or change.previous_snapshot
    opponent, is_home, venue, status, start_time = _extract_game_metadata(snapshot)
    loc_prefix = "vs" if is_home else "@"
    details, diff_summary = _format_diff_details(
        change.field_diffs,
        change.human_summary,
    )

    fields = [
        NotificationField("Opponent", opponent, inline=True),
        NotificationField("Date & Time", start_time, inline=True),
        NotificationField("Venue", venue, inline=False),
        NotificationField("Status", status, inline=True),
    ]
    if diff_summary:
        fields.append(NotificationField("Changes", diff_summary, inline=False))

    return NotificationMessage(
        title=f"🔄 Schedule Update: {loc_prefix} {opponent}",
        summary=f"Schedule changes were detected for game {loc_prefix} {opponent}.",
        details=details,
        transition=GameStateTransition.UPDATED,
        severity=NotificationSeverity.INFO,
        fields=fields,
        canonical_game_id=change.canonical_game_id,
        cycle_id=cycle_id,
        timestamp=change.recorded_at,
    )


def _build_deleted_message(
    change: GameChangeRecord,
    cycle_id: str | None,
) -> NotificationMessage:
    """Build notification message for deleted or cancelled game."""
    opponent, is_home, venue, _, start_time = _extract_game_metadata(
        change.previous_snapshot,
    )
    loc_prefix = "vs" if is_home else "@"

    fields = [
        NotificationField("Opponent", opponent, inline=True),
        NotificationField("Original Date", start_time, inline=True),
        NotificationField("Venue", venue, inline=False),
    ]

    return NotificationMessage(
        title=f"❌ Game Cancelled / Postponed: {loc_prefix} {opponent}",
        summary=(
            f"Game {loc_prefix} {opponent} on {start_time} has been "
            "cancelled or removed from the active schedule."
        ),
        transition=GameStateTransition.DELETED,
        severity=NotificationSeverity.ALERT,
        fields=fields,
        canonical_game_id=change.canonical_game_id,
        cycle_id=cycle_id,
        timestamp=change.recorded_at,
    )


def _format_conflict_details(
    conflicts: list[DetectedConflict],
    fallback: str,
) -> tuple[str, str]:
    """Format conflict details and comma-separated field names."""
    if not conflicts:
        return fallback, "Unknown field"

    names = ", ".join(c.field.value for c in conflicts)
    lines: list[str] = []
    for c in conflicts:
        lines.append(f"• Conflict on '{c.field.value}':")
        lines.extend(
            f"  - {d.source_a} ({d.value_a}) vs {d.source_b} ({d.value_b})"
            for d in c.discrepancies
        )

    return "\n".join(lines), names


def _build_conflict_message(
    change: GameChangeRecord,
    cycle_id: str | None,
) -> NotificationMessage:
    """Build notification message for detected conflict."""
    snapshot = change.current_snapshot or change.previous_snapshot
    opponent, is_home, venue, _, start_time = _extract_game_metadata(snapshot)
    loc_prefix = "vs" if is_home else "@"
    details, conflicts_str = _format_conflict_details(
        change.detected_conflicts,
        change.human_summary,
    )

    fields = [
        NotificationField("Opponent", opponent, inline=True),
        NotificationField("Date & Time", start_time, inline=True),
        NotificationField("Venue", venue, inline=False),
        NotificationField("Conflicting Fields", conflicts_str, inline=False),
    ]

    return NotificationMessage(
        title=f"⚠️ Schedule Conflict Detected: {loc_prefix} {opponent}",
        summary=(
            f"Discrepancies across data sources for game {loc_prefix} "
            f"{opponent} require administrator review."
        ),
        details=details,
        transition=GameStateTransition.CONFLICT_DETECTED,
        severity=NotificationSeverity.WARNING,
        fields=fields,
        canonical_game_id=change.canonical_game_id,
        cycle_id=cycle_id,
        timestamp=change.recorded_at,
    )


def _build_unchanged_message(
    change: GameChangeRecord,
    cycle_id: str | None,
) -> NotificationMessage:
    """Build notification message for unchanged game."""
    opponent, is_home, venue, status, start_time = _extract_game_metadata(
        change.current_snapshot or change.previous_snapshot,
    )
    loc_prefix = "vs" if is_home else "@"

    fields = [
        NotificationField("Opponent", opponent, inline=True),
        NotificationField("Date & Time", start_time, inline=True),
        NotificationField("Venue", venue, inline=False),
        NotificationField("Status", status, inline=True),
    ]

    return NotificationMessage(
        title=f"Game Unchanged: {loc_prefix} {opponent}",
        summary=f"No changes detected for game {loc_prefix} {opponent}.",
        transition=GameStateTransition.UNCHANGED,
        severity=NotificationSeverity.INFO,
        fields=fields,
        canonical_game_id=change.canonical_game_id,
        cycle_id=cycle_id,
        timestamp=change.recorded_at,
    )


@dataclass
class NotificationMessage:
    """Platform-agnostic notification event representation."""

    title: str
    summary: str
    details: str = ""
    transition: GameStateTransition | None = None
    severity: NotificationSeverity = NotificationSeverity.INFO
    fields: list[NotificationField] = dataclass_field(default_factory=list)
    timestamp: datetime = dataclass_field(default_factory=lambda: datetime.now(UTC))
    event_url: str | None = None
    footer: str = DEFAULT_NOTIFICATION_FOOTER
    canonical_game_id: str | None = None
    cycle_id: str | None = None

    @classmethod
    def from_change_record(
        cls,
        change: GameChangeRecord,
        *,
        cycle_id: str | None = None,
    ) -> NotificationMessage:
        """Construct a structured notification message from a GameChangeRecord.

        Args:
            change: Atomic game change record.
            cycle_id: Optional sync cycle identifier.

        Returns:
            Populated NotificationMessage instance.
        """
        if change.state_transition == GameStateTransition.CREATED:
            return _build_created_message(change, cycle_id)

        if change.state_transition == GameStateTransition.UPDATED:
            return _build_updated_message(change, cycle_id)

        if change.state_transition == GameStateTransition.DELETED:
            return _build_deleted_message(change, cycle_id)

        if change.state_transition == GameStateTransition.CONFLICT_DETECTED:
            return _build_conflict_message(change, cycle_id)

        return _build_unchanged_message(change, cycle_id)

    @classmethod
    def from_cycle_result(
        cls,
        cycle: ChangeDetectionCycleResult,
    ) -> NotificationMessage:
        """Construct a summary notification message from a full change cycle.

        Args:
            cycle: Synchronization cycle result.

        Returns:
            NotificationMessage summarizing cycle metrics.
        """
        fields = [
            NotificationField("Created", str(len(cycle.created_games)), inline=True),
            NotificationField("Updated", str(len(cycle.updated_games)), inline=True),
            NotificationField("Deleted", str(len(cycle.deleted_games)), inline=True),
            NotificationField(
                "Conflicts",
                str(len(cycle.conflict_games)),
                inline=True,
            ),
            NotificationField(
                "Unchanged",
                str(len(cycle.unchanged_games)),
                inline=True,
            ),
            NotificationField(
                "Total Changes",
                str(cycle.total_changes),
                inline=True,
            ),
        ]

        if cycle.conflict_games:
            severity = NotificationSeverity.WARNING
        elif cycle.total_changes > 0:
            severity = NotificationSeverity.SUCCESS
        else:
            severity = NotificationSeverity.INFO

        title = f"🏒 Sync Cycle Summary: {cycle.total_changes} Change(s)"
        summary = (
            f"Schedule synchronization cycle {cycle.cycle_id} completed with "
            f"{cycle.total_changes} atomic change(s) detected."
        )

        return cls(
            title=title,
            summary=summary,
            severity=severity,
            fields=fields,
            cycle_id=cycle.cycle_id,
            timestamp=cycle.completed_at,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize notification message to dictionary representation.

        Returns:
            Dictionary representation of the notification message.
        """
        return {
            "title": self.title,
            "summary": self.summary,
            "details": self.details,
            "transition": self.transition.value if self.transition else None,
            "severity": self.severity.value,
            "fields": [f.to_dict() for f in self.fields],
            "timestamp": self.timestamp.isoformat(),
            "event_url": self.event_url,
            "footer": self.footer,
            "canonical_game_id": self.canonical_game_id,
            "cycle_id": self.cycle_id,
        }


@dataclass
class DispatchResult:
    """Outcome of dispatching a notification message to a specific channel."""

    channel: NotificationChannel
    success: bool
    status_code: int | None = None
    attempts: int = 1
    error_message: str | None = None
    dispatched_at: datetime = dataclass_field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialize dispatch result to dictionary representation.

        Returns:
            Dictionary representation of the dispatch result.
        """
        return {
            "channel": self.channel.value,
            "success": self.success,
            "status_code": self.status_code,
            "attempts": self.attempts,
            "error_message": self.error_message,
            "dispatched_at": self.dispatched_at.isoformat(),
        }


@dataclass
class MultiChannelDispatchSummary:
    """Aggregated results from dispatching notifications across all channels."""

    results: list[DispatchResult] = dataclass_field(default_factory=list)
    cycle_id: str | None = None
    message_title: str = ""

    @property
    def successful_channels(self) -> list[NotificationChannel]:
        """Return list of channels where dispatch was successful.

        Returns:
            List of successfully notified channels.
        """
        return [r.channel for r in self.results if r.success]

    @property
    def failed_channels(self) -> list[NotificationChannel]:
        """Return list of channels where dispatch failed.

        Returns:
            List of channels that encountered dispatch errors.
        """
        return [r.channel for r in self.results if not r.success]

    @property
    def all_successful(self) -> bool:
        """Indicate whether all targeted channels succeeded.

        Returns:
            True if all results succeeded, False otherwise.
        """
        return bool(self.results) and all(r.success for r in self.results)

    def to_dict(self) -> dict[str, Any]:
        """Serialize dispatch summary to dictionary representation.

        Returns:
            Dictionary representation of multi-channel dispatch summary.
        """
        return {
            "cycle_id": self.cycle_id,
            "message_title": self.message_title,
            "all_successful": self.all_successful,
            "successful_channels": [c.value for c in self.successful_channels],
            "failed_channels": [c.value for c in self.failed_channels],
            "results": [r.to_dict() for r in self.results],
        }


__all__ = [
    "DEFAULT_BACKOFF_FACTOR",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_NOTIFICATION_FOOTER",
    "DEFAULT_TELEGRAM_PARSE_MODE",
    "DEFAULT_TIMEOUT_SECONDS",
    "DispatchResult",
    "MultiChannelDispatchSummary",
    "NotificationChannel",
    "NotificationConfig",
    "NotificationField",
    "NotificationMessage",
    "NotificationSeverity",
]

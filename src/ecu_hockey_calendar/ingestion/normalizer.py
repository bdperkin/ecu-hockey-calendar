"""Data normalization utilities for schedule ingestion."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ecu_hockey_calendar.storage.models import GameStatus

DEFAULT_TIMEZONE = "America/New_York"

# Canonical team name aliases
_TEAM_NAME_MAP: dict[str, str] = {
    "ecu": "East Carolina University",
    "east carolina": "East Carolina University",
    "east carolina univ": "East Carolina University",
    "east carolina university": "East Carolina University",
    "uncw": "UNC Wilmington",
    "unc-wilmington": "UNC Wilmington",
    "unc wilmington": "UNC Wilmington",
    "unc": "UNC Chapel Hill",
    "unc chapel hill": "UNC Chapel Hill",
    "unc-chapel hill": "UNC Chapel Hill",
    "nc state": "NC State University",
    "nc state university": "NC State University",
    "app state": "Appalachian State University",
    "appalachian state": "Appalachian State University",
    "appalachian state university": "Appalachian State University",
    "vt": "Virginia Tech",
    "virginia tech": "Virginia Tech",
    "alabama": "University of Alabama",
    "alabama d2": "University of Alabama (D2)",
    "alabama d3": "University of Alabama (D3)",
    "wake forest": "Wake Forest University",
    "high point": "High Point University",
    "duke": "Duke University",
}


def normalize_team_name(name: str) -> str:
    """Normalize a team or opponent name into canonical format.

    Args:
        name: Raw team name string from upstream sources.

    Returns:
        Cleaned, canonical team name.
    """
    cleaned = re.sub(r"\s+", " ", name).strip()
    if not cleaned:
        return ""

    lookup_key = cleaned.lower()
    if lookup_key in _TEAM_NAME_MAP:
        return _TEAM_NAME_MAP[lookup_key]

    # Clean prefixes like "vs. " or "@ "
    cleaned = re.sub(r"^(vs\.?|@)\s*", "", cleaned, flags=re.IGNORECASE).strip()
    lookup_key = cleaned.lower()
    if lookup_key in _TEAM_NAME_MAP:
        return _TEAM_NAME_MAP[lookup_key]

    return cleaned


HOURS_PER_HALF_DAY = 12


def _convert_12h_time(hour: int, minute: int, meridiem: str) -> tuple[int, int]:
    """Convert 12-hour time components to 24-hour hour and minute."""
    if meridiem.upper() == "PM" and hour < HOURS_PER_HALF_DAY:
        return hour + HOURS_PER_HALF_DAY, minute

    if meridiem.upper() == "AM" and hour == HOURS_PER_HALF_DAY:
        return 0, minute

    return hour, minute


def _parse_time_parts(time_str: str | None) -> tuple[int, int]:
    """Parse time string into hour and minute components.

    Args:
        time_str: Raw time string (e.g., "7:00 PM", "19:30", "7:00pm").

    Returns:
        Tuple of (hour, minute) in 24-hour format. Defaults to (19, 0) if unparsable.
    """
    if not time_str or time_str.strip().upper() in {"TBD", "TBA", ""}:
        return 19, 0

    cleaned = time_str.strip()
    match_12h = re.match(r"^(\d{1,2}):(\d{2})\s*([AP]M)$", cleaned, re.IGNORECASE)
    if match_12h:
        return _convert_12h_time(
            int(match_12h.group(1)),
            int(match_12h.group(2)),
            match_12h.group(3),
        )

    match_24h = re.match(r"^(\d{1,2}):(\d{2})$", cleaned)
    if match_24h:
        return int(match_24h.group(1)), int(match_24h.group(2))

    return 19, 0


def _parse_textual_date(cleaned: str) -> tuple[int, int, int] | None:
    """Parse textual month representations like 'September 4, 2026'."""
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
        try:
            parsed = datetime.strptime(cleaned, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
        else:
            return parsed.year, parsed.month, parsed.day

    return None


def _parse_date_components(date_str: str) -> tuple[int, int, int]:
    """Extract year, month, and day integers from various date formats.

    Args:
        date_str: Raw date string.

    Returns:
        Tuple of (year, month, day).

    Raises:
        ValueError: If date cannot be parsed.
    """
    cleaned = date_str.strip()

    # ISO format YYYY-MM-DD
    match_iso = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", cleaned)
    if match_iso:
        return int(match_iso.group(1)), int(match_iso.group(2)), int(match_iso.group(3))

    # US format MM/DD/YYYY or MM-DD-YYYY
    match_us = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})", cleaned)
    if match_us:
        return int(match_us.group(3)), int(match_us.group(1)), int(match_us.group(2))

    text_parsed = _parse_textual_date(cleaned)
    if text_parsed:
        return text_parsed

    msg = f"Unrecognized date format: {date_str!r}"
    raise ValueError(msg)


def parse_game_datetime(
    date_str: str,
    time_str: str | None = None,
    tz_name: str = DEFAULT_TIMEZONE,
) -> datetime:
    """Parse date and optional time strings into a timezone-aware UTC datetime.

    Args:
        date_str: Date string in ISO, US, or textual month format.
        time_str: Optional time string (e.g., "7:00 PM", "19:00", "TBD").
        tz_name: Timezone of the source venue/schedule (default: America/New_York).

    Returns:
        Timezone-aware datetime in UTC.
    """
    year, month, day = _parse_date_components(date_str)
    hour, minute = _parse_time_parts(time_str)
    tz = ZoneInfo(tz_name)
    local_dt = datetime(year, month, day, hour, minute, tzinfo=tz)
    return local_dt.astimezone(UTC)


def parse_game_score(
    score_str: str | None,
) -> tuple[int | None, int | None, str | None]:
    """Parse raw game score string into home score, away score, and overtime note.

    Args:
        score_str: Raw score text (e.g., "5 - 3", "4-5 (OT)", "3-2 (SO)", "0-0").

    Returns:
        Tuple of (home_score, away_score, overtime_note).
    """
    if not score_str or not score_str.strip():
        return None, None, None

    cleaned = score_str.strip()
    match = re.search(
        r"(\d+)\s*[-:\u2013]\s*(\d+)(?:\s*\((OT|SO|2OT|F/OT|F/SO)\))?",
        cleaned,
        re.IGNORECASE,
    )
    if not match:
        return None, None, None

    s1 = int(match.group(1))
    s2 = int(match.group(2))
    raw_ot = match.group(3)
    overtime_note: str | None = str(raw_ot).upper() if raw_ot is not None else None
    return s1, s2, overtime_note


STATUS_MAPPING: dict[str, GameStatus] = {
    "final": GameStatus.FINAL,
    "finished": GameStatus.FINAL,
    "completed": GameStatus.FINAL,
    "postponed": GameStatus.POSTPONED,
    "delayed": GameStatus.POSTPONED,
    "cancelled": GameStatus.CANCELLED,
    "canceled": GameStatus.CANCELLED,
    "forfeit": GameStatus.CANCELLED,
    "in progress": GameStatus.IN_PROGRESS,
    "live": GameStatus.IN_PROGRESS,
    "ongoing": GameStatus.IN_PROGRESS,
}


def parse_game_status(
    status_str: str | None,
    *,
    has_score: bool = False,
) -> GameStatus:
    """Determine normalized GameStatus from raw status text or score presence.

    Args:
        status_str: Status text from source (e.g., "final", "scheduled", "postponed").
        has_score: Whether non-zero scores were found for the game.

    Returns:
        Normalized GameStatus enum value.
    """
    default_status = GameStatus.FINAL if has_score else GameStatus.SCHEDULED
    if not status_str or not status_str.strip():
        return default_status

    cleaned = status_str.strip().lower()
    return STATUS_MAPPING.get(cleaned, default_status)


__all__ = [
    "DEFAULT_TIMEZONE",
    "normalize_team_name",
    "parse_game_datetime",
    "parse_game_score",
    "parse_game_status",
]

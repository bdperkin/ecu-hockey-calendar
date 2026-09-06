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
    "elon": "Elon University",
    "elon university": "Elon University",
    "charlotte": "UNC Charlotte",
    "unc charlotte": "UNC Charlotte",
    "georgetown": "Georgetown University",
    "georgetown university": "Georgetown University",
    "st joseph's": "Saint Joseph's University",
    "st. joseph's": "Saint Joseph's University",
    "saint joseph's": "Saint Joseph's University",
    "saint joseph's university": "Saint Joseph's University",
    "james madison": "James Madison University",
    "james madison university": "James Madison University",
    "james madison m2": "James Madison University (M2)",
    "jmu": "James Madison University",
    "ga tech": "Georgia Tech",
    "georgia tech": "Georgia Tech",
    "clemson": "Clemson University",
    "clemson university": "Clemson University",
    "saint thomas": "St. Thomas University",
    "st thomas": "St. Thomas University",
    "st. thomas": "St. Thomas University",
    "st. thomas university": "St. Thomas University",
    "richmond": "University of Richmond",
    "university of richmond": "University of Richmond",
    "rowan": "Rowan University",
    "rowan university": "Rowan University",
    "virginia": "University of Virginia",
    "uva": "University of Virginia",
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
        time_str: Raw time string (e.g., "7:00 PM", "19:30", "8:45 PM EST").

    Returns:
        Tuple of (hour, minute) in 24-hour format. Defaults to (19, 0) if unparsable.
    """
    if not time_str or time_str.strip().upper() in {"TBD", "TBA", "", "-"}:
        return 19, 0

    cleaned = time_str.strip()
    cleaned = re.sub(
        r"\b(EST|EDT|ET|CST|CDT|CT|MST|MDT|MT|PST|PDT|PT|UTC)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

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


COLLEGIATE_SEASON_START_MONTH = 8


def _resolve_season_year(
    month: int,
    season: str | None,
    default_year: int | None,
) -> int:
    """Determine calendar year based on month and collegiate hockey season."""
    if season and "-" in season:
        parts = season.split("-")
        start_yr = int(parts[0].strip())
        end_yr = int(parts[1].strip())
        return start_yr if month >= COLLEGIATE_SEASON_START_MONTH else end_yr

    if default_year is not None:
        return default_year

    return datetime.now(UTC).year


def _parse_short_date(
    cleaned: str,
    season: str | None = None,
    default_year: int | None = None,
) -> tuple[int, int, int] | None:
    """Parse short date strings like 'Sat Oct  4' or 'Jan 23'."""
    match = re.match(
        r"^(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?\s+)?([A-Za-z]{3,9})\s+(\d{1,2})$",
        cleaned,
        re.IGNORECASE,
    )
    if not match:
        return None

    month_name, day_str = match.group(1), match.group(2)
    day = int(day_str)
    for fmt in ("%B", "%b"):
        try:
            month = datetime.strptime(month_name, fmt).replace(tzinfo=UTC).month
        except ValueError:
            continue
        else:
            year = _resolve_season_year(month, season, default_year)
            return year, month, day

    return None


def _parse_date_components(
    date_str: str,
    *,
    season: str | None = None,
    default_year: int | None = None,
) -> tuple[int, int, int]:
    """Extract year, month, and day integers from various date formats.

    Args:
        date_str: Raw date string.
        season: Optional collegiate hockey season string (e.g. '2025-2026').
        default_year: Optional fallback year when year is missing.

    Returns:
        Tuple of (year, month, day).

    Raises:
        ValueError: If date cannot be parsed.
    """
    cleaned = date_str.strip()
    cleaned = re.sub(
        r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

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

    short_parsed = _parse_short_date(
        cleaned,
        season=season,
        default_year=default_year,
    )
    if short_parsed:
        return short_parsed

    msg = f"Unrecognized date format: {date_str!r}"
    raise ValueError(msg)


def parse_game_datetime(
    date_str: str,
    time_str: str | None = None,
    tz_name: str = DEFAULT_TIMEZONE,
    *,
    season: str | None = None,
    default_year: int | None = None,
) -> datetime:
    """Parse date and optional time strings into a timezone-aware UTC datetime.

    Args:
        date_str: Date string in ISO, US, textual, or short month-day format.
        time_str: Optional time string (e.g., "7:00 PM", "19:00", "8:45 PM EST").
        tz_name: Timezone of the source venue/schedule (default: America/New_York).
        season: Optional collegiate hockey season (e.g. '2025-2026').
        default_year: Optional fallback year if omitted from date string.

    Returns:
        Timezone-aware datetime in UTC.
    """
    year, month, day = _parse_date_components(
        date_str,
        season=season,
        default_year=default_year,
    )
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

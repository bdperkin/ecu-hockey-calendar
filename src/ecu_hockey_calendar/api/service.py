"""Calendar feed generation service conforming strictly to RFC 5545."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime, parsedate_to_datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ecu_hockey_calendar.models import Game

DEFAULT_PROD_ID = "-//ECU Men's Ice Hockey//ECU Hockey Calendar Service//EN"
DEFAULT_CALENDAR_NAME = "ECU Men's Ice Hockey Schedule"
DEFAULT_CALENDAR_DESC = (
    "Official match fixtures and schedule for East Carolina University "
    "Men's Ice Hockey."
)
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_DURATION_HOURS = 2.5
DEFAULT_ALARM_MINUTES = 120
DEFAULT_CACHE_MAX_AGE = 3600
DEFAULT_STALE_WHILE_REVALIDATE = 600
DEFAULT_ECU_DOMAIN = "ecuhockey.com"
DEFAULT_TICKETS_URL = "https://www.ecuhockey.com/tickets"
DEFAULT_ECU_TEAM_NAME = "East Carolina University"


@dataclass(frozen=True)
class VenueDetails:
    """Venue location metadata including geocoded coordinates.

    Attributes:
        name: Name of the venue or rink facility.
        address: Street address line.
        city: City name.
        state: State abbreviation.
        postal_code: Postal or ZIP code.
        latitude: Geocoded latitude coordinate.
        longitude: Geocoded longitude coordinate.
    """

    name: str
    address: str
    city: str
    state: str
    postal_code: str
    latitude: float | None = None
    longitude: float | None = None

    @property
    def full_location(self) -> str:
        """Return formatted full address string.

        Returns:
            Formatted full location string.
        """
        return (
            f"{self.name}, {self.address}, {self.city}, {self.state} {self.postal_code}"
        )

    @property
    def geo_string(self) -> str | None:
        """Return RFC 5545 GEO coordinate property string (latitude;longitude).

        Returns:
            Formatted coordinate string or None if coordinates are missing.
        """
        if self.latitude is not None and self.longitude is not None:
            return f"{self.latitude:.6f};{self.longitude:.6f}"

        return None


KNOWN_VENUES: dict[str, VenueDetails] = {
    "the factory ice house": VenueDetails(
        name="The Factory Ice House",
        address="1839 S Main St",
        city="Wake Forest",
        state="NC",
        postal_code="27587",
        latitude=35.955400,
        longitude=-78.532300,
    ),
    "orange county sportsplex": VenueDetails(
        name="Orange County Sportsplex",
        address="101 Meadowlands Dr",
        city="Hillsborough",
        state="NC",
        postal_code="27278",
        latitude=36.059400,
        longitude=-79.106500,
    ),
    "invisalign arena": VenueDetails(
        name="Invisalign Arena",
        address="1001 Competition Dr",
        city="Morrisville",
        state="NC",
        postal_code="27560",
        latitude=35.834400,
        longitude=-78.795600,
    ),
    "wake competition center": VenueDetails(
        name="Invisalign Arena",
        address="1001 Competition Dr",
        city="Morrisville",
        state="NC",
        postal_code="27560",
        latitude=35.834400,
        longitude=-78.795600,
    ),
    "polar ice raleigh": VenueDetails(
        name="Polar Ice Raleigh",
        address="2601 North Raleigh Blvd",
        city="Raleigh",
        state="NC",
        postal_code="27604",
        latitude=35.814300,
        longitude=-78.604500,
    ),
    "fort dupont ice arena": VenueDetails(
        name="Fort Dupont Ice Arena",
        address="3779 Ely Pl SE",
        city="Washington",
        state="DC",
        postal_code="20020",
        latitude=38.879400,
        longitude=-76.945800,
    ),
    "berglund center": VenueDetails(
        name="Berglund Center",
        address="710 Williamson Rd NE",
        city="Roanoke",
        state="VA",
        postal_code="24016",
        latitude=37.279600,
        longitude=-79.932800,
    ),
    "roanoke civic center": VenueDetails(
        name="Berglund Center",
        address="710 Williamson Rd NE",
        city="Roanoke",
        state="VA",
        postal_code="24016",
        latitude=37.279600,
        longitude=-79.932800,
    ),
    "lancerlot sports complex": VenueDetails(
        name="Lancerlot Sports Complex",
        address="1110 Vinyard Rd",
        city="Vinton",
        state="VA",
        postal_code="24179",
        latitude=37.272800,
        longitude=-79.887800,
    ),
    "chilled ponds ice sports complex": VenueDetails(
        name="Chilled Ponds Ice Sports Complex",
        address="1416 Stephanie Way",
        city="Chesapeake",
        state="VA",
        postal_code="23320",
        latitude=36.758400,
        longitude=-76.242700,
    ),
}


def resolve_venue_details(venue_name: str) -> tuple[str, str | None]:
    """Resolve venue name to full location string and geocoded coordinates.

    Args:
        venue_name: Raw venue name from schedule.

    Returns:
        Tuple of (location_string, optional_geo_string).
    """
    cleaned = venue_name.strip().lower()
    for key, details in KNOWN_VENUES.items():
        if key in cleaned or cleaned in key:
            return details.full_location, details.geo_string

    return venue_name.strip(), None


def _extract_next_chunk(remaining: str, limit: int) -> str:
    """Extract a UTF-8 valid chunk of text up to limit octets.

    Args:
        remaining: Remaining text to chunk.
        limit: Maximum octets allowed.

    Returns:
        Next valid character chunk.
    """
    sub_bytes = remaining.encode("utf-8")
    if len(sub_bytes) <= limit:
        return remaining

    chunk_bytes = sub_bytes[:limit]
    valid_chunk = chunk_bytes.decode("utf-8", errors="ignore")
    return valid_chunk or remaining[0]


def fold_line(line: str, max_octets: int = 75) -> str:
    """Fold an iCalendar content line according to RFC 5545 Section 3.1.

    Lines longer than 75 octets are split into multiple lines using CRLF
    followed by a single space character.

    Args:
        line: Content line to fold.
        max_octets: Maximum octets allowed per line.

    Returns:
        Folded line string.
    """
    if len(line.encode("utf-8")) <= max_octets:
        return line

    chunks: list[str] = []
    remaining = line
    limit = max_octets

    while remaining:
        chunk = _extract_next_chunk(remaining, limit)
        chunks.append(chunk)
        remaining = remaining[len(chunk) :]
        limit = max_octets - 1

    return "\r\n ".join(chunks)


def escape_text(text: str) -> str:
    """Escape text characters according to RFC 5545 Section 3.3.11.

    Args:
        text: Raw text string.

    Returns:
        Escaped text string safe for iCalendar properties.
    """
    escaped = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return escaped.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def generate_game_uid(
    game: Game,
    primary_team_name: str = DEFAULT_ECU_TEAM_NAME,
    domain: str = DEFAULT_ECU_DOMAIN,
) -> str:
    """Generate a deterministic and permanent UID for a game event.

    Args:
        game: Domain Game instance.
        primary_team_name: Canonical team name.
        domain: Domain namespace for UID suffix.

    Returns:
        Deterministic UID string formatted as 'game-...@domain'.
    """
    gid = game.game_id.strip()
    if "@" in gid:
        return gid

    clean_gid = re.sub(r"[^a-zA-Z0-9-]", "-", gid.lower()).strip("-")
    if clean_gid:
        return f"game-{clean_gid}@{domain}"

    date_str = game.start_time.strftime("%Y%m%d")
    opp = game.opponent_of(primary_team_name)
    opp_slug = re.sub(r"[^a-zA-Z0-9-]", "", opp.name.lower())[:16]
    ha = "home" if game.is_home_game(primary_team_name) else "away"
    return f"game-{date_str}-{opp_slug}-{ha}@{domain}"


@dataclass
class CalendarFeedConfig:
    """Configuration options for RFC 5545 iCalendar feed generation.

    Attributes:
        prod_id: Product identifier for iCalendar VCALENDAR header.
        calendar_name: X-WR-CALNAME calendar display name.
        calendar_desc: X-WR-CALDESC calendar description.
        timezone_name: Local timezone name.
        refresh_interval_hours: Client polling refresh interval.
        alarm_minutes: Reminder alarm trigger in minutes (0 to disable).
        duration_hours: Estimated game duration in hours.
        primary_team_name: Primary team name for home/away resolution.
        domain: Domain name for UIDs.
    """

    prod_id: str = DEFAULT_PROD_ID
    calendar_name: str = DEFAULT_CALENDAR_NAME
    calendar_desc: str = DEFAULT_CALENDAR_DESC
    timezone_name: str = DEFAULT_TIMEZONE
    refresh_interval_hours: int = 1
    alarm_minutes: int = DEFAULT_ALARM_MINUTES
    duration_hours: float = DEFAULT_DURATION_HOURS
    primary_team_name: str = DEFAULT_ECU_TEAM_NAME
    domain: str = DEFAULT_ECU_DOMAIN


def _resolve_dtstamp_str(dtstamp_override: datetime | None, now_utc: datetime) -> str:
    """Format DTSTAMP string from override or current UTC timestamp.

    Args:
        dtstamp_override: Optional explicit datetime.
        now_utc: Fallback UTC datetime.

    Returns:
        Formatted UTC timestamp string.
    """
    stamp_dt = dtstamp_override if dtstamp_override is not None else now_utc
    return stamp_dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _filter_and_sort_games(
    games: Sequence[Game],
    *,
    include_past: bool,
    now_utc: datetime,
) -> list[Game]:
    """Filter games by date if past matches are excluded, then sort.

    Args:
        games: Collection of games.
        include_past: True to include past games.
        now_utc: Current UTC datetime.

    Returns:
        Filtered and sorted list of games.
    """
    if include_past:
        return sorted(games, key=lambda g: g.start_time)

    future_games = [g for g in games if g.start_time.astimezone(UTC) >= now_utc]
    return sorted(future_games, key=lambda g: g.start_time)


class CalendarFeedService:
    """Service to generate RFC 5545 compliant calendar feeds and manage caching."""

    def __init__(self, config: CalendarFeedConfig | None = None) -> None:
        """Initialize the calendar feed service.

        Args:
            config: Optional configuration settings.
        """
        self.config = config or CalendarFeedConfig()

    def _build_alarm_block(self, summary: str, alarm_minutes: int) -> list[str]:
        """Construct RFC 5545 VALARM block."""
        if alarm_minutes <= 0:
            return []

        if alarm_minutes % 60 == 0:
            trigger = f"-PT{alarm_minutes // 60}H"
            hours = alarm_minutes // 60
            desc_time = f"{hours} hour{'s' if hours > 1 else ''}"
        else:
            trigger = f"-PT{alarm_minutes}M"
            desc_time = f"{alarm_minutes} minutes"

        desc = escape_text(f"{summary} starts in {desc_time}!")

        return [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{desc}",
            f"TRIGGER:{trigger}",
            "END:VALARM",
        ]

    def _resolve_status_and_summary(self, game: Game) -> tuple[str, str, bool]:
        """Resolve RFC 5545 status, event summary, and home/away designation."""
        is_home = game.is_home_game(self.config.primary_team_name)
        opponent = game.opponent_of(self.config.primary_team_name)
        result_str = game.result.value.upper()

        status_val = "CONFIRMED"
        summary_prefix = ""
        if "CANCEL" in result_str:
            status_val = "CANCELLED"
            summary_prefix = "[CANCELLED] "
        elif "POSTPONE" in result_str:
            status_val = "CANCELLED"
            summary_prefix = "[POSTPONED] "

        vs_or_at = "vs" if is_home else "at"
        summary = f"{summary_prefix}ECU Hockey {vs_or_at} {opponent.name}"
        return status_val, summary, is_home

    def _format_event_timestamps(self, game: Game) -> tuple[str, str]:
        """Calculate UTC DTSTART and DTEND property value strings."""
        start_utc = game.start_time.astimezone(UTC)
        end_utc = start_utc + timedelta(hours=self.config.duration_hours)
        return (
            start_utc.strftime("%Y%m%dT%H%M%SZ"),
            end_utc.strftime("%Y%m%dT%H%M%SZ"),
        )

    def _format_game_description(
        self,
        game: Game,
        summary: str,
        *,
        is_home: bool,
    ) -> str:
        """Format rich text description block for game event."""
        opponent = game.opponent_of(self.config.primary_team_name)
        lines = [
            f"Match: {summary}",
            f"Opponent: {opponent.name}",
            f"Designation: {'Home' if is_home else 'Away'}",
            f"Venue: {game.venue}",
            f"Status: {game.result.value.capitalize()}",
        ]
        if is_home:
            lines.append(f"Tickets: {DEFAULT_TICKETS_URL}")

        if game.home_score is not None and game.away_score is not None:
            lines.append(
                f"Score: {game.home_team.name} {game.home_score}, "
                f"{game.away_team.name} {game.away_score}",
            )

        return escape_text("\n".join(lines))

    def _build_game_event(
        self,
        game: Game,
        dtstamp: str,
        alarm_minutes: int,
    ) -> list[str]:
        """Build RFC 5545 VEVENT property lines for a single game."""
        status_val, summary, is_home = self._resolve_status_and_summary(game)
        dtstart, dtend = self._format_event_timestamps(game)
        loc_str, geo_str = resolve_venue_details(game.venue)
        desc_text = self._format_game_description(game, summary, is_home=is_home)
        uid = generate_game_uid(
            game,
            self.config.primary_team_name,
            self.config.domain,
        )

        event_lines = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"SUMMARY:{escape_text(summary)}",
            f"LOCATION:{escape_text(loc_str)}",
            f"DESCRIPTION:{desc_text}",
            f"STATUS:{status_val}",
        ]

        if geo_str:
            event_lines.append(f"GEO:{geo_str}")

        if is_home:
            event_lines.append(f"URL:{DEFAULT_TICKETS_URL}")

        # VALARM reminder
        event_lines.extend(self._build_alarm_block(summary, alarm_minutes))
        event_lines.append("END:VEVENT")

        return event_lines

    def _build_calendar_header(self, season: str | None) -> list[str]:
        """Construct RFC 5545 VCALENDAR header lines."""
        cal_name = self.config.calendar_name
        if season:
            cal_name = f"{cal_name} ({season})"

        return [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            f"PRODID:{self.config.prod_id}",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            f"X-WR-CALNAME:{escape_text(cal_name)}",
            f"X-WR-CALDESC:{escape_text(self.config.calendar_desc)}",
            f"X-WR-TIMEZONE:{self.config.timezone_name}",
            f"REFRESH-INTERVAL;VALUE=DURATION:PT{self.config.refresh_interval_hours}H",
            f"X-PUBLISHED-TTL:PT{self.config.refresh_interval_hours}H",
        ]

    def generate_ics_feed(
        self,
        games: Sequence[Game],
        *,
        season: str | None = None,
        include_past: bool = True,
        alarm_minutes: int | None = None,
        dtstamp_override: datetime | None = None,
    ) -> str:
        """Generate a complete RFC 5545 iCalendar (.ics) formatted feed.

        Args:
            games: Collection of domain Game instances.
            season: Optional season filter (e.g., '2026-2027').
            include_past: If False, only future scheduled games are included.
            alarm_minutes: Reminder alarm offset in minutes (None uses default).
            dtstamp_override: Optional explicit DTSTAMP datetime.

        Returns:
            A string containing valid, folded RFC 5545 iCalendar content with CRLF
            line endings.
        """
        active_alarm = (
            self.config.alarm_minutes if alarm_minutes is None else alarm_minutes
        )
        now_utc = datetime.now(UTC)
        dtstamp_str = _resolve_dtstamp_str(dtstamp_override, now_utc)
        sorted_games = _filter_and_sort_games(
            games,
            include_past=include_past,
            now_utc=now_utc,
        )

        lines = self._build_calendar_header(season)
        for game in sorted_games:
            lines.extend(self._build_game_event(game, dtstamp_str, active_alarm))

        lines.append("END:VCALENDAR")
        return "\r\n".join(fold_line(line) for line in lines) + "\r\n"

    @staticmethod
    def compute_etag(content: str) -> str:
        """Compute deterministic entity tag (ETag) for content payload.

        Args:
            content: Raw string content.

        Returns:
            Quoted ETag string, e.g. '"a1b2c3..."'.
        """
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return f'"{digest}"'

    @staticmethod
    def get_last_modified(
        games: Sequence[Game],
        default_dt: datetime | None = None,
    ) -> datetime:
        """Determine latest modification or creation timestamp across games.

        Args:
            games: Collection of games.
            default_dt: Default timestamp if games collection is empty.

        Returns:
            Latest datetime in UTC.
        """
        if not games:
            return default_dt or datetime.now(UTC)

        latest = max(g.start_time for g in games)
        return latest.astimezone(UTC)

    @staticmethod
    def format_http_date(dt: datetime) -> str:
        """Format datetime into standard RFC 7231 HTTP-date string.

        Args:
            dt: Datetime object.

        Returns:
            HTTP-date string (e.g. 'Tue, 08 Sep 2026 12:00:00 GMT').
        """
        return format_datetime(dt.astimezone(UTC), usegmt=True)

    @staticmethod
    def parse_http_date(date_str: str) -> datetime | None:
        """Parse an RFC 7231 HTTP-date string into a UTC datetime.

        Args:
            date_str: HTTP date string.

        Returns:
            UTC datetime or None if invalid.
        """
        try:
            return parsedate_to_datetime(date_str).astimezone(UTC)
        except (ValueError, TypeError):
            return None

"""Parser and cross-check engine for opponent schedule reverse lookup.

This module provides tools to query, parse, and verify ECU Ice Hockey fixtures
against opposing institutions' public schedule feeds (iCalendar, JSON, HTML).
It supports multi-factor confidence scoring, home/away inversion verification,
venue matching, and discrepancy reporting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from ecu_hockey_calendar.ingestion.normalizer import (
    DEFAULT_TIMEZONE,
    normalize_team_name,
    parse_game_datetime,
)
from ecu_hockey_calendar.storage.models import GameStatus

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bs4 import Tag

    from ecu_hockey_calendar.ingestion.html_parser import ParsedGameRecord
    from ecu_hockey_calendar.models import Game
    from ecu_hockey_calendar.storage.models import GameModel

ECU_NAME_PATTERN = re.compile(
    r"(?i)\b(?:east\s+carolina(?:\s+university)?|ecu|pirates)\b",
)
HIGH_CONFIDENCE_THRESHOLD = 0.75
TIME_TOLERANCE_EXACT_MINUTES = 15
TIME_TOLERANCE_NEAR_MINUTES = 60
WEIGHT_DATE_EXACT = 0.40
WEIGHT_DATE_ADJACENT = 0.10
WEIGHT_HOME_AWAY = 0.25
WEIGHT_TIME_EXACT = 0.20
WEIGHT_TIME_NEAR = 0.10
WEIGHT_VENUE_MATCH = 0.15
WEIGHT_VENUE_NEUTRAL = 0.08
DEFAULT_DURATION_HOURS = 2.5
COMPACT_DATETIME_LENGTH = 15
DATE_ONLY_LENGTH = 8
EXPECTED_SPLIT_PARTS = 2
MIN_HTML_CELLS = 2
MIN_HTML_TIME_CELLS = 3
MIN_HTML_VENUE_CELLS = 4


class OpponentFeedType(StrEnum):
    """Supported opponent schedule feed data formats."""

    ICAL = "ical"
    JSON = "json"
    HTML = "html"
    SPORTENGINE = "sportengine"


class VerificationStatus(StrEnum):
    """Categorical verification result from reverse cross-checking."""

    VERIFIED = "verified"
    DISCREPANCY = "discrepancy"
    UNVERIFIED = "unverified"
    UNAVAILABLE = "unavailable"


class DiscrepancyType(StrEnum):
    """Classification of detected schedule discrepancies."""

    DATE = "date"
    START_TIME = "start_time"
    VENUE = "venue"
    HOME_AWAY = "home_away"
    STATUS = "status"


@dataclass(frozen=True)
class Discrepancy:
    """Individual field discrepancy detected between ECU and opponent fixtures."""

    discrepancy_type: DiscrepancyType
    field_name: str
    ecu_value: str
    opponent_value: str
    severity: str = "medium"

    def to_dict(self) -> dict[str, str]:
        """Serialize discrepancy to plain dictionary."""
        return {
            "discrepancy_type": self.discrepancy_type.value,
            "field_name": self.field_name,
            "ecu_value": self.ecu_value,
            "opponent_value": self.opponent_value,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class OpponentEndpointConfig:
    """Configuration representing an opposing institution's schedule feed."""

    canonical_name: str
    feed_url: str
    feed_type: OpponentFeedType = OpponentFeedType.ICAL
    home_venue: str = "TBD"
    division: str = "ACHA M2"
    conference: str = "ACCHL"
    aliases: tuple[str, ...] = ()
    website: str | None = None


@dataclass
class OpponentFixture:
    """Normalized fixture record parsed from an opponent's schedule feed."""

    opponent_name: str
    summary: str
    start_time: datetime
    end_time: datetime | None = None
    venue: str = "TBD"
    is_opponent_home: bool = True
    status: GameStatus = GameStatus.SCHEDULED
    raw_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize opponent fixture to plain dictionary."""
        return {
            "opponent_name": self.opponent_name,
            "summary": self.summary,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "venue": self.venue,
            "is_opponent_home": self.is_opponent_home,
            "status": self.status.value,
        }


@dataclass
class ReverseCheckResult:
    """Comprehensive outcome of reverse-checking an ECU fixture against an opponent."""

    ecu_game_id: str | int | None
    opponent_canonical_name: str
    verification_status: VerificationStatus
    confidence_score: float
    matched_fixture: OpponentFixture | None = None
    discrepancies: list[Discrepancy] = field(default_factory=list)
    time_difference_minutes: int | None = None
    home_away_aligned: bool | None = None
    venue_matched: bool | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize verification result to plain dictionary."""
        return {
            "ecu_game_id": (
                str(self.ecu_game_id) if self.ecu_game_id is not None else None
            ),
            "opponent_canonical_name": self.opponent_canonical_name,
            "verification_status": self.verification_status.value,
            "confidence_score": round(self.confidence_score, 2),
            "matched_fixture": (
                self.matched_fixture.to_dict() if self.matched_fixture else None
            ),
            "discrepancies": [d.to_dict() for d in self.discrepancies],
            "time_difference_minutes": self.time_difference_minutes,
            "home_away_aligned": self.home_away_aligned,
            "venue_matched": self.venue_matched,
            "notes": self.notes,
        }


class OpponentDirectory:
    """Registry and query directory for opponent schedule feeds."""

    def __init__(self) -> None:
        """Initialize an empty opponent directory."""
        self._endpoints: dict[str, OpponentEndpointConfig] = {}
        self._alias_map: dict[str, str] = {}

    def register(self, config: OpponentEndpointConfig) -> None:
        """Register an opponent endpoint configuration.

        Args:
            config: OpponentEndpointConfig instance to register.
        """
        canonical = normalize_team_name(config.canonical_name)
        self._endpoints[canonical.lower()] = config
        self._alias_map[canonical.lower()] = canonical.lower()
        for alias in config.aliases:
            norm_alias = normalize_team_name(alias).lower()
            self._alias_map[norm_alias] = canonical.lower()

    def get(self, name: str) -> OpponentEndpointConfig | None:
        """Lookup opponent configuration by institution name or alias.

        Args:
            name: Raw or normalized opponent institution name.

        Returns:
            OpponentEndpointConfig instance or None.
        """
        normalized = normalize_team_name(name).lower()
        canonical_key = self._alias_map.get(normalized, normalized)
        return self._endpoints.get(canonical_key)

    def list_endpoints(self) -> list[OpponentEndpointConfig]:
        """List all unique registered opponent endpoint configurations.

        Returns:
            List of OpponentEndpointConfig objects.
        """
        return list(self._endpoints.values())

    def __contains__(self, name: str) -> bool:
        """Check if opponent name or alias is registered."""
        return self.get(name) is not None


def is_ecu_match(text: str) -> bool:
    """Check if text references East Carolina University or the Pirates.

    Args:
        text: Arbitrary summary, description, or opponent text.

    Returns:
        True if text refers to ECU.
    """
    return bool(ECU_NAME_PATTERN.search(text))


def _fixture_involves_ecu(fix: OpponentFixture) -> bool:
    """Check if single fixture matches ECU in any field."""
    desc = str(fix.raw_details.get("description", ""))
    loc = str(fix.raw_details.get("location", ""))
    opp = str(fix.raw_details.get("opponent", ""))
    return (
        is_ecu_match(fix.summary)
        or is_ecu_match(desc)
        or is_ecu_match(loc)
        or is_ecu_match(opp)
    )


def filter_ecu_fixtures(
    fixtures: Sequence[OpponentFixture],
) -> list[OpponentFixture]:
    """Filter opponent schedule fixtures for games scheduled against ECU.

    Args:
        fixtures: Sequence of parsed OpponentFixture items.

    Returns:
        Filtered list of fixtures involving ECU.
    """
    return [fix for fix in fixtures if _fixture_involves_ecu(fix)]


def _parse_ical_compact_dt(val: str, tz: ZoneInfo) -> datetime | None:
    """Parse compact ical datetime YYYYMMDDTHHMMSS."""
    clean = val.rstrip("Z")
    if "T" not in clean or len(clean) < COMPACT_DATETIME_LENGTH:
        return None

    try:
        yr, mo, dy = int(clean[:4]), int(clean[4:6]), int(clean[6:8])
        hr, mn, sc = int(clean[9:11]), int(clean[11:13]), int(clean[13:15])
        return datetime(yr, mo, dy, hr, mn, sc, tzinfo=tz).astimezone(UTC)
    except ValueError:
        return None


def _parse_ical_date_only(val: str, tz: ZoneInfo) -> datetime | None:
    """Parse date-only ical value YYYYMMDD."""
    clean = val.replace("-", "").strip()
    if len(clean) < DATE_ONLY_LENGTH:
        return None

    try:
        yr, mo, dy = int(clean[:4]), int(clean[4:6]), int(clean[6:8])
        return datetime(yr, mo, dy, 19, 0, tzinfo=tz).astimezone(UTC)
    except ValueError:
        return None


def parse_ical_datetime_string(
    val: str,
    default_tz: ZoneInfo | None = None,
) -> datetime | None:
    """Parse an iCalendar date or datetime string into a UTC datetime.

    Args:
        val: Raw iCalendar datetime string (e.g., '20261012T190000Z', '20261012').
        default_tz: Default timezone when string is naive.

    Returns:
        Timezone-aware datetime in UTC, or None if unparsable.
    """
    clean = val.strip()
    if not clean:
        return None

    tz = (
        ZoneInfo("UTC")
        if clean.endswith("Z")
        else (default_tz or ZoneInfo(DEFAULT_TIMEZONE))
    )
    return _parse_ical_compact_dt(clean, tz) or _parse_ical_date_only(clean, tz)


def _append_or_extend_ical_line(line: str, unfolded: list[str]) -> None:
    """Append new line or extend previous folded line."""
    if line.startswith((" ", "\t")) and unfolded:
        unfolded[-1] += line[1:]
    elif line.strip():
        unfolded.append(line.strip())


def _unfold_ical_lines(text: str) -> list[str]:
    """Unfold wrapped RFC 5545 iCalendar lines."""
    unfolded: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        _append_or_extend_ical_line(line, unfolded)

    return unfolded


def _check_summary_at_match(clean: str) -> bool | None:
    """Check at / @ delimiter in summary to determine home status."""
    parts = re.split(r"\s+(?:at|@)\s+", clean, maxsplit=1)
    if len(parts) != EXPECTED_SPLIT_PARTS:
        return None

    if is_ecu_match(parts[1]):
        return False

    return True if is_ecu_match(parts[0]) else None


def _check_summary_vs_match(clean: str) -> bool | None:
    """Check vs delimiter in summary to determine home status."""
    parts = re.split(r"\s+vs\.?\s+", clean, maxsplit=1)
    if len(parts) != EXPECTED_SPLIT_PARTS:
        return None

    if is_ecu_match(parts[1]):
        return True

    return False if is_ecu_match(parts[0]) else None


def _determine_ical_home_status(summary: str, *, default_home: bool = True) -> bool:
    """Determine if opponent is home based on match summary syntax."""
    clean = summary.lower()
    at_res = _check_summary_at_match(clean)
    if at_res is not None:
        return at_res

    vs_res = _check_summary_vs_match(clean)
    if vs_res is not None:
        return vs_res

    return default_home


_ICAL_STATUS_MAP = {
    "CANCELLED": GameStatus.CANCELLED,
    "POSTPONED": GameStatus.POSTPONED,
}


def _resolve_ical_status(status_str: str) -> GameStatus:
    """Resolve iCalendar STATUS property value to GameStatus enum."""
    return _ICAL_STATUS_MAP.get(status_str.upper().strip(), GameStatus.SCHEDULED)


def _build_vevent_fixture(
    props: Mapping[str, str],
    opponent_name: str,
) -> OpponentFixture | None:
    """Construct OpponentFixture from parsed VEVENT properties."""
    start_dt = parse_ical_datetime_string(props.get("DTSTART", ""))
    if not start_dt:
        return None

    end_dt = parse_ical_datetime_string(props.get("DTEND", ""))
    summary = props.get("SUMMARY", "")
    venue = props.get("LOCATION", "TBD")
    is_home = _determine_ical_home_status(summary)
    st = _resolve_ical_status(props.get("STATUS", "CONFIRMED"))

    return OpponentFixture(
        opponent_name=opponent_name,
        summary=summary,
        start_time=start_dt,
        end_time=end_dt,
        venue=venue,
        is_opponent_home=is_home,
        status=st,
        raw_details=dict(props),
    )


def _parse_vevent_block(
    lines: Sequence[str],
    opponent_name: str,
) -> OpponentFixture | None:
    """Parse property lines of a single VEVENT component."""
    props: dict[str, str] = {}
    for line in lines:
        if ":" not in line:
            continue

        prop_header, prop_val = line.split(":", maxsplit=1)
        prop_name = prop_header.split(";")[0].upper().strip()
        props[prop_name] = prop_val.strip()

    return _build_vevent_fixture(props, opponent_name)


def _finish_vevent_block(
    cur_event: list[str] | None,
    opponent_name: str,
    fixtures: list[OpponentFixture],
) -> None:
    """Parse and append finished vevent block if present."""
    if cur_event is None:
        return

    fix = _parse_vevent_block(cur_event, opponent_name)
    if fix is not None:
        fixtures.append(fix)


def _handle_ical_line(
    line: str,
    cur_event: list[str] | None,
    opponent_name: str,
    fixtures: list[OpponentFixture],
) -> list[str] | None:
    """Process a single iCalendar line and track current event lines."""
    up = line.upper()
    if up == "BEGIN:VEVENT":
        return []

    if up == "END:VEVENT":
        _finish_vevent_block(cur_event, opponent_name, fixtures)
        return None

    if cur_event is not None:
        cur_event.append(line)

    return cur_event


def parse_opponent_ical_feed(
    text: str,
    opponent_name: str,
) -> list[OpponentFixture]:
    """Parse an RFC 5545 iCalendar (.ics) feed into OpponentFixture items.

    Args:
        text: Raw iCalendar payload text.
        opponent_name: Canonical name of the opponent institution.

    Returns:
        List of parsed OpponentFixture instances.
    """
    fixtures: list[OpponentFixture] = []
    cur_event: list[str] | None = None

    for line in _unfold_ical_lines(text):
        cur_event = _handle_ical_line(line, cur_event, opponent_name, fixtures)

    return fixtures


def _parse_date_and_time_to_utc(date_val: str, time_val: str | None) -> datetime | None:
    """Combine date string and optional time string into UTC datetime."""
    try:
        clean_date = date_val.strip()
        if "T" in clean_date:
            return datetime.fromisoformat(clean_date).astimezone(UTC)

        return parse_game_datetime(clean_date, time_val).astimezone(UTC)
    except (ValueError, TypeError):
        return None


def _resolve_json_home_away(item: Mapping[str, Any]) -> bool:
    """Determine home/away status from JSON fixture fields."""
    if "is_home" in item:
        return bool(item["is_home"])

    ha_map = {"home": True, "h": True, "away": False, "a": False}
    ha_val = ha_map.get(str(item.get("home_away", "")).lower())
    if ha_val is not None:
        return ha_val

    summary = str(item.get("summary", "") or item.get("opponent", ""))
    return _determine_ical_home_status(summary)


def _extract_json_start_dt(item: Mapping[str, Any]) -> datetime | None:
    """Extract start datetime from JSON item."""
    raw_dt = str(
        item.get("start_time", "") or item.get("datetime", "") or item.get("date", ""),
    )
    if not raw_dt:
        return None

    raw_time = str(item.get("time", "")) or None
    return _parse_date_and_time_to_utc(raw_dt, raw_time)


def _build_single_json_fixture(
    item: Mapping[str, Any],
    opponent_name: str,
) -> OpponentFixture | None:
    """Construct OpponentFixture from a JSON dictionary."""
    start_dt = _extract_json_start_dt(item)
    if not start_dt:
        return None

    summary = str(
        item.get("summary", "") or f"{opponent_name} vs {item.get('opponent', '')}",
    )
    return OpponentFixture(
        opponent_name=opponent_name,
        summary=summary,
        start_time=start_dt,
        end_time=start_dt + timedelta(hours=DEFAULT_DURATION_HOURS),
        venue=str(item.get("venue", "") or item.get("location", "TBD")),
        is_opponent_home=_resolve_json_home_away(item),
        status=GameStatus.SCHEDULED,
        raw_details=dict(item),
    )


def _extract_json_items_list(data: object) -> list[Any]:
    """Extract candidate list of fixtures from JSON object."""
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for candidate_key in ("games", "schedule", "fixtures", "events", "data"):
            val = data.get(candidate_key)
            if isinstance(val, list):
                return val

    return []


def parse_opponent_json_feed(
    data: object,
    opponent_name: str,
) -> list[OpponentFixture]:
    """Parse JSON schedule payload into OpponentFixture items.

    Args:
        data: Parsed JSON array or dictionary.
        opponent_name: Canonical name of the opponent institution.

    Returns:
        List of parsed OpponentFixture instances.
    """
    items = _extract_json_items_list(data)
    fixtures: list[OpponentFixture] = []
    for item in items:
        if isinstance(item, dict):
            fix = _build_single_json_fixture(item, opponent_name)
            if fix is not None:
                fixtures.append(fix)

    return fixtures


def _extract_cell_text(row: Tag, cell_idx: int) -> str:
    """Extract stripped cell text safely by index."""
    cells = row.find_all(["td", "th"])
    return cells[cell_idx].get_text(" ", strip=True) if cell_idx < len(cells) else ""


def _extract_html_row_dt(row: Tag, cells: Sequence[Tag]) -> datetime | None:
    """Extract start datetime from HTML table row."""
    date_str = _extract_cell_text(row, 0)
    time_str = (
        _extract_cell_text(row, 2) if len(cells) >= MIN_HTML_TIME_CELLS else "19:00"
    )
    return _parse_date_and_time_to_utc(date_str, time_str)


def _extract_html_venue(row: Tag, cells: Sequence[Tag]) -> str:
    """Extract venue string from HTML row."""
    if len(cells) >= MIN_HTML_VENUE_CELLS:
        return _extract_cell_text(row, 3) or "TBD"

    return "TBD"


def _is_html_opponent_home(row_text: str) -> bool:
    """Check if opponent is home in HTML schedule row."""
    lower = row_text.lower()
    return "@" not in lower and " at " not in lower


def _parse_html_row_to_fixture(row: Tag, opponent_name: str) -> OpponentFixture | None:
    """Parse a single HTML schedule table row into an OpponentFixture."""
    cells = row.find_all(["td", "th"])
    if len(cells) < MIN_HTML_CELLS:
        return None

    row_text = row.get_text(" ", strip=True)
    if not is_ecu_match(row_text):
        return None

    start_dt = _extract_html_row_dt(row, cells)
    if not start_dt:
        return None

    return OpponentFixture(
        opponent_name=opponent_name,
        summary=row_text,
        start_time=start_dt,
        venue=_extract_html_venue(row, cells),
        is_opponent_home=_is_html_opponent_home(row_text),
        status=GameStatus.SCHEDULED,
        raw_details={"row_text": row_text},
    )


def parse_opponent_html_feed(
    html_text: str,
    opponent_name: str,
) -> list[OpponentFixture]:
    """Parse HTML schedule tables for opponent fixtures.

    Args:
        html_text: Raw HTML schedule markup.
        opponent_name: Canonical name of the opponent institution.

    Returns:
        List of parsed OpponentFixture instances.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    fixtures: list[OpponentFixture] = []
    for row in soup.find_all("tr"):
        fix = _parse_html_row_to_fixture(row, opponent_name)
        if fix is not None:
            fixtures.append(fix)

    return fixtures


def _extract_game_id(game: object) -> str | int | None:
    """Extract game_id safely as str, int, or None."""
    gid = getattr(game, "game_id", getattr(game, "id", None))
    return gid if isinstance(gid, (str, int)) else None


def _extract_ecu_game_fields(
    game: GameModel | ParsedGameRecord | Game,
) -> tuple[str | int | None, str, datetime, str, bool]:
    """Extract uniform fields from GameModel, ParsedGameRecord, or Game entity."""
    gid = _extract_game_id(game)
    if hasattr(game, "opponent_name"):
        return (
            gid,
            str(game.opponent_name),
            game.start_time,
            str(getattr(game, "venue", "TBD")),
            bool(getattr(game, "is_home", True)),
        )

    home_name = game.home_team.name
    away_name = game.away_team.name
    is_home = is_ecu_match(home_name)
    opp = away_name if is_home else home_name
    st = game.start_time
    ven = str(getattr(game, "venue", "TBD"))
    return gid, opp, st, ven, is_home


def _score_date_comparison(
    ecu_dt: datetime,
    opp_dt: datetime,
) -> tuple[float, list[Discrepancy]]:
    """Compare fixture dates in local America/New_York calendar."""
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    ecu_date = ecu_dt.astimezone(tz).date()
    opp_date = opp_dt.astimezone(tz).date()
    if ecu_date == opp_date:
        return WEIGHT_DATE_EXACT, []

    is_adj = abs((ecu_date - opp_date).days) == 1
    disc = Discrepancy(
        DiscrepancyType.DATE,
        "date",
        str(ecu_date),
        str(opp_date),
        "medium" if is_adj else "high",
    )
    return (WEIGHT_DATE_ADJACENT if is_adj else 0.0), [disc]


def _score_home_away_alignment(
    *,
    ecu_is_home: bool,
    opp_is_home: bool,
) -> tuple[float, list[Discrepancy]]:
    """Verify inverted home/away alignment between ECU and opponent."""
    if ecu_is_home != opp_is_home:
        return WEIGHT_HOME_AWAY, []

    disc = Discrepancy(
        DiscrepancyType.HOME_AWAY,
        "is_home",
        f"ECU Home={ecu_is_home}",
        f"Opponent Home={opp_is_home}",
        "high",
    )
    return 0.0, [disc]


def _score_start_time_comparison(
    ecu_dt: datetime,
    opp_dt: datetime,
) -> tuple[float, int, list[Discrepancy]]:
    """Compare UTC start times and compute discrepancy."""
    diff_min = int(abs((ecu_dt - opp_dt).total_seconds()) // 60)
    if diff_min <= TIME_TOLERANCE_EXACT_MINUTES:
        return WEIGHT_TIME_EXACT, diff_min, []

    is_near = diff_min <= TIME_TOLERANCE_NEAR_MINUTES
    disc = Discrepancy(
        DiscrepancyType.START_TIME,
        "start_time",
        ecu_dt.isoformat(),
        opp_dt.isoformat(),
        "medium" if is_near else "high",
    )
    return (WEIGHT_TIME_NEAR if is_near else 0.0), diff_min, [disc]


def _score_venue_comparison(
    ecu_venue: str,
    opp_venue: str,
) -> tuple[float, bool, list[Discrepancy]]:
    """Compare normalized venue strings."""
    v1 = ecu_venue.strip().lower()
    v2 = opp_venue.strip().lower()
    if v1 in {"tbd", ""} or v2 in {"tbd", ""}:
        return WEIGHT_VENUE_NEUTRAL, True, []

    if v1 in v2 or v2 in v1:
        return WEIGHT_VENUE_MATCH, True, []

    disc = Discrepancy(
        DiscrepancyType.VENUE,
        "venue",
        ecu_venue,
        opp_venue,
        "high",
    )
    return 0.0, False, [disc]


def _score_timing(
    ecu_st: datetime,
    opp_st: datetime,
) -> tuple[float, int, list[Discrepancy]]:
    """Score date and start time comparisons combined."""
    d_sc, d_discs = _score_date_comparison(ecu_st, opp_st)
    t_sc, diff_min, t_discs = _score_start_time_comparison(ecu_st, opp_st)
    return d_sc + t_sc, diff_min, d_discs + t_discs


def _score_context(
    *,
    ecu_ih: bool,
    opp_ih: bool,
    ecu_ven: str,
    opp_ven: str,
) -> tuple[float, bool, bool, list[Discrepancy]]:
    """Score home/away alignment and venue matching."""
    h_sc, h_discs = _score_home_away_alignment(
        ecu_is_home=ecu_ih,
        opp_is_home=opp_ih,
    )
    v_sc, v_match, v_discs = _score_venue_comparison(ecu_ven, opp_ven)
    return h_sc + v_sc, not h_discs, v_match, h_discs + v_discs


def compare_fixtures(
    ecu_game: GameModel | ParsedGameRecord | Game,
    opponent_fixture: OpponentFixture,
) -> tuple[float, list[Discrepancy], int, bool, bool]:
    """Compare preliminary ECU game against opponent fixture and score confidence."""
    _, _, ecu_st, ecu_ven, ecu_ih = _extract_ecu_game_fields(ecu_game)
    t_sc, diff_min, t_discs = _score_timing(ecu_st, opponent_fixture.start_time)
    c_sc, ha_aligned, v_match, c_discs = _score_context(
        ecu_ih=ecu_ih,
        opp_ih=opponent_fixture.is_opponent_home,
        ecu_ven=ecu_ven,
        opp_ven=opponent_fixture.venue,
    )
    return round(t_sc + c_sc, 2), t_discs + c_discs, diff_min, ha_aligned, v_match


def _resolve_verification_status(
    score: float,
    discrepancies: Sequence[Discrepancy],
) -> VerificationStatus:
    """Map confidence score and discrepancies to VerificationStatus."""
    has_high = any(d.severity == "high" for d in discrepancies)
    if score >= HIGH_CONFIDENCE_THRESHOLD and not has_high:
        return VerificationStatus.VERIFIED

    return VerificationStatus.DISCREPANCY


def cross_check_game_against_opponent(
    ecu_game: GameModel | ParsedGameRecord | Game,
    opponent_fixtures: Sequence[OpponentFixture],
    opponent_canonical_name: str,
) -> ReverseCheckResult:
    """Cross-check an ECU fixture against an opponent's parsed fixtures."""
    gid, _, ecu_st, _, _ = _extract_ecu_game_fields(ecu_game)
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    ecu_date = ecu_st.astimezone(tz).date()
    candidates = [
        f
        for f in opponent_fixtures
        if abs((f.start_time.astimezone(tz).date() - ecu_date).days) <= 1
    ]
    if not candidates:
        return ReverseCheckResult(
            ecu_game_id=gid,
            opponent_canonical_name=opponent_canonical_name,
            verification_status=VerificationStatus.UNVERIFIED,
            confidence_score=0.0,
            notes=(
                f"No matching fixture found in {opponent_canonical_name} "
                f"schedule near {ecu_date}"
            ),
        )

    scored = [(compare_fixtures(ecu_game, f), f) for f in candidates]
    scored.sort(key=lambda item: item[0][0], reverse=True)
    best_comp, best_fix = scored[0]

    return ReverseCheckResult(
        ecu_game_id=gid,
        opponent_canonical_name=opponent_canonical_name,
        verification_status=_resolve_verification_status(best_comp[0], best_comp[1]),
        confidence_score=best_comp[0],
        matched_fixture=best_fix,
        discrepancies=best_comp[1],
        time_difference_minutes=best_comp[2],
        home_away_aligned=best_comp[3],
        venue_matched=best_comp[4],
    )


_ICAL = OpponentFeedType.ICAL
_DEFAULT_OPPONENTS: tuple[
    tuple[str, str, str, tuple[str, ...]],
    ...,
] = (
    (
        "UNC Chapel Hill",
        "tarheel",
        "Orange County Sportsplex",
        ("unc", "north carolina"),
    ),
    ("NC State University", "ncstate", "Wake Competition Center", ("nc state", "pack")),
    ("Virginia Tech", "hokies", "Lancerlot Sports Complex", ("vt", "hokies")),
    (
        "Wake Forest University",
        "wakeforest",
        "Winston-Salem Fairgrounds Annex",
        ("wake forest", "demon deacons"),
    ),
    ("Duke University", "duke", "Orange County Sportsplex", ("duke", "blue devils")),
    ("UNC Wilmington", "uncw", "Wilmington Ice House", ("uncw", "seahawks")),
    (
        "Appalachian State University",
        "appstate",
        "AppState Rink",
        ("app state", "mountaineers"),
    ),
    (
        "High Point University",
        "highpoint",
        "Greensboro Ice House",
        ("high point", "panthers"),
    ),
    ("Elon University", "elon", "Orange County Sportsplex", ("elon", "phoenix")),
    ("UNC Charlotte", "charlotte", "Pineville IceHouse", ("charlotte", "49ers")),
    ("James Madison University", "jmu", "Haymarket Iceplex", ("jmu", "dukes")),
    (
        "University of Richmond",
        "richmond",
        "Richmond Ice Zone",
        ("richmond", "spiders"),
    ),
    ("University of Virginia", "virginia", "Main Street Arena", ("uva", "cavaliers")),
    (
        "Georgetown University",
        "georgetown",
        "Fort Dupont Ice Arena",
        ("georgetown", "hoyas"),
    ),
)
DEFAULT_OPPONENT_SPECS: tuple[
    tuple[str, str, OpponentFeedType, str, tuple[str, ...]],
    ...,
] = tuple(
    (
        name,
        f"https://{slug}hockey.{'org' if slug == 'duke' else 'com'}/schedule.ics",
        _ICAL,
        venue,
        aliases,
    )
    for name, slug, venue, aliases in _DEFAULT_OPPONENTS
)


def get_default_opponent_directory() -> OpponentDirectory:
    """Construct and return default directory of known opponent endpoints.

    Returns:
        Populated OpponentDirectory instance.
    """
    directory = OpponentDirectory()
    for name, url, ftype, venue, aliases in DEFAULT_OPPONENT_SPECS:
        directory.register(
            OpponentEndpointConfig(
                canonical_name=name,
                feed_url=url,
                feed_type=ftype,
                home_venue=venue,
                aliases=aliases,
            ),
        )

    return directory


__all__ = [
    "DEFAULT_OPPONENT_SPECS",
    "HIGH_CONFIDENCE_THRESHOLD",
    "Discrepancy",
    "DiscrepancyType",
    "OpponentDirectory",
    "OpponentEndpointConfig",
    "OpponentFeedType",
    "OpponentFixture",
    "ReverseCheckResult",
    "VerificationStatus",
    "compare_fixtures",
    "cross_check_game_against_opponent",
    "filter_ecu_fixtures",
    "get_default_opponent_directory",
    "is_ecu_match",
    "parse_ical_datetime_string",
    "parse_opponent_html_feed",
    "parse_opponent_ical_feed",
    "parse_opponent_json_feed",
]

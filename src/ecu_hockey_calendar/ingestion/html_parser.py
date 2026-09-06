"""HTML parser for extracting game schedules using BeautifulSoup4."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, Tag

from ecu_hockey_calendar.ingestion.normalizer import (
    DEFAULT_TIMEZONE,
    normalize_team_name,
    parse_game_datetime,
    parse_game_score,
    parse_game_status,
)
from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.storage.models import GameStatus

if TYPE_CHECKING:
    from datetime import datetime

MIN_TABLE_COLUMNS = 3
TARGET_ROW_CELL_COUNT = 5

DEFAULT_ECU_TEAM = Team(
    name="East Carolina University",
    city="Greenville",
    state="NC",
    division="ACHA M2",
    conference="ACCHL",
)


@dataclass(frozen=True, slots=True)
class ParsedGameRecord:
    """Intermediate parsed representation of a scraped game event.

    Attributes:
        game_id: Generated or extracted unique identifier.
        opponent_name: Clean canonical name of opponent team.
        is_home: Whether ECU is the designated home team.
        start_time: Scheduled start time in UTC.
        venue: Arena, rink, or location string.
        status: Normalized GameStatus lifecycle state.
        home_score: Final home score if completed.
        away_score: Final away score if completed.
        overtime_note: Suffix such as 'OT' or 'SO' if game went to overtime.
        raw_text: Raw unparsed text line for reference.
    """

    game_id: str
    opponent_name: str
    is_home: bool
    start_time: datetime
    venue: str
    status: GameStatus = GameStatus.SCHEDULED
    home_score: int | None = None
    away_score: int | None = None
    overtime_note: str | None = None
    raw_text: str = ""

    def _determine_loss_result(self) -> GameResult:
        """Helper to distinguish regular loss from overtime/shootout loss."""
        if self.overtime_note in {"OT", "SO", "2OT", "F/OT", "F/SO"}:
            return GameResult.OVERTIME_LOSS

        return GameResult.LOSS

    def _get_ecu_and_opp_scores(self) -> tuple[int, int] | None:
        """Extract (ecu_score, opp_score) if scores are present."""
        if self.home_score is None or self.away_score is None:
            return None

        if self.is_home:
            return self.home_score, self.away_score

        return self.away_score, self.home_score

    def calculate_result(self) -> GameResult:
        """Calculate GameResult relative to ECU."""
        scores = self._get_ecu_and_opp_scores()
        if scores is None:
            return GameResult.SCHEDULED

        ecu_score, opp_score = scores
        if ecu_score > opp_score:
            return GameResult.WIN

        if ecu_score < opp_score:
            return self._determine_loss_result()

        return GameResult.TIE

    def to_domain_game(
        self,
        ecu_team: Team = DEFAULT_ECU_TEAM,
        opponent_team: Team | None = None,
    ) -> Game:
        """Convert parsed record to domain Game dataclass.

        Args:
            ecu_team: Canonical ECU Team dataclass.
            opponent_team: Optional opponent Team dataclass.

        Returns:
            Validated domain Game instance.
        """
        opp = opponent_team or Team(
            name=self.opponent_name,
            city="Unknown",
            state="NC",
        )
        home = ecu_team if self.is_home else opp
        away = opp if self.is_home else ecu_team

        return Game(
            game_id=self.game_id,
            home_team=home,
            away_team=away,
            start_time=self.start_time,
            venue=self.venue,
            result=self.calculate_result(),
            home_score=self.home_score,
            away_score=self.away_score,
        )


def _generate_game_id(
    start_time: datetime,
    opponent: str,
    *,
    is_home: bool,
) -> str:
    """Generate deterministic game identifier from date, opponent, and venue type.

    Args:
        start_time: UTC start datetime.
        opponent: Opponent team name.
        is_home: Home/away flag.

    Returns:
        Slugified game identifier.
    """
    date_str = start_time.strftime("%Y%m%d")
    opp_slug = re.sub(r"[^a-z0-9]+", "-", opponent.lower()).strip("-")
    prefix = "home" if is_home else "away"
    return f"ecu-{prefix}-{opp_slug}-{date_str}"


def _clean_text(tag: Tag | None) -> str:
    """Extract and normalize stripped text from a BeautifulSoup Tag."""
    if tag is None:
        return ""

    return re.sub(r"\s+", " ", tag.get_text()).strip()


def _parse_home_away(raw_str: str) -> tuple[bool, str]:
    """Extract home/away status and clean opponent name from indicator strings.

    Args:
        raw_str: Text like 'vs NC State', '@ UNC Wilmington', or 'at Virginia Tech'.

    Returns:
        Tuple of (is_home, cleaned_opponent_name).
    """
    cleaned = re.sub(r"\s+", " ", raw_str).strip()
    is_home = True
    if re.match(r"^(@|at\s+)", cleaned, re.IGNORECASE):
        is_home = False
        cleaned = re.sub(r"^(@|at\s+)", "", cleaned, flags=re.IGNORECASE).strip()
    elif re.match(r"^vs\.?\s+", cleaned, re.IGNORECASE):
        is_home = True
        cleaned = re.sub(r"^vs\.?\s+", "", cleaned, flags=re.IGNORECASE).strip()

    return is_home, normalize_team_name(cleaned)


def _is_header_row(cell_text: str) -> bool:
    """Check whether row text matches standard table header keywords."""
    lowered = cell_text.lower()
    return any(h in lowered for h in ("date", "time", "day", "game"))


def _build_game_record(
    start_time: datetime,
    opponent: str,
    *,
    is_home: bool,
    venue: str,
    score_str: str,
    raw_text: str,
) -> ParsedGameRecord:
    """Construct a ParsedGameRecord with computed scores and status."""
    s1, s2, ot_note = parse_game_score(score_str)
    return ParsedGameRecord(
        game_id=_generate_game_id(start_time, opponent, is_home=is_home),
        opponent_name=opponent,
        is_home=is_home,
        start_time=start_time,
        venue=venue,
        status=parse_game_status(score_str, has_score=s1 is not None),
        home_score=s1 if is_home else s2,
        away_score=s2 if is_home else s1,
        overtime_note=ot_note,
        raw_text=raw_text,
    )


def _extract_cell_texts(cells: list[Tag]) -> list[str] | None:
    """Extract and pad cell texts, returning None if invalid row or header."""
    if len(cells) < MIN_TABLE_COLUMNS:
        return None

    texts = [_clean_text(c) for c in cells]
    if _is_header_row(texts[0]):
        return None

    while len(texts) < TARGET_ROW_CELL_COUNT:
        texts.append("")

    return texts


def _parse_table_row(
    row: Tag,
    tz_name: str,
    default_venue: str,
) -> ParsedGameRecord | None:
    """Parse a single <tr> element into a ParsedGameRecord.

    Args:
        row: BeautifulSoup table row Tag.
        tz_name: Timezone string.
        default_venue: Fallback venue if missing.

    Returns:
        ParsedGameRecord or None if row does not contain game data.
    """
    cells = row.find_all(["td", "th"])
    texts = _extract_cell_texts(cells)
    if texts is None:
        return None

    try:
        start_time = parse_game_datetime(texts[0], texts[2], tz_name=tz_name)
    except ValueError:
        return None

    is_home, opponent = _parse_home_away(texts[1])
    if not opponent:
        return None

    venue_str = texts[3] or default_venue
    return _build_game_record(
        start_time,
        opponent,
        is_home=is_home,
        venue=venue_str,
        score_str=texts[4],
        raw_text=" | ".join(texts[: len(cells)]),
    )


def _find_card_text(card: Tag, pattern: str, default: str = "") -> str:
    """Find child element by class regex and return cleaned text."""
    el = card.find(class_=re.compile(pattern, re.IGNORECASE))
    return _clean_text(el) or default


def _parse_game_card(
    card: Tag,
    tz_name: str,
    default_venue: str,
) -> ParsedGameRecord | None:
    """Parse a game card element (<div class="game-card">, etc.) into a record.

    Args:
        card: BeautifulSoup card Tag.
        tz_name: Timezone string.
        default_venue: Fallback venue.

    Returns:
        ParsedGameRecord or None if invalid.
    """
    date_text = _find_card_text(card, r"(date|time|schedule-date)")
    opp_text = _find_card_text(card, r"(opponent|team|vs|title)")
    if not date_text or not opp_text:
        return None

    try:
        start_time = parse_game_datetime(date_text, None, tz_name=tz_name)
    except ValueError:
        return None

    is_home, opponent = _parse_home_away(opp_text)
    if not opponent:
        return None

    venue_text = _find_card_text(
        card,
        r"(venue|location|arena|rink)",
        default=default_venue,
    )
    score_text = _find_card_text(card, r"(score|result|status)")

    return _build_game_record(
        start_time,
        opponent,
        is_home=is_home,
        venue=venue_text,
        score_str=score_text,
        raw_text=card.get_text(" ", strip=True),
    )


def _parse_tables(
    soup: BeautifulSoup,
    tz_name: str,
    default_venue: str,
) -> list[ParsedGameRecord]:
    """Extract game records from HTML table rows."""
    records: list[ParsedGameRecord] = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            rec = _parse_table_row(row, tz_name, default_venue)
            if rec:
                records.append(rec)

    return records


def _parse_cards(
    soup: BeautifulSoup,
    tz_name: str,
    default_venue: str,
) -> list[ParsedGameRecord]:
    """Extract game records from HTML card structures."""
    patterns = [
        re.compile(r"(game-card|schedule-item|schedule-row)"),
        re.compile(r"(game-row|event-item)"),
    ]
    for pat in patterns:
        records: list[ParsedGameRecord] = []
        for card in soup.find_all(class_=pat):
            rec = _parse_game_card(card, tz_name, default_venue)
            if rec:
                records.append(rec)

        if records:
            return records

    return []


def parse_schedule_html(
    html: str,
    *,
    tz_name: str = DEFAULT_TIMEZONE,
    default_venue: str = "Carolina Ice Zone",
) -> list[ParsedGameRecord]:
    """Parse HTML content to extract all game records.

    Inspects both table-based structures and card/div-based structures.

    Args:
        html: Raw HTML markup string.
        tz_name: Timezone string for game timestamps.
        default_venue: Fallback venue if unstated.

    Returns:
        List of parsed game records.
    """
    soup = BeautifulSoup(html, "html.parser")
    table_records = _parse_tables(soup, tz_name, default_venue)
    if table_records:
        return table_records

    return _parse_cards(soup, tz_name, default_venue)


__all__ = [
    "DEFAULT_ECU_TEAM",
    "ParsedGameRecord",
    "parse_schedule_html",
]

"""SportsEngine schedule and game parser for ACCHL."""

# pylint: disable=too-many-lines

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ecu_hockey_calendar.ingestion.html_parser import (
    ParsedGameRecord,
    _clean_text,
    _generate_game_id,
    _parse_home_away,
)
from ecu_hockey_calendar.ingestion.normalizer import (
    normalize_team_name,
    parse_game_datetime,
    parse_game_score,
    parse_game_status,
)
from ecu_hockey_calendar.storage.models import GameStatus

DEFAULT_ACCHL_SEASON = "2025-2026"
DEFAULT_BASE_URL = "https://www.acchockey.com"
MIN_SCHEDULE_CELLS = 4
SPLIT_SCHEDULE_MIN_CELLS = 8
LEAGUE_GAME_OFFSET_MIN_CELLS = 7
SPLIT_SCORES_MIN_COUNT = 2
DEFAULT_AWAY_SCORE_COL = 3
DEFAULT_HOME_SCORE_COL = 5
SCHEDULE_LINK_PATTERNS = (
    "/schedule/team_instance/",
    "/schedule/tab_completegamelist/",
)


def _extract_season_from_tags(soup: BeautifulSoup) -> str | None:
    """Find season string from title or season-classed tags."""
    for tag in (soup.find("title"), soup.find(class_=re.compile(r"season"))):
        if isinstance(tag, Tag):
            match = re.search(r"(20\d{2}-20\d{2})", tag.get_text())
            if match:
                return str(match.group(1))

    return None


def extract_season_from_html(html: str) -> str | None:
    """Extract collegiate season string like '2025-2026' from page content."""
    soup = BeautifulSoup(html, "html.parser")
    tag_season = _extract_season_from_tags(soup)
    if tag_season:
        return tag_season

    body_match = re.search(r"(20\d{2}-20\d{2})", html[:4000])
    if body_match:
        return str(body_match.group(1))

    return None


def _determine_division_and_game_type(
    league_game_id: str | None,
) -> tuple[str, str]:
    """Map league game ID prefix to division and game classification."""
    if not league_game_id:
        return "ACCHL", "regular_season"

    prefix = league_game_id.split("-")[0].upper()
    prefix_map = {
        "ME": ("ACC M2 Elite", "conference"),
        "MP": ("ACC M2 Premier", "conference"),
        "M1": ("ACC M1", "conference"),
        "M2": ("ACC M2", "conference"),
        "M3": ("ACC M3", "conference"),
        "SR": ("ACC Showcase", "showcase"),
        "E": ("Exhibition", "exhibition"),
        "T": ("ACC Tournament", "tournament"),
    }
    return prefix_map.get(prefix, ("ACCHL", "regular_season"))


def _extract_sportengine_game_id(row: Tag) -> str | None:
    """Extract numeric SportsEngine game ID from row attribute or links."""
    row_id = str(row.get("id", ""))
    id_match = re.search(r"game_list_row_(\d+)", row_id)
    if id_match:
        return str(id_match.group(1))

    for link in row.find_all("a", href=True):
        href = str(link.get("href", ""))
        link_match = re.search(r"/game/show/(\d+)", href)
        if link_match:
            return str(link_match.group(1))

    return None


def _extract_opponent_info(cell: Tag) -> tuple[bool, str, str]:
    """Extract home/away flag, opponent name, and opponent URL from cell."""
    cell_text = _clean_text(cell)
    is_home, clean_name = _parse_home_away(cell_text)

    team_link = cell.find("a", class_="teamName") or cell.find(
        "a",
        href=re.compile(r"/page/show/\d+"),
    )
    opp_url = ""
    if isinstance(team_link, Tag):
        opp_url = str(team_link.get("href", ""))
        link_text = _clean_text(team_link)
        if link_text:
            clean_name = normalize_team_name(link_text)

    return is_home, clean_name, opp_url


def _extract_score_from_classes(cell: Tag) -> tuple[str, str]:
    """Extract result and score from dedicated schedule list elements."""
    res_elem = cell.find(class_="scheduleListResult")
    score_elem = cell.find(class_="scheduleListScore")
    res_str = _clean_text(res_elem) if isinstance(res_elem, Tag) else ""
    score_str = _clean_text(score_elem) if isinstance(score_elem, Tag) else ""
    return res_str, score_str


def _extract_score_and_result(cell: Tag) -> tuple[str, str]:
    """Extract raw score string and outcome character from cell."""
    res_str, score_str = _extract_score_from_classes(cell)
    if score_str or res_str:
        return res_str, score_str

    cell_text = _clean_text(cell)
    match = re.search(r"(\d+\s*[-:]\s*\d+(?:\s*\([A-Z/]+\))?)", cell_text)
    score = str(match.group(1)) if match else ""
    res = cell_text[0] if cell_text.startswith(("W", "L", "T")) else ""
    return res, score


def _compute_scores(
    s1: int,
    s2: int,
    *,
    is_home: bool,
) -> tuple[int, int]:
    """Assign team scores according to home/away orientation."""
    if is_home:
        return s1, s2

    return s2, s1


def _parse_scores_for_record(
    score_str: str,
    *,
    is_home: bool,
) -> tuple[int | None, int | None, str | None]:
    """Parse raw score string into home_score, away_score, and overtime_note."""
    s1, s2, ot = parse_game_score(score_str)
    if s1 is None or s2 is None:
        return None, None, None

    home_score, away_score = _compute_scores(s1, s2, is_home=is_home)
    return home_score, away_score, ot


def _extract_time_and_status(
    status_cell: Tag | None,
    *,
    has_score: bool,
    row_classes: list[str],
) -> tuple[str | None, GameStatus]:
    """Determine scheduled time string and GameStatus lifecycle state."""
    raw_status = _clean_text(status_cell) if status_cell else ""
    time_str: str | None = None

    time_match = re.search(
        r"(\d{1,2}:\d{2}\s*[AP]M(?:\s*[A-Z]{2,4})?)",
        raw_status,
        re.IGNORECASE,
    )
    if time_match:
        time_str = str(time_match.group(1))

    if has_score or "completed" in row_classes:
        return time_str, GameStatus.FINAL

    status = parse_game_status(raw_status, has_score=has_score)
    return time_str, status


def _build_game_metadata(
    league_game_id: str | None,
    se_game_id: str | None,
    season: str,
    opp_url: str,
) -> dict[str, object]:
    """Construct structured league verification metadata."""
    division, game_type = _determine_division_and_game_type(league_game_id)
    return {
        "league_game_id": league_game_id,
        "sportengine_game_id": se_game_id,
        "division": division,
        "game_type": game_type,
        "season": season,
        "opponent_url": opp_url,
        "source": "acchockey.com",
    }


def _extract_row_cells(row: Tag) -> list[Tag]:
    """Extract td elements from row."""
    return list(row.find_all("td"))


def _extract_tag_classes(tag: Tag) -> list[str]:
    """Extract list of class name strings from a tag."""
    raw_class = tag.get("class")
    if isinstance(raw_class, list):
        return [str(c) for c in raw_class]

    if isinstance(raw_class, str):
        return raw_class.split()

    return []


def _get_cell_at(cells: list[Tag], index: int) -> Tag | None:
    """Safely get cell tag at index."""
    if index < len(cells):
        return cells[index]

    return None


def _is_valid_date_text(text: str) -> bool:
    """Validate that date text is not empty, header, or placeholder."""
    if not text or text.lower() in {"date", "tbd"}:
        return False

    return any(c.isdigit() for c in text)


@dataclass(frozen=True)
class _RowBasicData:
    """Core schedule table row attributes."""

    league_game_id: str | None
    date_text: str
    score_cell: Tag
    opp_cell: Tag
    venue: str
    status_cell: Tag | None


@dataclass(frozen=True)
class _TableColumnIndices:
    """Detected column positions for schedule table."""

    game_id: int = 0
    date: int = 1
    score: int = 2
    opponent: int = 3
    venue: int = 4
    status: int = 5
    away_team: int = 2
    away_score: int = DEFAULT_AWAY_SCORE_COL
    home_team: int = 4
    home_score: int = DEFAULT_HOME_SCORE_COL
    is_split: bool = False


@dataclass(frozen=True)
class _SplitRowData:
    """Intermediate parsed attributes from a split-row layout."""

    date_text: str
    opp_name: str
    is_home: bool
    opp_url: str
    league_game_id: str | None
    venue: str
    status_cell: Tag | None
    away_score_cell: Tag | None
    home_score_cell: Tag | None


def _is_split_headers(headers: list[str]) -> bool:
    """Check whether table headers describe a split home/away layout."""
    has_away = any("away" in h or "visitor" in h for h in headers)
    has_home = any("home" in h for h in headers)
    return has_away and has_home


def _find_header_col(
    headers: list[str],
    keywords: tuple[str, ...],
    default: int,
) -> int:
    """Find the first column index matching any keyword."""
    for idx, text in enumerate(headers):
        if any(k in text for k in keywords):
            return idx

    return default


def _find_header_indices(
    headers: list[str],
    keywords: tuple[str, ...],
) -> list[int]:
    """Find all column indices matching any keyword."""
    return [idx for idx, text in enumerate(headers) if any(k in text for k in keywords)]


def _resolve_split_score_cols(
    headers: list[str],
) -> tuple[int, int]:
    """Identify away and home score column indices."""
    indices = _find_header_indices(headers, ("score", "result", "pts"))
    if len(indices) >= SPLIT_SCORES_MIN_COUNT:
        return indices[0], indices[1]

    return DEFAULT_AWAY_SCORE_COL, DEFAULT_HOME_SCORE_COL


def _parse_split_headers(headers: list[str]) -> _TableColumnIndices:
    """Build column mapping for split home/away header row."""
    away_score_col, home_score_col = _resolve_split_score_cols(headers)
    return _TableColumnIndices(
        game_id=_find_header_col(headers, ("game id", "game #", "game_id"), 0),
        date=_find_header_col(headers, ("date",), 1),
        away_team=_find_header_col(headers, ("away", "visitor"), 2),
        away_score=away_score_col,
        home_team=_find_header_col(headers, ("home",), 4),
        home_score=home_score_col,
        venue=_find_header_col(headers, ("location", "venue", "arena"), 6),
        status=_find_header_col(headers, ("status", "time"), 7),
        is_split=True,
    )


def _parse_standard_headers(headers: list[str]) -> _TableColumnIndices:
    """Build column mapping for standard 6- or 7-column header row."""
    return _TableColumnIndices(
        game_id=_find_header_col(headers, ("game id", "game #", "game_id"), 0),
        date=_find_header_col(headers, ("date",), 1),
        score=_find_header_col(headers, ("result", "score"), 2),
        opponent=_find_header_col(headers, ("opponent", "opp"), 3),
        venue=_find_header_col(headers, ("location", "venue", "arena"), 4),
        status=_find_header_col(headers, ("status", "time"), 5),
        is_split=False,
    )


def _detect_column_indices(table: Tag) -> _TableColumnIndices:
    """Identify table column positions from th elements."""
    th_tags = table.find_all("th")
    if not th_tags:
        return _TableColumnIndices()

    headers = [_clean_text(th).lower() for th in th_tags]
    if _is_split_headers(headers):
        return _parse_split_headers(headers)

    return _parse_standard_headers(headers)


def _is_cell_score_like(cell: Tag | None) -> bool:
    """Check if cell content resembles a score integer or hyphen."""
    if cell is None:
        return False

    text = _clean_text(cell)
    return text == "-" or bool(re.match(r"^\d+(?:\s*\([A-Z/]+\))?$", text))


def _detect_row_columns_by_count(cells: list[Tag]) -> _TableColumnIndices:
    """Infer column layout based on cell count and content."""
    n = len(cells)
    if n >= SPLIT_SCHEDULE_MIN_CELLS and _is_cell_score_like(
        _get_cell_at(cells, DEFAULT_AWAY_SCORE_COL),
    ):
        return _TableColumnIndices(
            game_id=0,
            date=1,
            away_team=2,
            away_score=DEFAULT_AWAY_SCORE_COL,
            home_team=4,
            home_score=DEFAULT_HOME_SCORE_COL,
            venue=6,
            status=7,
            is_split=True,
        )

    if n >= LEAGUE_GAME_OFFSET_MIN_CELLS and not _is_valid_date_text(
        _clean_text(_get_cell_at(cells, 1)),
    ):
        return _TableColumnIndices(
            game_id=0,
            date=2,
            score=3,
            opponent=4,
            venue=5,
            status=6,
            is_split=False,
        )

    return _TableColumnIndices()


def _needs_fallback_columns(
    cells: list[Tag],
    cols: _TableColumnIndices,
) -> bool:
    """Check whether row layout differs from table-level column detection."""
    date_cell = _get_cell_at(cells, cols.date)
    date_text = _clean_text(date_cell) if date_cell else ""
    return not _is_valid_date_text(date_text)


def _resolve_row_columns(
    cells: list[Tag],
    cols: _TableColumnIndices | None,
) -> _TableColumnIndices:
    """Ensure valid column mapping for current row cells."""
    if cols is not None and not _needs_fallback_columns(cells, cols):
        return cols

    return _detect_row_columns_by_count(cells)


def _is_ecu_name(name: str) -> bool:
    """Check whether a name string refers to East Carolina University."""
    if not name:
        return False

    norm = normalize_team_name(name)
    if norm == "East Carolina University":
        return True

    lower = name.lower()
    return "east carolina" in lower or "ecu" in lower.split()


def _find_cell_team_link(cell: Tag) -> Tag | None:
    """Find anchor element representing a team in a cell."""
    link = cell.find("a", class_="teamName")
    if isinstance(link, Tag):
        return link

    link = cell.find("a", href=re.compile(r"/page/show/\d+|/team_instance/\d+"))
    if isinstance(link, Tag):
        return link

    link = cell.find("a", href=True)
    return link if isinstance(link, Tag) else None


def _extract_cell_team_and_url(cell: Tag | None) -> tuple[str, str]:
    """Extract team name and URL from team cell."""
    if cell is None:
        return "", ""

    team_link = _find_cell_team_link(cell)
    if team_link is not None:
        link_text = _clean_text(team_link)
        if link_text:
            return normalize_team_name(link_text), str(team_link.get("href", ""))

    return normalize_team_name(_clean_text(cell)), ""


def _resolve_split_opponent(
    away_cell: Tag | None,
    home_cell: Tag | None,
) -> tuple[bool, str, str]:
    """Determine (is_home, opp_name, opp_url) from away and home team cells."""
    away_name, away_url = _extract_cell_team_and_url(away_cell)
    home_name, home_url = _extract_cell_team_and_url(home_cell)

    if _is_ecu_name(away_name):
        return False, home_name, home_url

    if _is_ecu_name(home_name):
        return True, away_name, away_url

    return True, away_name, away_url


def _parse_int_score(text: str) -> int | None:
    """Extract digits as integer score."""
    match = re.search(r"\b(\d+)\b", text)
    return int(match.group(1)) if match else None


def _parse_overtime_note(text: str) -> str | None:
    """Extract overtime suffix from text if present."""
    match = re.search(r"\b(OT|SO|2OT|F/OT|F/SO)\b", text, re.IGNORECASE)
    return str(match.group(1)).upper() if match else None


def _extract_split_score(cell: Tag | None) -> tuple[int | None, str | None]:
    """Extract integer score and optional overtime note from a split score cell."""
    if cell is None:
        return None, None

    text = _clean_text(cell)
    if not text or text in {"-", "TBD"}:
        return None, None

    return _parse_int_score(text), _parse_overtime_note(text)


def _cell_text_or_default(
    cell: Tag | None,
    default: str | None = None,
) -> str | None:
    """Extract stripped cell text or fallback value."""
    text = _clean_text(cell)
    return text or default


def _has_valid_scores(home_score: int | None, away_score: int | None) -> bool:
    """Check if scores are present and positive."""
    if home_score is None or away_score is None:
        return False

    return home_score > 0 or away_score > 0


def _resolve_split_row_scores(
    away_score_cell: Tag | None,
    home_score_cell: Tag | None,
    status_cell: Tag | None,
    row: Tag,
) -> tuple[str | None, tuple[GameStatus, int | None, int | None, str | None]]:
    """Parse scores and determine GameStatus for split row."""
    away_score, away_ot = _extract_split_score(away_score_cell)
    home_score, home_ot = _extract_split_score(home_score_cell)
    ot = home_ot or away_ot
    has_score = _has_valid_scores(home_score, away_score)
    time_str, status = _extract_time_and_status(
        status_cell,
        has_score=has_score,
        row_classes=_extract_tag_classes(row),
    )
    if status in {GameStatus.SCHEDULED, GameStatus.CANCELLED, GameStatus.POSTPONED}:
        return time_str, (status, None, None, None)

    return time_str, (status, home_score, away_score, ot)


def _extract_split_row_data(
    cells: list[Tag],
    cols: _TableColumnIndices,
) -> _SplitRowData | None:
    """Validate and gather cell elements for a split-row game entry."""
    date_text = _clean_text(_get_cell_at(cells, cols.date))
    if not _is_valid_date_text(date_text):
        return None

    is_home, opp_name, opp_url = _resolve_split_opponent(
        _get_cell_at(cells, cols.away_team),
        _get_cell_at(cells, cols.home_team),
    )
    if not opp_name:
        return None

    return _SplitRowData(
        date_text=date_text,
        opp_name=opp_name,
        is_home=is_home,
        opp_url=opp_url,
        league_game_id=_cell_text_or_default(_get_cell_at(cells, cols.game_id)),
        venue=_cell_text_or_default(_get_cell_at(cells, cols.venue), "TBD") or "TBD",
        status_cell=_get_cell_at(cells, cols.status),
        away_score_cell=_get_cell_at(cells, cols.away_score),
        home_score_cell=_get_cell_at(cells, cols.home_score),
    )


def _build_split_record(
    data: _SplitRowData,
    time_str: str | None,
    scores_status: tuple[GameStatus, int | None, int | None, str | None],
    season: str,
    row: Tag,
) -> ParsedGameRecord | None:
    """Instantiate ParsedGameRecord for split-row structure."""
    status, home_score, away_score, ot = scores_status
    try:
        start_time = parse_game_datetime(
            data.date_text,
            time_str=time_str,
            season=season,
        )
    except ValueError:
        return None

    se_game_id = _extract_sportengine_game_id(row)
    return ParsedGameRecord(
        game_id=_generate_game_id(start_time, data.opp_name, is_home=data.is_home),
        opponent_name=data.opp_name,
        is_home=data.is_home,
        start_time=start_time,
        venue=data.venue,
        status=status,
        home_score=home_score,
        away_score=away_score,
        overtime_note=ot,
        raw_text=f"{data.date_text} {data.opp_name}".strip(),
        league_game_id=data.league_game_id,
        metadata=_build_game_metadata(
            data.league_game_id,
            se_game_id,
            season,
            data.opp_url,
        ),
    )


def _parse_split_table_row(
    row: Tag,
    cells: list[Tag],
    season: str,
    cols: _TableColumnIndices,
) -> ParsedGameRecord | None:
    """Parse row with separate away and home team/score columns."""
    data = _extract_split_row_data(cells, cols)
    if data is None:
        return None

    time_str, scores_status = _resolve_split_row_scores(
        data.away_score_cell,
        data.home_score_cell,
        data.status_cell,
        row,
    )
    return _build_split_record(data, time_str, scores_status, season, row)


def _extract_row_cells_tuple(
    cells: list[Tag],
    cols: _TableColumnIndices,
) -> tuple[Tag, Tag, Tag] | None:
    """Extract and validate date, score, and opponent cells."""
    date_cell = _get_cell_at(cells, cols.date)
    if date_cell is None or not _is_valid_date_text(_clean_text(date_cell)):
        return None

    score_cell = _get_cell_at(cells, cols.score)
    opp_cell = _get_cell_at(cells, cols.opponent)
    if score_cell is None or opp_cell is None:
        return None

    return date_cell, score_cell, opp_cell


def _extract_row_basic_data(
    cells: list[Tag],
    cols: _TableColumnIndices | None = None,
) -> _RowBasicData | None:
    """Extract core column values and tags from row cells."""
    if len(cells) < MIN_SCHEDULE_CELLS:
        return None

    resolved_cols = cols if cols is not None else _TableColumnIndices()
    vital_cells = _extract_row_cells_tuple(cells, resolved_cols)
    if vital_cells is None:
        return None

    date_cell, score_cell, opp_cell = vital_cells
    venue = _cell_text_or_default(_get_cell_at(cells, resolved_cols.venue), "TBD")
    game_id_cell = _get_cell_at(cells, resolved_cols.game_id)
    return _RowBasicData(
        league_game_id=_cell_text_or_default(game_id_cell),
        date_text=_clean_text(date_cell),
        score_cell=score_cell,
        opp_cell=opp_cell,
        venue=venue or "TBD",
        status_cell=_get_cell_at(cells, resolved_cols.status),
    )


def _parse_row_status_and_scores(
    score_cell: Tag,
    status_cell: Tag | None,
    row: Tag,
    *,
    is_home: bool,
) -> tuple[str | None, GameStatus, int | None, int | None, str | None]:
    """Parse score values and compute status from table row."""
    _, score_str = _extract_score_and_result(score_cell)
    home_score, away_score, ot = _parse_scores_for_record(score_str, is_home=is_home)
    has_score = (
        home_score is not None
        and away_score is not None
        and (home_score > 0 or away_score > 0)
    )
    row_classes = _extract_tag_classes(row)
    time_str, status = _extract_time_and_status(
        status_cell,
        has_score=has_score,
        row_classes=row_classes,
    )
    if status in {GameStatus.SCHEDULED, GameStatus.CANCELLED, GameStatus.POSTPONED}:
        home_score, away_score, ot = None, None, None

    return time_str, status, home_score, away_score, ot


def _parse_standard_table_row(
    row: Tag,
    cells: list[Tag],
    season: str,
    cols: _TableColumnIndices,
) -> ParsedGameRecord | None:
    """Parse single standard SportEngine schedule table row."""
    data = _extract_row_basic_data(cells, cols)
    if data is None:
        return None

    is_home, opp_name, opp_url = _extract_opponent_info(data.opp_cell)
    if not opp_name:
        return None

    time_str, status, home_score, away_score, ot = _parse_row_status_and_scores(
        data.score_cell,
        data.status_cell,
        row,
        is_home=is_home,
    )
    try:
        start_time = parse_game_datetime(
            data.date_text,
            time_str=time_str,
            season=season,
        )
    except ValueError:
        return None

    se_game_id = _extract_sportengine_game_id(row)
    return ParsedGameRecord(
        game_id=_generate_game_id(start_time, opp_name, is_home=is_home),
        opponent_name=opp_name,
        is_home=is_home,
        start_time=start_time,
        venue=data.venue,
        status=status,
        home_score=home_score,
        away_score=away_score,
        overtime_note=ot,
        raw_text=f"{data.date_text} {opp_name}".strip(),
        league_game_id=data.league_game_id,
        metadata=_build_game_metadata(data.league_game_id, se_game_id, season, opp_url),
    )


def _parse_stat_table_row(
    row: Tag,
    season: str,
    cols: _TableColumnIndices | None = None,
) -> ParsedGameRecord | None:
    """Parse single SportEngine schedule table row into ParsedGameRecord."""
    cells = _extract_row_cells(row)
    resolved_cols = _resolve_row_columns(cells, cols)
    if resolved_cols.is_split:
        return _parse_split_table_row(row, cells, season, resolved_cols)

    return _parse_standard_table_row(row, cells, season, resolved_cols)


def _parse_table_rows(table: Tag, season: str) -> list[ParsedGameRecord]:
    """Parse all valid game records from schedule table."""
    cols = _detect_column_indices(table)
    records: list[ParsedGameRecord] = []
    for row in table.find_all("tr"):
        rec = _parse_stat_table_row(row, season, cols)
        if rec is not None:
            records.append(rec)

    return records


def parse_acchockey_schedule_html(
    html: str,
    *,
    default_season: str = DEFAULT_ACCHL_SEASON,
) -> list[ParsedGameRecord]:
    """Parse SportEngine HTML schedule page into ParsedGameRecord instances.

    Args:
        html: Raw HTML page markup.
        default_season: Fallback season identifier if not detected.

    Returns:
        List of parsed game records.
    """
    season = extract_season_from_html(html) or default_season
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_=re.compile(r"statTable"))
    if not isinstance(table, Tag):
        return []

    return _parse_table_rows(table, season)


def _parse_details_list(
    details_ul: Tag,
) -> dict[str, str]:
    """Extract key-value pairs from game_details list element."""
    details: dict[str, str] = {}
    for li in details_ul.find_all("li"):
        strong = li.find("strong")
        if isinstance(strong, Tag):
            label = _clean_text(strong).rstrip(":").strip()
            strong.decompose()
            val = _clean_text(li)
            if label:
                details[label.lower()] = val

    return details


def _find_header_links(header_div: Tag) -> list[Tag]:
    """Find team link elements in game header."""
    links = header_div.find_all("a", class_="teamName")
    if not links:
        links = header_div.find_all("a")

    return list(links)


def _collect_unique_names(links: list[Tag]) -> list[str]:
    """Collect ordered unique names from tags."""
    names: list[str] = []
    for link in links:
        name = _clean_text(link)
        if name and name not in names:
            names.append(name)

    return names


def _extract_header_names(header_div: Tag) -> tuple[str, str]:
    """Extract two distinct team names from header element."""
    links = _find_header_links(header_div)
    names = _collect_unique_names(links)
    t1 = names[0] if names else "East Carolina University"
    t2 = names[1] if len(names) > 1 else "Unknown"
    return t1, t2


def _extract_header_scores(header_div: Tag) -> tuple[int | None, int | None]:
    """Extract home and away scores from header text numbers."""
    raw_text = _clean_text(header_div)
    nums = [int(n) for n in re.findall(r"\b(\d+)\b", raw_text)]
    s1 = nums[0] if len(nums) > 0 else None
    s2 = nums[1] if len(nums) > 1 else None
    return s1, s2


def _parse_game_header_teams(
    header_div: Tag,
) -> tuple[str, str, int | None, int | None]:
    """Extract team names and scores from game_header_v2."""
    t1, t2 = _extract_header_names(header_div)
    s1, s2 = _extract_header_scores(header_div)
    return t1, t2, s1, s2


def _compute_page_scores(
    s1: int | None,
    s2: int | None,
) -> tuple[int | None, int | None]:
    """Extract (home_score, away_score) from optional score integers."""
    if s1 is None or s2 is None:
        return None, None

    return s2, s1


def _resolve_game_page_teams(
    t1: str,
    t2: str,
    s1: int | None,
    s2: int | None,
) -> tuple[str, bool, int | None, int | None]:
    """Resolve opponent name, home flag, and scores relative to ECU."""
    norm1 = normalize_team_name(t1)
    norm2 = normalize_team_name(t2)
    ecu_canonical = "East Carolina University"
    home_score, away_score = _compute_page_scores(s1, s2)

    if norm1 == ecu_canonical:
        return norm2, False, home_score, away_score

    return norm1, True, home_score, away_score


def _extract_game_details_dict(soup: BeautifulSoup) -> dict[str, str]:
    """Collect key-value details from all game_details lists on page."""
    details: dict[str, str] = {}
    for ul in soup.find_all("ul", class_=re.compile(r"game_details")):
        details.update(_parse_details_list(ul))

    return details


def _parse_game_header(
    soup: BeautifulSoup,
) -> tuple[str, str, int | None, int | None]:
    """Parse teams and scores from header element."""
    header = soup.find("div", class_=re.compile(r"game_header"))
    if isinstance(header, Tag):
        return _parse_game_header_teams(header)

    return "", "", None, None


def _resolve_game_page_header(
    soup: BeautifulSoup,
) -> tuple[str, bool, int | None, int | None]:
    """Resolve opponent name, home flag, and scores from game page header."""
    t1, t2, s1, s2 = _parse_game_header(soup)
    return _resolve_game_page_teams(t1, t2, s1, s2)


def _resolve_game_html_status_and_scores(
    raw_status: str | None,
    home_score: int | None,
    away_score: int | None,
) -> tuple[GameStatus, int | None, int | None]:
    """Determine GameStatus and sanitized scores for game detail page."""
    has_score = (
        home_score is not None
        and away_score is not None
        and (home_score > 0 or away_score > 0)
    )
    status = parse_game_status(raw_status, has_score=has_score)
    if status in {GameStatus.SCHEDULED, GameStatus.CANCELLED, GameStatus.POSTPONED}:
        return status, None, None

    return status, home_score, away_score


def parse_acchockey_game_html(
    html: str,
    *,
    default_season: str = DEFAULT_ACCHL_SEASON,
) -> ParsedGameRecord | None:
    """Parse single SportsEngine game detail page.

    Args:
        html: Raw HTML of game page.
        default_season: Fallback season identifier.

    Returns:
        ParsedGameRecord instance or None if invalid.
    """
    soup = BeautifulSoup(html, "html.parser")
    season = extract_season_from_html(html) or default_season
    details = _extract_game_details_dict(soup)

    date_str = details.get("date")
    if not date_str:
        return None

    opp, is_home, home_score, away_score = _resolve_game_page_header(soup)

    try:
        start_time = parse_game_datetime(
            date_str,
            time_str=details.get("time"),
            season=season,
        )
    except ValueError:
        return None

    league_id = details.get("game id")
    status, home_score, away_score = _resolve_game_html_status_and_scores(
        details.get("status"),
        home_score,
        away_score,
    )

    return ParsedGameRecord(
        game_id=_generate_game_id(start_time, opp, is_home=is_home),
        opponent_name=opp,
        is_home=is_home,
        start_time=start_time,
        venue=details.get("venue", "TBD"),
        status=status,
        home_score=home_score,
        away_score=away_score,
        league_game_id=league_id,
        metadata=_build_game_metadata(league_id, None, season, ""),
    )


def _extract_team_instance_schedule_link(
    href: str,
    base_url: str,
) -> str | None:
    """Construct schedule URL from team instance link if applicable."""
    inst_match = re.search(r"team_instance[/=](\d+)", href)
    if not inst_match:
        return None

    team_instance_id = inst_match.group(1)
    sub_match = re.search(r"subseason=(\d+)", href)
    sub_query = f"?subseason={sub_match.group(1)}" if sub_match else ""
    return urljoin(base_url, f"/schedule/team_instance/{team_instance_id}{sub_query}")


def _discover_schedule_from_team_links(
    soup: BeautifulSoup,
    base_url: str,
) -> list[str]:
    """Derive canonical schedule URLs from team instance links."""
    discovered: list[str] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        full_url = _extract_team_instance_schedule_link(href, base_url)
        if full_url and full_url not in seen:
            seen.add(full_url)
            discovered.append(full_url)

    return discovered


def _find_direct_schedule_links(
    soup: BeautifulSoup,
    base_url: str,
) -> list[str]:
    """Find schedule links directly matching known URL patterns."""
    links: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if any(k in href for k in SCHEDULE_LINK_PATTERNS):
            full_url = urljoin(base_url, href)
            if full_url not in seen:
                seen.add(full_url)
                links.append(full_url)

    return links


def extract_schedule_urls(
    html: str,
    base_url: str = DEFAULT_BASE_URL,
) -> list[str]:
    """Find schedule links from team page markup."""
    soup = BeautifulSoup(html, "html.parser")
    direct_links = _find_direct_schedule_links(soup, base_url)
    if direct_links:
        return direct_links

    return _discover_schedule_from_team_links(soup, base_url)


def extract_subseason_urls(
    html: str,
    base_url: str = DEFAULT_BASE_URL,
) -> list[str]:
    """Find subseason schedule URLs from season dropdown options."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()

    for opt in soup.find_all("option"):
        val = opt.get("value")
        if isinstance(val, str) and "subseason=" in val:
            full_url = urljoin(base_url, val)
            if full_url not in seen:
                seen.add(full_url)
                urls.append(full_url)

    return urls


def extract_pagination_urls(
    html: str,
    base_url: str = DEFAULT_BASE_URL,
) -> list[str]:
    """Extract next-page pagination links from schedule page."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()

    for container in soup.find_all(class_=re.compile(r"pagination|pager|page_nav")):
        for a in container.find_all("a", href=True):
            href = str(a["href"]).strip()
            full_url = urljoin(base_url, href)
            if full_url not in seen:
                seen.add(full_url)
                urls.append(full_url)

    return urls


__all__ = [
    "DEFAULT_ACCHL_SEASON",
    "DEFAULT_BASE_URL",
    "extract_pagination_urls",
    "extract_schedule_urls",
    "extract_season_from_html",
    "extract_subseason_urls",
    "parse_acchockey_game_html",
    "parse_acchockey_schedule_html",
]

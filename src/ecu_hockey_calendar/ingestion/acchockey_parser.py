"""SportsEngine schedule and game parser for ACCHL."""

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
    return bool(text) and text.lower() not in {"date", "tbd"}


@dataclass(frozen=True)
class _RowBasicData:
    """Core schedule table row attributes."""

    league_game_id: str | None
    date_text: str
    score_cell: Tag
    opp_cell: Tag
    venue: str
    status_cell: Tag | None


def _extract_row_basic_data(cells: list[Tag]) -> _RowBasicData | None:
    """Extract core column values and tags from row cells."""
    if len(cells) < MIN_SCHEDULE_CELLS:
        return None

    date_text = _clean_text(cells[1])
    if not _is_valid_date_text(date_text):
        return None

    league_game_id = _clean_text(cells[0]) or None
    venue_cell = _get_cell_at(cells, 4)
    venue = _clean_text(venue_cell) or "TBD"
    status_cell = _get_cell_at(cells, 5)
    return _RowBasicData(
        league_game_id=league_game_id,
        date_text=date_text,
        score_cell=cells[2],
        opp_cell=cells[3],
        venue=venue,
        status_cell=status_cell,
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
    has_score = home_score is not None and away_score is not None
    row_classes = _extract_tag_classes(row)
    time_str, status = _extract_time_and_status(
        status_cell,
        has_score=has_score,
        row_classes=row_classes,
    )
    return time_str, status, home_score, away_score, ot


def _parse_stat_table_row(
    row: Tag,
    season: str,
) -> ParsedGameRecord | None:
    """Parse single SportEngine schedule table row into ParsedGameRecord."""
    cells = _extract_row_cells(row)
    data = _extract_row_basic_data(cells)
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


def _parse_table_rows(table: Tag, season: str) -> list[ParsedGameRecord]:
    """Parse all valid game records from schedule table."""
    records: list[ParsedGameRecord] = []
    for row in table.find_all("tr"):
        rec = _parse_stat_table_row(row, season)
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

    has_score = home_score is not None and away_score is not None
    league_id = details.get("game id")
    return ParsedGameRecord(
        game_id=_generate_game_id(start_time, opp, is_home=is_home),
        opponent_name=opp,
        is_home=is_home,
        start_time=start_time,
        venue=details.get("venue", "TBD"),
        status=parse_game_status(
            details.get("status", "Scheduled"),
            has_score=has_score,
        ),
        home_score=home_score,
        away_score=away_score,
        league_game_id=league_id,
        metadata=_build_game_metadata(league_id, None, season, ""),
    )


def extract_schedule_urls(
    html: str,
    base_url: str = DEFAULT_BASE_URL,
) -> list[str]:
    """Find schedule links from team page markup."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        is_schedule = any(k in href for k in SCHEDULE_LINK_PATTERNS)
        if is_schedule:
            full_url = urljoin(base_url, href)
            if full_url not in seen:
                seen.add(full_url)
                links.append(full_url)

    return links


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

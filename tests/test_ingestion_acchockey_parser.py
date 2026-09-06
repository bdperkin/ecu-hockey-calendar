"""Unit tests for ACCHL SportsEngine schedule and game parser."""

from __future__ import annotations

from bs4 import BeautifulSoup

from ecu_hockey_calendar.ingestion.acchockey_parser import (
    _collect_unique_names,
    _determine_division_and_game_type,
    _extract_header_names,
    _extract_header_scores,
    _extract_opponent_info,
    _extract_row_cells,
    _extract_score_and_result,
    _extract_sportengine_game_id,
    _extract_tag_classes,
    _extract_time_and_status,
    _get_cell_at,
    _is_valid_date_text,
    _parse_details_list,
    _parse_game_header,
    _parse_scores_for_record,
    _parse_stat_table_row,
    _parse_table_rows,
    _resolve_game_page_teams,
    extract_pagination_urls,
    extract_schedule_urls,
    extract_season_from_html,
    extract_subseason_urls,
    parse_acchockey_game_html,
    parse_acchockey_schedule_html,
)
from ecu_hockey_calendar.storage.models import GameStatus

SAMPLE_SCHEDULE_HTML = """<!DOCTYPE html>
<html>
<head>
<title>Game Schedule - 2025-2026 Regular Season - East Carolina University</title>
</head>
<body>
<div class="contentTabs">
<a href="/schedule/tab_completegamelist/team_instance/index/10282704?subseason=950924">
Complete
</a>
</div>
<select name="subseasons">
<option value="/schedule/team_instance/10282704?subseason=950924">
2025-2026 Regular Season
</option>
<option value="/schedule/team_instance/10618291?subseason=966044">
2026-2027 Regular Season
</option>
<option value="/page/other">No Subseason Link</option>
</select>
<div class="pageElement">
<table class="statTable sortable noSortImages">
<thead>
<tr>
<th>Game ID</th><th>Date</th><th>Result</th>
<th>Opponent</th><th>Location</th><th>Status</th>
</tr>
</thead>
<tbody>
<tr id="game_list_row_44621413" class="odd completed compactGameList">
<td class="nowrap">ME-6</td>
<td class="nowrap">Sat Oct  4</td>
<td>
<div class="scheduleListResult">L</div>
<div class="scheduleListScore">
<a href="https://www.acchockey.com/game/show/44621413?subseason=950924">3-5</a>
</div>
</td>
<td>
<div class="scheduleListTeam">
@ <a class="teamName" href="/page/show/9165918-elon">Elon</a>
</div>
</td>
<td><div class="scheduleListTeam">Hillsborough, NC, USA</div></td>
<td class="nowrap"><a href="/game/show/44621413">TBD</a></td>
</tr>
<tr id="game_list_row_44621465" class="even completed compactGameList">
<td class="nowrap">ME-26</td>
<td class="nowrap">Fri Oct 24</td>
<td>
<div class="scheduleListResult">W</div>
<div class="scheduleListScore">
<a href="/game/show/44621465">6-4</a>
</div>
</td>
<td>
<div class="scheduleListTeam">
<a class="teamName" href="/page/show/9165948-app-state">App State</a>
</div>
</td>
<td><div class="scheduleListTeam">Fayetteville, NC, USA</div></td>
<td class="nowrap"><a href="/game/show/44621465">TBD</a></td>
</tr>
<tr id="game_list_row_45100998" class="odd scheduled compactGameList">
<td class="nowrap">E-100</td>
<td class="nowrap">Sat Jan 24</td>
<td>
<div class="scheduleListResult">-</div>
<div class="scheduleListScore"></div>
</td>
<td>
<div class="scheduleListTeam">
<a class="teamName" href="/page/show/9165918-elon">Elon</a>
</div>
</td>
<td><div class="scheduleListTeam">Greenville, NC, USA</div></td>
<td class="nowrap"><a href="/game/show/45100998">8:45 PM EST</a></td>
</tr>
</tbody>
</table>
</div>
<div class="pagination">
<a class="next_page" href="/schedule/team_instance/10282704?page=2">Next Page</a>
<a href="/schedule/team_instance/10282704?page=2">2</a>
</div>
</body>
</html>
"""

SAMPLE_GAME_DETAIL_HTML = """<!DOCTYPE html>
<html>
<head>
<title>Game Detail - Elon University vs East Carolina University</title>
</head>
<body>
<div class="season">2025-2026</div>
<div class="game_header_v2">
<a class="teamName" href="/page/show/9165918-elon">Elon University</a>
<span>5</span>
<a class="teamName" href="/page/show/9602441-east-carolina">East Carolina University</a>
<span>3</span>
</div>
<div class="StatWidgetGroup inset game_details">
<ul class="game_details">
<li><h3>General Info</h3></li>
<li><strong>Game ID:</strong> ME-6</li>
<li><strong>Date:</strong> Sat Oct 4, 2025</li>
<li><strong>Time:</strong> 7:30 PM EST</li>
<li><strong>Status:</strong> Final</li>
</ul>
<ul class="game_details">
<li><strong>Venue:</strong> Hillsborough, NC, USA</li>
</ul>
</div>
</body>
</html>
"""


def test_extract_season_from_html() -> None:
    """Verify season string extraction from title, class, and body."""
    # From title
    html_title = "<title>Schedule 2025-2026</title>"
    assert extract_season_from_html(html_title) == "2025-2026"

    # From .season class
    html_class = '<div class="season-banner">2026-2027 Season</div>'
    assert extract_season_from_html(html_class) == "2026-2027"

    # From raw body
    html_body = "<body>Some text mentioning 2024-2025 season</body>"
    assert extract_season_from_html(html_body) == "2024-2025"

    # Not found
    assert extract_season_from_html("<div>No season here</div>") is None


def test_determine_division_and_game_type() -> None:
    """Verify mapping of league game ID prefixes to division and game type."""
    assert _determine_division_and_game_type(None) == ("ACCHL", "regular_season")
    assert _determine_division_and_game_type("") == ("ACCHL", "regular_season")
    assert _determine_division_and_game_type("ME-6") == ("ACC M2 Elite", "conference")
    assert _determine_division_and_game_type("MP-10") == (
        "ACC M2 Premier",
        "conference",
    )
    assert _determine_division_and_game_type("M1-5") == ("ACC M1", "conference")
    assert _determine_division_and_game_type("M2-12") == ("ACC M2", "conference")
    assert _determine_division_and_game_type("M3-1") == ("ACC M3", "conference")
    assert _determine_division_and_game_type("SR-17") == ("ACC Showcase", "showcase")
    assert _determine_division_and_game_type("E-100") == ("Exhibition", "exhibition")
    assert _determine_division_and_game_type("T-4") == ("ACC Tournament", "tournament")
    assert _determine_division_and_game_type("UNKNOWN-99") == (
        "ACCHL",
        "regular_season",
    )


def test_extract_sportengine_game_id() -> None:
    """Verify extraction of numeric game ID from row attribute and links."""
    soup = BeautifulSoup(
        '<tr id="game_list_row_123456">'
        '<td><a href="/game/show/999999">Link</a></td></tr>',
        "html.parser",
    )
    row = soup.find("tr")
    assert row is not None
    assert _extract_sportengine_game_id(row) == "123456"

    soup_link_only = BeautifulSoup(
        '<tr><td><a href="https://www.acchockey.com/game/show/777888?subseason=123">'
        "Game</a></td></tr>",
        "html.parser",
    )
    row_link = soup_link_only.find("tr")
    assert row_link is not None
    assert _extract_sportengine_game_id(row_link) == "777888"

    soup_none = BeautifulSoup("<tr><td>No ID</td></tr>", "html.parser")
    row_none = soup_none.find("tr")
    assert row_none is not None
    assert _extract_sportengine_game_id(row_none) is None


def test_extract_opponent_info() -> None:
    """Verify opponent name and home/away determination from cell."""
    soup1 = BeautifulSoup(
        '<td><div class="team">@ '
        '<a class="teamName" href="/page/show/100">Elon</a></div></td>',
        "html.parser",
    )
    cell1 = soup1.find("td")
    assert cell1 is not None
    is_home, name, url = _extract_opponent_info(cell1)
    assert not is_home
    assert name == "Elon University"
    assert url == "/page/show/100"

    soup2 = BeautifulSoup(
        '<td><a href="/page/show/200">App State</a></td>',
        "html.parser",
    )
    cell2 = soup2.find("td")
    assert cell2 is not None
    is_home2, name2, url2 = _extract_opponent_info(cell2)
    assert is_home2
    assert name2 == "Appalachian State University"
    assert url2 == "/page/show/200"

    soup3 = BeautifulSoup("<td>vs NC State</td>", "html.parser")
    cell3 = soup3.find("td")
    assert cell3 is not None
    is_home3, name3, url3 = _extract_opponent_info(cell3)
    assert is_home3
    assert name3 == "NC State University"
    assert url3 == ""


def test_extract_score_and_result() -> None:
    """Verify score and result extraction from classes and text."""
    soup1 = BeautifulSoup(
        '<td><div class="scheduleListResult">W</div>'
        '<div class="scheduleListScore">6-4</div></td>',
        "html.parser",
    )
    cell1 = soup1.find("td")
    assert cell1 is not None
    res1, score1 = _extract_score_and_result(cell1)
    assert res1 == "W"
    assert score1 == "6-4"

    soup2 = BeautifulSoup("<td>L 3-5 (OT)</td>", "html.parser")
    cell2 = soup2.find("td")
    assert cell2 is not None
    res2, score2 = _extract_score_and_result(cell2)
    assert res2 == "L"
    assert score2 == "3-5 (OT)"

    soup3 = BeautifulSoup("<td>Scheduled</td>", "html.parser")
    cell3 = soup3.find("td")
    assert cell3 is not None
    res3, score3 = _extract_score_and_result(cell3)
    assert res3 == ""
    assert score3 == ""


def test_parse_scores_for_record() -> None:
    """Verify home/away score computation."""
    # ECU home: ECU is 6, Opp is 4
    h1, a1, ot1 = _parse_scores_for_record("6-4", is_home=True)
    assert h1 == 6
    assert a1 == 4
    assert ot1 is None

    # ECU away: ECU is 3, Opp (home) is 5
    h2, a2, ot2 = _parse_scores_for_record("3-5 (OT)", is_home=False)
    assert h2 == 5
    assert a2 == 3
    assert ot2 == "OT"

    # Unparsable
    assert _parse_scores_for_record("", is_home=True) == (None, None, None)


def test_extract_time_and_status() -> None:
    """Verify time and status resolution from status cell."""
    soup1 = BeautifulSoup("<td>8:45 PM EST</td>", "html.parser")
    cell1 = soup1.find("td")
    time1, status1 = _extract_time_and_status(cell1, has_score=False, row_classes=[])
    assert time1 == "8:45 PM EST"
    assert status1 == GameStatus.SCHEDULED

    # Completed class
    soup2 = BeautifulSoup("<td>TBD</td>", "html.parser")
    cell2 = soup2.find("td")
    time2, status2 = _extract_time_and_status(
        cell2,
        has_score=False,
        row_classes=["completed"],
    )
    assert time2 is None
    assert status2 == GameStatus.FINAL

    # Postponed text
    soup3 = BeautifulSoup("<td>Postponed</td>", "html.parser")
    cell3 = soup3.find("td")
    time3, status3 = _extract_time_and_status(cell3, has_score=False, row_classes=[])
    assert time3 is None
    assert status3 == GameStatus.POSTPONED

    # None cell
    time4, status4 = _extract_time_and_status(None, has_score=True, row_classes=[])
    assert time4 is None
    assert status4 == GameStatus.FINAL


def test_tag_classes_and_cell_helpers() -> None:
    """Verify class extraction and cell indexing helpers."""
    soup = BeautifulSoup(
        '<tr class="odd completed compact"><td>A</td><td>B</td></tr>',
        "html.parser",
    )
    tr = soup.find("tr")
    assert tr is not None
    assert _extract_tag_classes(tr) == ["odd", "completed", "compact"]

    soup_str = BeautifulSoup('<div class="single-class"></div>', "html.parser")
    div = soup_str.find("div")
    assert div is not None
    assert _extract_tag_classes(div) == ["single-class"]

    soup_none = BeautifulSoup("<div></div>", "html.parser")
    div_none = soup_none.find("div")
    assert div_none is not None
    assert _extract_tag_classes(div_none) == []

    cells = _extract_row_cells(tr)
    assert len(cells) == 2
    assert _get_cell_at(cells, 0) is cells[0]
    assert _get_cell_at(cells, 5) is None

    assert _is_valid_date_text("Sat Oct 4")
    assert not _is_valid_date_text("Date")
    assert not _is_valid_date_text("TBD")
    assert not _is_valid_date_text("")


def test_parse_stat_table_row_edge_cases() -> None:
    """Verify edge case handling in table row parsing."""
    # Too few cells
    soup1 = BeautifulSoup("<tr><td>1</td><td>2</td></tr>", "html.parser")
    r1 = soup1.find("tr")
    assert r1 is not None
    assert _parse_stat_table_row(r1, "2025-2026") is None

    # Date is header
    soup2 = BeautifulSoup(
        "<tr><td>Game ID</td><td>Date</td><td>Result</td><td>Opponent</td></tr>",
        "html.parser",
    )
    r2 = soup2.find("tr")
    assert r2 is not None
    assert _parse_stat_table_row(r2, "2025-2026") is None

    # Opponent is empty
    soup3 = BeautifulSoup(
        "<tr><td>G1</td><td>Sat Oct 4</td><td>-</td><td>   </td></tr>",
        "html.parser",
    )
    r3 = soup3.find("tr")
    assert r3 is not None
    assert _parse_stat_table_row(r3, "2025-2026") is None

    # Date ValueError
    soup4 = BeautifulSoup(
        "<tr><td>G1</td><td>InvalidDate</td><td>-</td><td>Elon</td></tr>",
        "html.parser",
    )
    r4 = soup4.find("tr")
    assert r4 is not None
    assert _parse_stat_table_row(r4, "2025-2026") is None


def test_parse_acchockey_schedule_html() -> None:
    """Verify full schedule parsing from real fixture markup."""
    records = parse_acchockey_schedule_html(SAMPLE_SCHEDULE_HTML)
    assert len(records) == 3

    # Row 1: ME-6, @ Elon, L 3-5 (ECU away)
    r0 = records[0]
    assert r0.league_game_id == "ME-6"
    assert r0.opponent_name == "Elon University"
    assert not r0.is_home
    assert r0.home_score == 5
    assert r0.away_score == 3
    assert r0.status == GameStatus.FINAL
    assert r0.venue == "Hillsborough, NC, USA"
    assert r0.metadata is not None
    assert r0.metadata["sportengine_game_id"] == "44621413"
    assert r0.metadata["division"] == "ACC M2 Elite"
    assert r0.metadata["game_type"] == "conference"
    assert r0.metadata["season"] == "2025-2026"

    # Row 2: ME-26, vs App State, W 6-4 (ECU home)
    r1 = records[1]
    assert r1.league_game_id == "ME-26"
    assert r1.opponent_name == "Appalachian State University"
    assert r1.is_home
    assert r1.home_score == 6
    assert r1.away_score == 4
    assert r1.status == GameStatus.FINAL

    # Row 3: E-100, vs Elon, scheduled with 8:45 PM EST
    r2 = records[2]
    assert r2.league_game_id == "E-100"
    assert r2.is_home
    assert r2.status == GameStatus.SCHEDULED
    assert r2.home_score is None
    assert r2.away_score is None
    assert r2.metadata is not None
    assert r2.metadata["division"] == "Exhibition"

    # No statTable
    assert not parse_acchockey_schedule_html("<div>No table</div>")


def test_parse_acchockey_game_html() -> None:
    """Verify single game detail page parsing."""
    rec = parse_acchockey_game_html(SAMPLE_GAME_DETAIL_HTML)
    assert rec is not None
    assert rec.opponent_name == "Elon University"
    assert rec.is_home
    assert rec.home_score == 3
    assert rec.away_score == 5
    assert rec.status == GameStatus.FINAL
    assert rec.venue == "Hillsborough, NC, USA"
    assert rec.league_game_id == "ME-6"

    # Game page missing date
    assert parse_acchockey_game_html("<div>No date</div>") is None

    # Game page with invalid date
    html_bad_date = """
    <ul class="game_details">
        <li><strong>Date:</strong> BadDate</li>
    </ul>
    """
    assert parse_acchockey_game_html(html_bad_date) is None

    # ECU as team 2 (home game)
    html_home = """
    <div class="game_header_v2">
        <a class="teamName">NC State</a>
        <span>2</span>
        <a class="teamName">East Carolina University</a>
        <span>5</span>
    </div>
    <ul class="game_details">
        <li><strong>Date:</strong> Sat Oct 18, 2025</li>
        <li><strong>Time:</strong> 7:00 PM</li>
        <li><strong>Game ID:</strong> ME-25</li>
    </ul>
    """
    rec_home = parse_acchockey_game_html(html_home)
    assert rec_home is not None
    assert rec_home.is_home
    assert rec_home.opponent_name == "NC State University"
    assert rec_home.home_score == 5
    assert rec_home.away_score == 2


def test_url_extraction_helpers() -> None:
    """Verify link extraction for schedules, subseasons, and pagination."""
    # Schedule links
    sched_links = extract_schedule_urls(SAMPLE_SCHEDULE_HTML)
    assert len(sched_links) == 2
    assert "10282704" in sched_links[0]

    # Subseason links
    sub_links = extract_subseason_urls(SAMPLE_SCHEDULE_HTML)
    assert len(sub_links) == 2
    assert any("950924" in url for url in sub_links)
    assert any("966044" in url for url in sub_links)

    # Pagination links
    page_links = extract_pagination_urls(SAMPLE_SCHEDULE_HTML)
    assert len(page_links) == 1
    assert "page=2" in page_links[0]


def test_parser_tag_and_details_branches() -> None:
    """Verify edge case branches in tag parsing, details lists, and name extraction."""
    # 1. _extract_sportengine_game_id with link but non-matching href
    soup_bad_link = BeautifulSoup(
        '<tr><td><a href="/game/show/abc">Link</a></td></tr>',
        "html.parser",
    )
    r_bad = soup_bad_link.find("tr")
    assert r_bad is not None
    assert _extract_sportengine_game_id(r_bad) is None

    # 2. _extract_opponent_info with team_link but empty text
    soup_empty_team = BeautifulSoup(
        '<td><a class="teamName" href="/page/show/100">   </a></td>',
        "html.parser",
    )
    td_empty = soup_empty_team.find("td")
    assert td_empty is not None
    is_h, name, url = _extract_opponent_info(td_empty)
    assert is_h
    assert name == ""
    assert url == "/page/show/100"

    # 3. _extract_tag_classes with string class attribute
    tag_str = BeautifulSoup('<div class="alpha beta"></div>', "html.parser").find("div")
    assert tag_str is not None
    # Simulate parser returning string instead of list
    tag_str["class"] = "alpha beta"
    assert _extract_tag_classes(tag_str) == ["alpha", "beta"]

    # 4. _parse_details_list with empty <strong></strong>
    ul_empty_strong = BeautifulSoup(
        "<ul><li><strong></strong> Empty label text</li></ul>",
        "html.parser",
    ).find("ul")
    assert ul_empty_strong is not None
    assert not _parse_details_list(ul_empty_strong)

    # 5. _collect_unique_names with duplicate and empty link text
    soup_names = BeautifulSoup(
        "<div><a>Alpha</a><a>Alpha</a><a>  </a><a>Beta</a></div>",
        "html.parser",
    )
    links = list(soup_names.find_all("a"))
    assert _collect_unique_names(links) == ["Alpha", "Beta"]


def test_parser_header_and_pagination_branches() -> None:
    """Verify edge case branches in headers, pagination, and non-tag rows."""
    # 6. _extract_header_names with empty header
    div_empty_hdr = BeautifulSoup("<div></div>", "html.parser").find("div")
    assert div_empty_hdr is not None
    assert _extract_header_names(div_empty_hdr) == (
        "East Carolina University",
        "Unknown",
    )

    # 7. _extract_header_scores with only 1 score number
    div_single_score = BeautifulSoup(
        "<div>East Carolina 4 Opponent</div>",
        "html.parser",
    ).find("div")
    assert div_single_score is not None
    assert _extract_header_scores(div_single_score) == (4, None)

    # 8. _resolve_game_page_teams where ECU is team 1 (away)
    opp, is_home, home_s, away_s = _resolve_game_page_teams(
        "East Carolina University",
        "Elon University",
        3,
        5,
    )
    assert opp == "Elon University"
    assert not is_home
    assert home_s == 5
    assert away_s == 3

    # 9. _parse_game_header when header is absent
    soup_no_hdr = BeautifulSoup("<div>No header here</div>", "html.parser")
    assert _parse_game_header(soup_no_hdr) == ("", "", None, None)

    # 10. extract_subseason_urls and extract_pagination_urls duplicate suppression
    html_dups = """
    <select>
        <option value="/subseason=123">S1</option>
        <option value="/subseason=123">S1 Dup</option>
    </select>
    <div class="pagination">
        <a href="/page=2">2</a>
        <a href="/page=2">2 Dup</a>
    </div>
    """
    assert len(extract_subseason_urls(html_dups)) == 1
    assert len(extract_pagination_urls(html_dups)) == 1

    # 11. _parse_table_rows with non-Tag rows
    table_html = (
        "<table>\n<!-- comment -->\n<tr><td>ME-1</td><td>Sat Oct 4</td>"
        "<td>5-2</td><td>Elon</td><td>Rink</td></tr>\n</table>"
    )
    table_soup = BeautifulSoup(table_html, "html.parser")
    table = table_soup.find("table")
    assert table is not None
    assert len(_parse_table_rows(table, "2025-2026")) == 1

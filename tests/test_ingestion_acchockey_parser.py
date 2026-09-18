"""Unit tests for ACCHL SportsEngine schedule and game parser."""

# pylint: disable=too-many-lines,too-many-locals

from __future__ import annotations

from bs4 import BeautifulSoup

from ecu_hockey_calendar.ingestion.acchockey_parser import (
    _cell_text_or_default,
    _collect_unique_names,
    _detect_column_indices,
    _detect_row_columns_by_count,
    _determine_division_and_game_type,
    _extract_cell_team_and_url,
    _extract_header_names,
    _extract_header_scores,
    _extract_opponent_info,
    _extract_row_basic_data,
    _extract_row_cells,
    _extract_row_cells_tuple,
    _extract_score_and_result,
    _extract_split_score,
    _extract_sportengine_game_id,
    _extract_tag_classes,
    _extract_team_instance_schedule_link,
    _extract_time_and_status,
    _find_cell_team_link,
    _find_direct_schedule_links,
    _find_header_col,
    _find_header_indices,
    _get_cell_at,
    _has_valid_scores,
    _is_cell_score_like,
    _is_ecu_name,
    _is_split_headers,
    _is_valid_date_text,
    _needs_fallback_columns,
    _parse_details_list,
    _parse_game_header,
    _parse_int_score,
    _parse_overtime_note,
    _parse_scores_for_record,
    _parse_split_headers,
    _parse_split_table_row,
    _parse_standard_headers,
    _parse_stat_table_row,
    _parse_table_rows,
    _resolve_game_page_teams,
    _resolve_row_columns,
    _resolve_split_opponent,
    _resolve_split_score_cols,
    _TableColumnIndices,
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
        "<tr><td>G1</td><td>99/99/9999</td><td>-</td><td>Elon</td></tr>",
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

    # Scheduled game page without scores
    html_sched = """
    <div class="game_header_v2">
        <a class="teamName">NC State</a>
        <a class="teamName">East Carolina University</a>
    </div>
    <ul class="game_details">
        <li><strong>Date:</strong> Sat Oct 18, 2026</li>
        <li><strong>Time:</strong> 7:00 PM</li>
        <li><strong>Game ID:</strong> ME-99</li>
        <li><strong>Status:</strong> Scheduled</li>
    </ul>
    """
    rec_sched = parse_acchockey_game_html(html_sched)
    assert rec_sched is not None
    assert rec_sched.status == GameStatus.SCHEDULED
    assert rec_sched.home_score is None
    assert rec_sched.away_score is None


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


def test_parse_7_column_schedule_tables() -> None:
    """Verify parsing of 7-column tables with League Game or Game Type."""
    html_league_game = """
    <table class="statTable">
    <thead>
    <tr>
    <th>Game ID</th><th>League Game</th><th>Date</th><th>Result</th>
    <th>Opponent</th><th>Location</th><th>Status</th>
    </tr>
    </thead>
    <tbody>
    <tr id="game_list_row_201" class="completed">
    <td>ME-10</td>
    <td>League</td>
    <td>Sat Oct 08</td>
    <td>
    <div class="scheduleListResult">W</div>
    <div class="scheduleListScore">5-3</div>
    </td>
    <td>vs <a class="teamName" href="/page/show/duke">Duke</a></td>
    <td>Wake Forest Ice House</td>
    <td>Final</td>
    </tr>
    <tr id="game_list_row_202" class="scheduled">
    <td>ME-11</td>
    <td></td>
    <td>Sun Oct 09</td>
    <td>
    <div class="scheduleListResult">-</div>
    <div class="scheduleListScore"></div>
    </td>
    <td>@ <a class="teamName" href="/page/show/elon">Elon</a></td>
    <td>Hillsborough, NC</td>
    <td>3:00 PM EST</td>
    </tr>
    </tbody>
    </table>
    """
    records = parse_acchockey_schedule_html(
        html_league_game,
        default_season="2022-2023",
    )
    assert len(records) == 2
    rec1, rec2 = records[0], records[1]
    assert rec1.opponent_name == "Duke University"
    assert rec1.is_home is True
    assert rec1.home_score == 5
    assert rec1.away_score == 3
    assert rec1.status == GameStatus.FINAL
    assert rec1.venue == "Wake Forest Ice House"

    assert rec2.opponent_name == "Elon University"
    assert rec2.is_home is False
    assert rec2.home_score is None
    assert rec2.away_score is None
    assert rec2.status == GameStatus.SCHEDULED

    # 7-column table with Game Type instead of League Game
    html_game_type = """
    <table class="statTable">
    <thead>
    <tr>
    <th>Game ID</th><th>Game Type</th><th>Date</th><th>Result</th>
    <th>Opponent</th><th>Location</th><th>Status</th>
    </tr>
    </thead>
    <tbody>
    <tr id="game_list_row_301" class="completed">
    <td>ME-20</td>
    <td>Conference</td>
    <td>Fri Nov 12</td>
    <td>
    <div class="scheduleListResult">L</div>
    <div class="scheduleListScore">2-4</div>
    </td>
    <td>vs <a class="teamName" href="/page/show/uncw">UNC Wilmington</a></td>
    <td>The Factory</td>
    <td>Final</td>
    </tr>
    </tbody>
    </table>
    """
    records_gt = parse_acchockey_schedule_html(
        html_game_type,
        default_season="2021-2022",
    )
    assert len(records_gt) == 1
    rec_gt = records_gt[0]
    assert rec_gt.opponent_name == "UNC Wilmington"
    assert rec_gt.home_score == 2
    assert rec_gt.away_score == 4
    assert rec_gt.status == GameStatus.FINAL


def test_parse_8_column_split_schedule_table() -> None:
    """Verify parsing of 2023-2024 8-column table with separate away/home columns."""
    html_split = """
    <table class="statTable">
    <thead>
    <tr>
    <th>Game ID</th><th>Date</th><th>Away</th><th>Score</th>
    <th>Home</th><th>Score</th><th>Location</th><th>Status</th>
    </tr>
    </thead>
    <tbody>
    <!-- ECU is Home, won 6-2 against Duke -->
    <tr id="game_list_row_401" class="completed">
    <td>ME-30</td>
    <td>Sat Oct 21</td>
    <td><a class="teamName" href="/page/show/duke">Duke</a></td>
    <td><div class="scheduleListScore">2</div></td>
    <td><a class="teamName" href="/page/show/ecu">East Carolina University</a></td>
    <td><div class="scheduleListScore">6</div></td>
    <td>Wake Forest Ice House</td>
    <td>Final</td>
    </tr>
    <!-- ECU is Away, won 5-3 in overtime against Charlotte -->
    <tr id="game_list_row_402" class="completed">
    <td>ME-31</td>
    <td>Sat Nov 04</td>
    <td><a class="teamName" href="/page/show/ecu">East Carolina University</a></td>
    <td><div class="scheduleListScore">5 (OT)</div></td>
    <td><a class="teamName" href="/page/show/charlotte">Charlotte</a></td>
    <td><div class="scheduleListScore">3</div></td>
    <td>Pineville Ice House</td>
    <td>Final</td>
    </tr>
    <!-- Scheduled future game, no scores -->
    <tr id="game_list_row_403" class="scheduled">
    <td>ME-32</td>
    <td>Sat Jan 13</td>
    <td><a class="teamName" href="/page/show/elon">Elon</a></td>
    <td>-</td>
    <td><a class="teamName" href="/page/show/ecu">East Carolina</a></td>
    <td>-</td>
    <td>The Factory</td>
    <td>8:00 PM EST</td>
    </tr>
    </tbody>
    </table>
    """
    records = parse_acchockey_schedule_html(html_split, default_season="2023-2024")
    assert len(records) == 3

    r1, r2, r3 = records[0], records[1], records[2]

    # Opponents must be clean team names, not score digits!
    assert r1.opponent_name == "Duke University"
    assert r1.is_home is True
    assert r1.home_score == 6
    assert r1.away_score == 2
    assert r1.status == GameStatus.FINAL
    assert r1.venue == "Wake Forest Ice House"

    assert r2.opponent_name == "UNC Charlotte"
    assert r2.is_home is False
    assert r2.home_score == 3
    assert r2.away_score == 5
    assert r2.overtime_note == "OT"
    assert r2.status == GameStatus.FINAL
    assert r2.venue == "Pineville Ice House"

    assert r3.opponent_name == "Elon University"
    assert r3.is_home is True
    assert r3.home_score is None
    assert r3.away_score is None
    assert r3.status == GameStatus.SCHEDULED


def test_schedule_discovery_from_team_instance_links() -> None:
    """Verify fallback discovery of schedule URLs from team instance links."""
    html_landing_posts = """
    <div>
        <h1>East Carolina University 2026-2027</h1>
        <a href="/posts/team_instance/10618291?subseason=966044">Latest Posts</a>
        <a href="/roster/team_instance/10618291?subseason=966044">Roster</a>
    </div>
    """
    discovered = extract_schedule_urls(html_landing_posts)
    assert len(discovered) == 1
    assert discovered[0] == (
        "https://www.acchockey.com/schedule/team_instance/10618291?subseason=966044"
    )

    # Without subseason query
    html_no_sub = '<div><a href="/roster/team_instance/10618291">Roster</a></div>'
    discovered_no_sub = extract_schedule_urls(html_no_sub)
    assert discovered_no_sub == [
        "https://www.acchockey.com/schedule/team_instance/10618291",
    ]

    # No team instance link
    assert extract_schedule_urls("<div>No links here</div>") == []


def test_column_indices_and_header_helpers() -> None:
    """Verify header detection and column index mapping helpers."""
    split_sample = ["game id", "date", "away", "score", "home", "score"]
    assert _is_split_headers(split_sample) is True
    assert _is_split_headers(["game id", "date", "visitor", "home"]) is True
    assert _is_split_headers(["game id", "date", "result", "opponent"]) is False

    headers_split = [
        "game id",
        "date",
        "away",
        "score",
        "home",
        "score",
        "venue",
        "status",
    ]
    assert _find_header_col(headers_split, ("date",), 0) == 1
    assert _find_header_col(headers_split, ("nonexistent",), 99) == 99
    assert _find_header_indices(headers_split, ("score",)) == [3, 5]
    assert _resolve_split_score_cols(headers_split) == (3, 5)
    assert _resolve_split_score_cols(["no", "scores"]) == (3, 5)

    split_cols = _parse_split_headers(headers_split)
    assert split_cols.is_split is True
    assert split_cols.away_team == 2
    assert split_cols.home_team == 4

    std_headers = [
        "game id",
        "league game",
        "date",
        "result",
        "opponent",
        "location",
        "status",
    ]
    std_cols = _parse_standard_headers(std_headers)
    assert std_cols.is_split is False
    assert std_cols.date == 2
    assert std_cols.score == 3
    assert std_cols.opponent == 4

    # Table without th tags
    soup_empty = BeautifulSoup("<table><tr><td>data</td></tr></table>", "html.parser")
    table_empty = soup_empty.find("table")
    assert table_empty is not None
    assert _detect_column_indices(table_empty) == _TableColumnIndices()


def test_row_column_detection_fallback_and_cells() -> None:
    """Verify fallback row column detection and score checking."""
    assert _is_cell_score_like(None) is False
    soup_cells = BeautifulSoup(
        "<tr><td>ME-1</td><td>League</td><td>Sat Oct 4</td><td>5-2</td>"
        "<td>Elon</td><td>Rink</td><td>Final</td><td>Extra</td></tr>",
        "html.parser",
    )
    row = soup_cells.find("tr")
    assert row is not None
    cells = _extract_row_cells(row)

    assert _is_cell_score_like(cells[3]) is False
    assert _is_cell_score_like(cells[1]) is False
    dash_cell = BeautifulSoup("<td>-</td>", "html.parser").find("td")
    assert _is_cell_score_like(dash_cell) is True

    # 8-cell split detection
    soup_split_cells = BeautifulSoup(
        "<tr><td>ME-1</td><td>Sat Oct 4</td><td>Duke</td><td>3</td>"
        "<td>ECU</td><td>5</td><td>Rink</td><td>Final</td></tr>",
        "html.parser",
    )
    split_row = soup_split_cells.find("tr")
    assert split_row is not None
    split_cells = _extract_row_cells(split_row)
    assert _is_cell_score_like(split_cells[3]) is True
    cols_split = _detect_row_columns_by_count(split_cells)
    assert cols_split.is_split is True

    # 7-cell layout detection
    cols_7 = _detect_row_columns_by_count(cells[:7])
    assert cols_7.date == 2
    assert cols_7.is_split is False

    # 6-cell layout detection (default)
    cols_6 = _detect_row_columns_by_count(cells[:6])
    assert cols_6.date == 1

    # _needs_fallback_columns check
    assert _needs_fallback_columns(cells, _TableColumnIndices(date=1)) is True
    assert _needs_fallback_columns(cells, _TableColumnIndices(date=2)) is False

    # _resolve_row_columns
    resolved = _resolve_row_columns(cells, _TableColumnIndices(date=2))
    assert resolved.date == 2


def test_split_row_helpers_and_edge_cases() -> None:
    """Verify split row helper functions and edge case handling."""
    assert _is_ecu_name("East Carolina University") is True
    assert _is_ecu_name("ECU") is True
    assert _is_ecu_name("East Carolina Club") is True
    assert _is_ecu_name("Duke University") is False
    assert _is_ecu_name("") is False

    soup_links = BeautifulSoup(
        '<div><a class="teamName" href="/p1">Duke</a>'
        '<a href="/page/show/1234">ECU</a><a href="/other">Elon</a></div>',
        "html.parser",
    )
    assert _find_cell_team_link(soup_links) is not None

    instance_cell = BeautifulSoup(
        '<td><a href="/team_instance/1234">Duke</a></td>',
        "html.parser",
    ).find("td")
    assert instance_cell is not None
    assert _find_cell_team_link(instance_cell) is not None

    empty_cell = BeautifulSoup("<td></td>", "html.parser").find("td")
    assert empty_cell is not None
    assert _find_cell_team_link(empty_cell) is None
    assert _extract_cell_team_and_url(None) == ("", "")
    assert _extract_cell_team_and_url(empty_cell) == ("", "")

    empty_link_cell = BeautifulSoup(
        '<td><a href="/team"></a>Fallback</td>',
        "html.parser",
    ).find("td")
    assert empty_link_cell is not None
    assert _extract_cell_team_and_url(empty_link_cell) == ("Fallback", "")

    cell_duke = BeautifulSoup(
        '<td><a class="teamName" href="/duke">Duke</a></td>',
        "html.parser",
    ).find("td")
    cell_ecu = BeautifulSoup(
        '<td><a class="teamName" href="/ecu">ECU</a></td>',
        "html.parser",
    ).find("td")
    cell_elon = BeautifulSoup(
        '<td><a class="teamName" href="/elon">Elon</a></td>',
        "html.parser",
    ).find("td")

    # When away is ECU
    is_home1, opp1, _ = _resolve_split_opponent(cell_ecu, cell_duke)
    assert is_home1 is False
    assert opp1 == "Duke University"

    # When home is ECU
    is_home2, opp2, _ = _resolve_split_opponent(cell_duke, cell_ecu)
    assert is_home2 is True
    assert opp2 == "Duke University"

    # When neither is ECU
    is_home3, opp3, _ = _resolve_split_opponent(cell_duke, cell_elon)
    assert is_home3 is True
    assert opp3 == "Duke University"

    # Score parsing helpers
    assert _parse_int_score("5") == 5
    assert _parse_int_score("invalid") is None
    assert _parse_overtime_note("5 (OT)") == "OT"
    assert _parse_overtime_note("3") is None
    assert _extract_split_score(None) == (None, None)
    assert _extract_split_score(empty_cell) == (None, None)

    assert _has_valid_scores(None, 5) is False
    assert _has_valid_scores(0, 0) is False
    assert _has_valid_scores(5, 2) is True

    assert _cell_text_or_default(None, "def") == "def"
    assert _cell_text_or_default(empty_cell, "def") == "def"

    # _extract_team_instance_schedule_link edge case
    assert (
        _extract_team_instance_schedule_link("/random/link", "https://example.com")
        is None
    )
    assert not _find_direct_schedule_links(soup_links, "https://example.com")


def test_split_table_row_edge_cases() -> None:
    """Verify edge cases when parsing split table rows."""
    # Row with invalid date
    soup_bad_date = BeautifulSoup(
        "<tr><td>ME-1</td><td>Date</td><td>Duke</td><td>2</td>"
        "<td>ECU</td><td>5</td><td>Rink</td><td>Final</td></tr>",
        "html.parser",
    )
    r_bad_date = soup_bad_date.find("tr")
    assert r_bad_date is not None
    cols = _TableColumnIndices(is_split=True)
    cells_bad_date = _extract_row_cells(r_bad_date)
    assert _parse_split_table_row(r_bad_date, cells_bad_date, "2023-2024", cols) is None

    # Row with bad date format that fails parse_game_datetime
    soup_unparseable = BeautifulSoup(
        "<tr><td>ME-1</td><td>99/99/9999</td><td>Duke</td><td>2</td>"
        "<td>ECU</td><td>5</td><td>Rink</td><td>Final</td></tr>",
        "html.parser",
    )
    r_unp = soup_unparseable.find("tr")
    assert r_unp is not None
    cells_unp = _extract_row_cells(r_unp)
    assert _parse_split_table_row(r_unp, cells_unp, "2023-2024", cols) is None

    # Row with missing opponent name
    soup_no_opp = BeautifulSoup(
        "<tr><td>ME-1</td><td>Sat Oct 4</td><td></td><td>-</td>"
        "<td></td><td>-</td><td>Rink</td><td>Final</td></tr>",
        "html.parser",
    )
    r_no_opp = soup_no_opp.find("tr")
    assert r_no_opp is not None
    cells_no_opp = _extract_row_cells(r_no_opp)
    assert _parse_split_table_row(r_no_opp, cells_no_opp, "2023-2024", cols) is None

    # Row with Scheduled status clears scores
    soup_sched = BeautifulSoup(
        "<tr><td>ME-1</td><td>Sat Oct 4</td><td>Duke</td><td>-</td>"
        "<td>ECU</td><td>-</td><td>Rink</td><td>Scheduled</td></tr>",
        "html.parser",
    )
    r_sched = soup_sched.find("tr")
    assert r_sched is not None
    rec_sched = _parse_split_table_row(
        r_sched,
        _extract_row_cells(r_sched),
        "2023-2024",
        cols,
    )
    assert rec_sched is not None
    assert rec_sched.status == GameStatus.SCHEDULED
    assert rec_sched.home_score is None

    # _extract_row_cells_tuple edge cases
    soup_short = BeautifulSoup(
        "<tr><td>ME-1</td><td>Sat Oct 4</td></tr>",
        "html.parser",
    )
    r_short = soup_short.find("tr")
    assert r_short is not None
    cells_short = _extract_row_cells(r_short)
    assert _extract_row_cells_tuple(cells_short, _TableColumnIndices()) is None
    assert _extract_row_basic_data(cells_short) is None

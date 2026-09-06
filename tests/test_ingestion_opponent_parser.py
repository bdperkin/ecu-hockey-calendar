"""Unit tests for opponent schedule feed parsing and verification logic."""

# pylint: disable=protected-access,too-many-lines,too-many-locals

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from ecu_hockey_calendar.ingestion.html_parser import ParsedGameRecord
from ecu_hockey_calendar.ingestion.opponent_parser import (
    DEFAULT_OPPONENT_SPECS,
    HIGH_CONFIDENCE_THRESHOLD,
    Discrepancy,
    DiscrepancyType,
    OpponentDirectory,
    OpponentEndpointConfig,
    OpponentFeedType,
    OpponentFixture,
    ReverseCheckResult,
    VerificationStatus,
    _append_or_extend_ical_line,
    _build_single_json_fixture,
    _build_vevent_fixture,
    _check_summary_at_match,
    _check_summary_vs_match,
    _determine_ical_home_status,
    _extract_cell_text,
    _extract_ecu_game_fields,
    _extract_html_row_dt,
    _extract_html_venue,
    _extract_json_items_list,
    _extract_json_start_dt,
    _fixture_involves_ecu,
    _handle_ical_line,
    _is_html_opponent_home,
    _parse_date_and_time_to_utc,
    _parse_html_row_to_fixture,
    _parse_ical_compact_dt,
    _parse_ical_date_only,
    _parse_vevent_block,
    _resolve_ical_status,
    _resolve_json_home_away,
    _resolve_verification_status,
    _score_date_comparison,
    _score_home_away_alignment,
    _score_start_time_comparison,
    _score_venue_comparison,
    _unfold_ical_lines,
    compare_fixtures,
    cross_check_game_against_opponent,
    filter_ecu_fixtures,
    get_default_opponent_directory,
    is_ecu_match,
    parse_ical_datetime_string,
    parse_opponent_html_feed,
    parse_opponent_ical_feed,
    parse_opponent_json_feed,
)
from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.storage.models import GameModel, GameStatus, TeamModel

SAMPLE_ICAL_FEED = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//UNC Hockey//Schedule//EN
BEGIN:VEVENT
UID:unc-ecu-20261018
DTSTART:20261018T233000Z
DTEND:20261019T020000Z
SUMMARY:UNC Tar Heels vs. East Carolina University
LOCATION:Orange County Sportsplex
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
UID:unc-duke-20261025
DTSTART:20261025T230000Z
SUMMARY:UNC vs Duke
LOCATION:Orange County Sportsplex
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
UID:unc-ecu-away-20261107
DTSTART;VALUE=DATE:20261107
SUMMARY:UNC at ECU Pirates
LOCATION:Carolina Ice Palace
STATUS:POSTPONED
END:VEVENT
END:VCALENDAR"""

SAMPLE_JSON_FEED = {
    "games": [
        {
            "id": "vt-1",
            "date": "2026-10-18",
            "time": "7:30 PM",
            "opponent": "East Carolina University",
            "location": "Lancerlot Sports Complex",
            "is_home": True,
            "status": "scheduled",
        },
        {
            "id": "vt-2",
            "date": "2026-11-01",
            "time": "14:00",
            "opponent": "NC State",
            "venue": "Lancerlot Sports Complex",
            "home_away": "home",
        },
        {
            "id": "vt-3",
            "start_time": "2026-11-15T19:00:00Z",
            "summary": "Virginia Tech at ECU",
            "home_away": "away",
            "venue": "Carolina Ice Palace",
            "status": "canceled",
        },
    ],
}

SAMPLE_HTML_FEED = """
<html>
<body>
    <table>
        <tr><th>Date</th><th>Opponent</th><th>Time</th><th>Location</th></tr>
        <tr>
            <td>10/18/2026</td>
            <td>East Carolina University</td>
            <td>7:30 PM</td>
            <td>The Factory Ice House</td>
        </tr>
        <tr>
            <td>10/25/2026</td>
            <td>Duke Blue Devils</td>
            <td>8:00 PM</td>
            <td>Wake Competition Center</td>
        </tr>
        <tr>
            <td>11/07/2026</td>
            <td>@ ECU Pirates</td>
            <td>4:00 PM</td>
            <td>Carolina Ice Palace</td>
        </tr>
    </table>
</body>
</html>
"""


def test_discrepancy_dataclass_and_dict() -> None:
    """Verify Discrepancy dataclass serialization to dictionary."""
    disc = Discrepancy(
        discrepancy_type=DiscrepancyType.START_TIME,
        field_name="start_time",
        ecu_value="19:00",
        opponent_value="19:30",
        severity="high",
    )
    d = disc.to_dict()
    assert d["discrepancy_type"] == "start_time"
    assert d["field_name"] == "start_time"
    assert d["ecu_value"] == "19:00"
    assert d["opponent_value"] == "19:30"
    assert d["severity"] == "high"


def test_opponent_fixture_dataclass_and_dict() -> None:
    """Verify OpponentFixture serialization to dictionary."""
    now = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    end = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)
    fix = OpponentFixture(
        opponent_name="UNC",
        summary="UNC vs ECU",
        start_time=now,
        end_time=end,
        venue="Orange County Sportsplex",
        is_opponent_home=True,
        status=GameStatus.SCHEDULED,
    )
    d = fix.to_dict()
    assert d["opponent_name"] == "UNC"
    assert d["start_time"] == now.isoformat()
    assert d["end_time"] == end.isoformat()
    assert d["venue"] == "Orange County Sportsplex"
    assert d["is_opponent_home"] is True
    assert d["status"] == "SCHEDULED"

    fix_no_end = OpponentFixture(
        opponent_name="UNC",
        summary="UNC vs ECU",
        start_time=now,
    )
    assert fix_no_end.to_dict()["end_time"] is None


def test_reverse_check_result_dataclass_and_dict() -> None:
    """Verify ReverseCheckResult serialization to dictionary."""
    disc = Discrepancy(
        discrepancy_type=DiscrepancyType.VENUE,
        field_name="venue",
        ecu_value="Rink A",
        opponent_value="Rink B",
    )
    now = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    fixture = OpponentFixture(
        opponent_name="UNC",
        summary="UNC vs ECU",
        start_time=now,
    )
    res = ReverseCheckResult(
        ecu_game_id="game-123",
        opponent_canonical_name="UNC",
        verification_status=VerificationStatus.DISCREPANCY,
        confidence_score=0.75,
        matched_fixture=fixture,
        discrepancies=[disc],
        time_difference_minutes=0,
        home_away_aligned=True,
        venue_matched=False,
        notes="Venue mismatch detected",
    )
    d = res.to_dict()
    assert d["ecu_game_id"] == "game-123"
    assert d["opponent_canonical_name"] == "UNC"
    assert d["verification_status"] == "discrepancy"
    assert d["confidence_score"] == 0.75
    assert d["matched_fixture"] is not None
    assert len(d["discrepancies"]) == 1
    assert d["venue_matched"] is False
    assert d["notes"] == "Venue mismatch detected"

    empty_res = ReverseCheckResult(
        ecu_game_id=None,
        opponent_canonical_name="Unknown",
        verification_status=VerificationStatus.UNAVAILABLE,
        confidence_score=0.0,
    )
    assert empty_res.to_dict()["ecu_game_id"] is None
    assert empty_res.to_dict()["matched_fixture"] is None


def test_opponent_directory_registration_and_lookup() -> None:
    """Test opponent directory registration, alias matching, and properties."""
    dir_obj = OpponentDirectory()
    assert not dir_obj.list_endpoints()

    cfg = OpponentEndpointConfig(
        canonical_name="University of North Carolina",
        feed_url="https://unchockey.com/calendar.ics",
        feed_type=OpponentFeedType.ICAL,
        home_venue="Orange County Sportsplex",
        aliases=("UNC", "North Carolina", "Tar Heels"),
    )
    dir_obj.register(cfg)

    assert "UNC" in dir_obj
    assert "Tar Heels" in dir_obj
    assert "North Carolina" in dir_obj
    assert "University of North Carolina" in dir_obj
    assert "Duke" not in dir_obj

    res = dir_obj.get("UNC")
    assert res is not None
    assert res.canonical_name == "University of North Carolina"

    res_alias = dir_obj.get("Tar Heels")
    assert res_alias is not None
    assert res_alias.canonical_name == "University of North Carolina"

    assert dir_obj.get("Duke") is None
    assert len(dir_obj.list_endpoints()) == 1


def test_get_default_opponent_directory() -> None:
    """Verify standard collegiate opponents exist in default directory."""
    dir_obj = get_default_opponent_directory()
    assert len(dir_obj.list_endpoints()) == len(DEFAULT_OPPONENT_SPECS)

    for name, _, _, _, aliases in DEFAULT_OPPONENT_SPECS:
        assert dir_obj.get(name) is not None
        for alias in aliases:
            assert dir_obj.get(alias) is not None


def test_is_ecu_match() -> None:
    """Test ECU institution name identification variants."""
    assert is_ecu_match("East Carolina")
    assert is_ecu_match("East Carolina University")
    assert is_ecu_match("ECU")
    assert is_ecu_match("ECU Pirates")
    assert is_ecu_match("Pirates")
    assert not is_ecu_match("UNC")
    assert not is_ecu_match("NC State")
    assert not is_ecu_match("Duke")


def test_unfold_ical_lines() -> None:
    """Test unfolding RFC 5545 lines with tab and space continuations."""
    raw = (
        "SUMMARY:UNC Tar\r\n"
        "  Heels vs.\r\n"
        "\t East Carolina\r\n"
        "LOCATION:The\r\n"
        "  Factory\r\n"
        "\r\n"
        "STATUS:CONFIRMED"
    )
    lines = _unfold_ical_lines(raw)
    assert lines[0] == "SUMMARY:UNC Tar Heels vs. East Carolina"
    assert lines[1] == "LOCATION:The Factory"
    assert lines[2] == "STATUS:CONFIRMED"

    unfolded: list[str] = []
    _append_or_extend_ical_line(" FIRST", unfolded)
    assert unfolded[0] == "FIRST"


def test_parse_ical_datetime_string() -> None:
    """Test iCalendar datetime parsing for various timestamp representations."""
    dt_compact = parse_ical_datetime_string("20261018T233000Z")
    assert dt_compact is not None
    assert dt_compact == datetime(2026, 10, 18, 23, 30, tzinfo=UTC)

    dt_local = parse_ical_datetime_string("20261018T193000")
    assert dt_local is not None
    eastern = ZoneInfo("America/New_York")
    expected_local = datetime(2026, 10, 18, 19, 30, tzinfo=eastern).astimezone(UTC)
    assert dt_local == expected_local

    chicago = ZoneInfo("America/Chicago")
    dt_chicago = parse_ical_datetime_string("20261018T193000", default_tz=chicago)
    assert dt_chicago is not None
    assert dt_chicago == datetime(2026, 10, 18, 19, 30, tzinfo=chicago).astimezone(UTC)

    dt_date_only = parse_ical_datetime_string("20261018")
    assert dt_date_only is not None
    expected_date = datetime(2026, 10, 18, 19, 0, tzinfo=eastern).astimezone(UTC)
    assert dt_date_only == expected_date

    assert parse_ical_datetime_string("") is None
    assert parse_ical_datetime_string("INVALID") is None
    assert _parse_ical_compact_dt("BADVAL", eastern) is None
    assert _parse_ical_compact_dt("20269999T230000", eastern) is None
    assert _parse_ical_date_only("BADVAL", eastern) is None
    assert _parse_ical_date_only("20269999", eastern) is None


def test_parse_opponent_json_edge_items() -> None:
    """Test parsing JSON schedule containing non-dict and invalid items."""
    mixed_items = [
        "not-a-dict",
        {"no_valid_date": "value"},
        {"date": "2026-10-18", "opponent": "ECU"},
    ]
    fixtures = parse_opponent_json_feed(mixed_items, "Virginia Tech")
    assert len(fixtures) == 1
    assert fixtures[0].opponent_name == "Virginia Tech"


def test_parse_opponent_ical_feed() -> None:
    """Test full parsing of RFC 5545 iCalendar schedule payload."""
    fixtures = parse_opponent_ical_feed(SAMPLE_ICAL_FEED, "UNC")
    assert len(fixtures) == 3

    f1 = fixtures[0]
    assert f1.opponent_name == "UNC"
    assert f1.is_opponent_home is True
    assert f1.venue == "Orange County Sportsplex"

    f2 = fixtures[1]
    assert f2.opponent_name == "UNC"
    assert f2.is_opponent_home is True

    f3 = fixtures[2]
    assert f3.opponent_name == "UNC"
    assert f3.is_opponent_home is False
    assert f3.status == GameStatus.POSTPONED

    cancelled_vevent = (
        "BEGIN:VCALENDAR\n"
        "BEGIN:VEVENT\n"
        "DTSTART:20261018T230000Z\n"
        "STATUS:CANCELLED\n"
        "SUMMARY:ECU @ UNC\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )
    c_fixtures = parse_opponent_ical_feed(cancelled_vevent, "UNC")
    assert len(c_fixtures) == 1
    assert c_fixtures[0].status == GameStatus.CANCELLED
    assert c_fixtures[0].is_opponent_home is True


def test_summary_home_status_variations() -> None:
    """Test home/away detection across various summary delimiter syntaxes."""
    assert _check_summary_at_match("unc at ecu") is False
    assert _check_summary_at_match("ecu at unc") is True
    assert _check_summary_at_match("ecu @ unc") is True
    assert _check_summary_at_match("no delimiter here") is None
    assert _check_summary_at_match("unc at duke") is None

    assert _check_summary_vs_match("unc vs. ecu") is True
    assert _check_summary_vs_match("ecu vs. unc") is False
    assert _check_summary_vs_match("unc vs ecu") is True
    assert _check_summary_vs_match("no delimiter here") is None
    assert _check_summary_vs_match("unc vs duke") is None

    assert _determine_ical_home_status("ECU @ UNC") is True
    assert _determine_ical_home_status("UNC vs ECU") is True
    assert (
        _determine_ical_home_status("Neutral Showcase Game", default_home=False)
        is False
    )


def test_resolve_ical_status() -> None:
    """Test resolution of iCal status property strings to GameStatus."""
    assert _resolve_ical_status("CONFIRMED") == GameStatus.SCHEDULED
    assert _resolve_ical_status("CANCELLED") == GameStatus.CANCELLED
    assert _resolve_ical_status("cancelled") == GameStatus.CANCELLED
    assert _resolve_ical_status("POSTPONED") == GameStatus.POSTPONED
    assert _resolve_ical_status("postponed") == GameStatus.POSTPONED
    assert _resolve_ical_status("TENTATIVE") == GameStatus.SCHEDULED


def test_vevent_block_missing_or_invalid() -> None:
    """Test vevent block handling when properties are malformed or missing."""
    assert _build_vevent_fixture({}, "UNC") is None
    assert _build_vevent_fixture({"DTSTART": "INVALID"}, "UNC") is None
    assert _parse_vevent_block(["NO_COLON_LINE"], "UNC") is None

    fixtures: list[OpponentFixture] = []
    res_none = _handle_ical_line("OTHER:LINE", None, "UNC", fixtures)
    assert res_none is None
    assert not fixtures

    res_begin = _handle_ical_line("BEGIN:VEVENT", None, "UNC", fixtures)
    assert res_begin == []

    res_end = _handle_ical_line("END:VEVENT", ["NO_COLON_LINE"], "UNC", fixtures)
    assert res_end is None
    assert not fixtures

    res_end_none = _handle_ical_line("END:VEVENT", None, "UNC", fixtures)
    assert res_end_none is None
    assert not fixtures

    res_append = _handle_ical_line("SUMMARY:Test", [], "UNC", fixtures)
    assert res_append == ["SUMMARY:Test"]


def test_time_parsing_helpers() -> None:
    """Test datetime and time parsing helper functions."""
    assert _parse_date_and_time_to_utc("invalid_date", "7:00 PM") is None
    dt_parsed = _parse_date_and_time_to_utc("2026-10-18", "7:30 PM")
    assert dt_parsed is not None
    assert dt_parsed.hour == 23
    assert dt_parsed.minute == 30
    assert _parse_date_and_time_to_utc("2026-10-18T23:30:00Z", None) == dt_parsed


def test_parse_opponent_json_feed() -> None:
    """Test parsing JSON schedule payloads with varied formats and schemas."""
    fixtures = parse_opponent_json_feed(SAMPLE_JSON_FEED, "Virginia Tech")
    assert len(fixtures) == 3

    f1 = fixtures[0]
    assert f1.opponent_name == "Virginia Tech"
    assert f1.is_opponent_home is True
    assert f1.venue == "Lancerlot Sports Complex"

    f2 = fixtures[1]
    assert f2.opponent_name == "Virginia Tech"
    assert f2.is_opponent_home is True
    assert f2.venue == "Lancerlot Sports Complex"

    f3 = fixtures[2]
    assert f3.opponent_name == "Virginia Tech"
    assert f3.is_opponent_home is False
    assert f3.venue == "Carolina Ice Palace"

    list_payload = [{"date": "2026-10-18", "opponent": "ECU"}]
    f_list = parse_opponent_json_feed(list_payload, "Virginia Tech")
    assert len(f_list) == 1

    dict_variants = {
        "events": [{"date": "2026-10-18", "opponent": "ECU"}],
    }
    assert len(parse_opponent_json_feed(dict_variants, "VT")) == 1

    dict_schedule = {
        "schedule": [{"date": "2026-10-18", "opponent": "ECU"}],
    }
    assert len(parse_opponent_json_feed(dict_schedule, "VT")) == 1

    dict_data = {
        "data": [{"date": "2026-10-18", "opponent": "ECU"}],
    }
    assert len(parse_opponent_json_feed(dict_data, "VT")) == 1

    dict_fixtures = {
        "fixtures": [{"date": "2026-10-18", "opponent": "ECU"}],
    }
    assert len(parse_opponent_json_feed(dict_fixtures, "VT")) == 1

    empty_data: dict[str, Any] = {}
    assert not parse_opponent_json_feed(empty_data, "VT")
    assert not parse_opponent_json_feed("NOT_A_DICT_OR_LIST", "VT")  # type: ignore[arg-type]


def test_json_helper_functions_and_branches() -> None:
    """Test helper functions parsing JSON opponent items."""
    assert _extract_json_items_list({"other": [1, 2]}) == []

    assert _resolve_json_home_away({"is_home": True}) is True
    assert _resolve_json_home_away({"home_away": "home"}) is True
    assert _resolve_json_home_away({"home_away": "away"}) is False
    assert _resolve_json_home_away({"summary": "ECU @ VT"}) is True

    assert _extract_json_start_dt({"datetime": "2026-10-18T23:30:00Z"}) is not None
    assert _extract_json_start_dt({}) is None

    assert _build_single_json_fixture({"no_date": 1}, "VT") is None


def test_parse_opponent_html_feed() -> None:
    """Test parsing HTML schedule tables for opponent fixtures."""
    fixtures = parse_opponent_html_feed(SAMPLE_HTML_FEED, "NC State")
    assert len(fixtures) == 2

    f1 = fixtures[0]
    assert f1.opponent_name == "NC State"
    assert f1.is_opponent_home is True
    assert f1.venue == "The Factory Ice House"

    f2 = fixtures[1]
    assert f2.opponent_name == "NC State"
    assert f2.is_opponent_home is False
    assert f2.venue == "Carolina Ice Palace"

    empty_html = "<html><body><p>No table</p></body></html>"
    assert not parse_opponent_html_feed(empty_html, "NC State")


def test_html_helper_functions() -> None:
    """Test helper functions parsing HTML table elements."""
    soup = BeautifulSoup(
        "<table><tr><td>2026-10-18</td><td>ECU</td>"
        "<td>7:30 PM</td><td>Rink</td></tr></table>",
        "html.parser",
    )
    row = soup.find("tr")
    assert isinstance(row, Tag)
    cells = row.find_all(["td", "th"])

    assert _extract_cell_text(row, 0) == "2026-10-18"
    assert _extract_cell_text(row, 99) == ""
    assert _extract_html_venue(row, cells) == "Rink"
    assert _extract_html_venue(row, cells[:2]) == "TBD"

    assert _is_html_opponent_home("ECU vs UNC") is True
    assert _is_html_opponent_home("@ ECU") is False
    assert _is_html_opponent_home("UNC at ECU") is False

    assert _extract_html_row_dt(row, cells) is not None
    assert _extract_html_row_dt(row, cells[:2]) is not None

    empty_row = BeautifulSoup("<tr><td>Single Cell</td></tr>", "html.parser").find("tr")
    assert isinstance(empty_row, Tag)
    assert _parse_html_row_to_fixture(empty_row, "UNC") is None

    no_ecu_row = BeautifulSoup(
        "<tr><td>2026-10-18</td><td>Duke</td></tr>",
        "html.parser",
    ).find("tr")
    assert isinstance(no_ecu_row, Tag)
    assert _parse_html_row_to_fixture(no_ecu_row, "UNC") is None

    invalid_dt_row = BeautifulSoup(
        "<tr><td>INVALID</td><td>ECU</td><td>7:30 PM</td></tr>",
        "html.parser",
    ).find("tr")
    assert isinstance(invalid_dt_row, Tag)
    assert _parse_html_row_to_fixture(invalid_dt_row, "UNC") is None


def test_filter_ecu_fixtures() -> None:
    """Test filtering fixture list down to only ECU matchups."""
    now = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    f_ecu = OpponentFixture(
        opponent_name="UNC",
        summary="UNC vs ECU",
        start_time=now,
    )
    f_other = OpponentFixture(
        opponent_name="UNC",
        summary="UNC vs Duke",
        start_time=now,
    )
    f_raw = OpponentFixture(
        opponent_name="UNC",
        summary="Game 3",
        start_time=now,
        raw_details={"opponent": "East Carolina Pirates"},
    )
    filtered = filter_ecu_fixtures([f_ecu, f_other, f_raw])
    assert len(filtered) == 2
    assert _fixture_involves_ecu(f_ecu) is True
    assert _fixture_involves_ecu(f_other) is False
    assert _fixture_involves_ecu(f_raw) is True


def test_extract_ecu_game_fields() -> None:
    """Test field extraction from Game, GameModel, and ParsedGameRecord."""
    dt = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    t1 = Team(name="East Carolina University", city="Greenville", state="NC")
    t2 = Team(name="UNC", city="Chapel Hill", state="NC")

    game = Game(
        game_id="g1",
        home_team=t1,
        away_team=t2,
        start_time=dt,
        venue="Rink 1",
    )
    gid, opp, st, ven, ih = _extract_ecu_game_fields(game)
    assert gid == "g1"
    assert opp == "UNC"
    assert st == dt
    assert ven == "Rink 1"
    assert ih is True

    # Away game
    game_away = Game(
        game_id="g2",
        home_team=t2,
        away_team=t1,
        start_time=dt,
        venue="Rink 2",
    )
    _, opp_away, _, _, ih_away = _extract_ecu_game_fields(game_away)
    assert opp_away == "UNC"
    assert ih_away is False

    # ParsedGameRecord
    parsed_rec = ParsedGameRecord(
        game_id="prec-1",
        opponent_name="UNC",
        start_time=dt,
        venue="Rink 3",
        is_home=True,
    )
    pgid, popp, pst, pven, pih = _extract_ecu_game_fields(parsed_rec)
    assert pgid == "prec-1"
    assert popp == "UNC"
    assert pst == dt
    assert pven == "Rink 3"
    assert pih is True


def test_scoring_helpers() -> None:
    """Test individual scoring helper functions."""
    dt1 = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    dt2 = datetime(2026, 10, 19, 23, 30, tzinfo=UTC)  # 1 day diff
    dt3 = datetime(2026, 10, 25, 23, 30, tzinfo=UTC)  # Multi-day diff

    s_exact, d_exact = _score_date_comparison(dt1, dt1)
    assert s_exact > 0
    assert not d_exact

    s_adj, d_adj = _score_date_comparison(dt1, dt2)
    assert s_adj > 0
    assert len(d_adj) == 1

    s_far, d_far = _score_date_comparison(dt1, dt3)
    assert s_far == 0.0
    assert len(d_far) == 1

    # Home/away
    s_ha_ok, d_ha_ok = _score_home_away_alignment(ecu_is_home=True, opp_is_home=False)
    assert s_ha_ok > 0
    assert not d_ha_ok

    s_ha_bad, d_ha_bad = _score_home_away_alignment(ecu_is_home=True, opp_is_home=True)
    assert s_ha_bad == 0.0
    assert len(d_ha_bad) == 1

    # Start time
    s_t_exact, diff_0, dt_0 = _score_start_time_comparison(dt1, dt1)
    assert s_t_exact > 0
    assert diff_0 == 0
    assert not dt_0

    dt_near = dt1 + datetime.resolution * 30 * 60 * 1000000  # 30 mins later
    s_t_near, diff_30, dt_near_disc = _score_start_time_comparison(dt1, dt_near)
    assert s_t_near > 0
    assert diff_30 == 30
    assert len(dt_near_disc) == 1

    dt_far = dt1 + datetime.resolution * 120 * 60 * 1000000  # 120 mins later
    s_t_far, diff_120, dt_far_disc = _score_start_time_comparison(dt1, dt_far)
    assert s_t_far == 0.0
    assert diff_120 == 120
    assert len(dt_far_disc) == 1

    # Venue
    s_v_match, m_v_match, dv_match = _score_venue_comparison(
        "Carolina Ice Palace",
        "carolina ice palace",
    )
    assert s_v_match > 0
    assert m_v_match is True
    assert not dv_match

    s_v_tbd, m_v_tbd, dv_tbd = _score_venue_comparison("TBD", "Some Rink")
    assert s_v_tbd > 0
    assert m_v_tbd is True
    assert not dv_tbd

    s_v_bad, m_v_bad, dv_bad = _score_venue_comparison("Rink A", "Rink B")
    assert s_v_bad == 0.0
    assert m_v_bad is False
    assert len(dv_bad) == 1


def test_compare_fixtures_exact_alignment() -> None:
    """Test fixture comparison with perfectly matching schedule parameters."""
    dt = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    ecu_team = Team(name="East Carolina University", city="Greenville", state="NC")
    opp_team = Team(name="NC State Icepack", city="Raleigh", state="NC")

    ecu_game = Game(
        game_id="game-1",
        home_team=ecu_team,
        away_team=opp_team,
        start_time=dt,
        venue="The Factory Ice House",
    )
    opp_fix = OpponentFixture(
        opponent_name="NC State",
        summary="NC State at ECU",
        start_time=dt,
        venue="The Factory Ice House",
        is_opponent_home=False,  # Aligned with ECU being home!
        status=GameStatus.SCHEDULED,
    )

    score, discs, diff_min, ha_aligned, ven_match = compare_fixtures(ecu_game, opp_fix)
    assert score >= HIGH_CONFIDENCE_THRESHOLD
    assert ha_aligned is True
    assert ven_match is True
    assert diff_min == 0
    assert not discs

    v_status = _resolve_verification_status(score, discs)
    assert v_status == VerificationStatus.VERIFIED


def test_compare_fixtures_discrepancies() -> None:
    """Test fixture comparison detecting time, date, venue, and status conflicts."""
    dt_ecu = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    dt_opp = datetime(2026, 10, 19, 1, 0, tzinfo=UTC)  # 90 minutes later!
    ecu_team = Team(name="East Carolina University", city="Greenville", state="NC")
    opp_team = Team(name="NC State Icepack", city="Raleigh", state="NC")

    ecu_game = Game(
        game_id="game-1",
        home_team=ecu_team,
        away_team=opp_team,
        start_time=dt_ecu,
        venue="The Factory Ice House",
        result=GameResult.SCHEDULED,
    )
    opp_fix = OpponentFixture(
        opponent_name="NC State",
        summary="NC State vs ECU",
        start_time=dt_opp,
        venue="Wake Competition Center",
        is_opponent_home=True,  # Conflict: both claim home!
        status=GameStatus.CANCELLED,
    )

    score, discs, diff_min, ha_aligned, ven_match = compare_fixtures(ecu_game, opp_fix)
    assert score < HIGH_CONFIDENCE_THRESHOLD
    assert ha_aligned is False
    assert ven_match is False
    assert diff_min == 90
    assert len(discs) == 3

    v_status = _resolve_verification_status(score, discs)
    assert v_status == VerificationStatus.DISCREPANCY


def test_cross_check_game_against_opponent_scenarios() -> None:
    """Test cross_check_game_against_opponent scenarios and edge cases."""
    dt = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    ecu_team = Team(name="East Carolina University", city="Greenville", state="NC")
    opp_team = Team(name="UNC", city="Chapel Hill", state="NC")

    ecu_game = Game(
        game_id="game-3",
        home_team=ecu_team,
        away_team=opp_team,
        start_time=dt,
        venue="Carolina Ice Palace",
    )

    # Scenario 1: Empty fixtures list -> UNVERIFIED
    res_empty = cross_check_game_against_opponent(ecu_game, [], "UNC")
    assert res_empty.verification_status == VerificationStatus.UNVERIFIED
    assert res_empty.confidence_score == 0.0

    # Scenario 2: Fixtures present but on other dates -> UNVERIFIED
    dt_other = datetime(2026, 11, 20, 23, 30, tzinfo=UTC)
    f_other = OpponentFixture(
        opponent_name="UNC",
        summary="UNC vs ECU",
        start_time=dt_other,
    )
    res_unverified = cross_check_game_against_opponent(ecu_game, [f_other], "UNC")
    assert res_unverified.verification_status == VerificationStatus.UNVERIFIED
    assert res_unverified.confidence_score == 0.0

    # Scenario 3: Matching fixture present -> VERIFIED
    f_match = OpponentFixture(
        opponent_name="UNC",
        summary="UNC at ECU",
        start_time=dt,
        venue="Carolina Ice Palace",
        is_opponent_home=False,
    )
    res_verified = cross_check_game_against_opponent(
        ecu_game,
        [f_match, f_other],
        "UNC",
    )
    assert res_verified.verification_status == VerificationStatus.VERIFIED
    assert res_verified.matched_fixture == f_match

    # Scenario 4: GameModel ORM entity support
    home_orm = TeamModel(name="East Carolina University", city="Greenville", state="NC")
    away_orm = TeamModel(name="UNC", city="Chapel Hill", state="NC")
    game_orm = GameModel(
        game_id="orm-game-1",
        home_team=home_orm,
        away_team=away_orm,
        start_time=dt,
        venue="Carolina Ice Palace",
    )
    res_orm = cross_check_game_against_opponent(game_orm, [f_match], "UNC")
    assert res_orm.verification_status == VerificationStatus.VERIFIED

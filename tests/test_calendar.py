"""Tests for ECUHockeyCalendar service and export capabilities."""

import json
from datetime import UTC, datetime

import pytest

from ecu_hockey_calendar.calendar import ECUHockeyCalendar
from ecu_hockey_calendar.models import Team


def test_calendar_initialization_defaults() -> None:
    """Test calendar initializes with expected default team and season."""
    calendar = ECUHockeyCalendar()
    assert calendar.season == "2026-2027"
    assert calendar.team.name == "East Carolina University"
    assert calendar.schedule.total_games == 0


def test_calendar_custom_team(unc_team: Team) -> None:
    """Test calendar initialization with custom team and season."""
    calendar = ECUHockeyCalendar(season="2025-2026", team=unc_team)
    assert calendar.season == "2025-2026"
    assert calendar.team == unc_team


def test_add_match_home_and_away(unc_team: Team) -> None:
    """Test scheduling both home and away matches."""
    calendar = ECUHockeyCalendar(season="2026-2027")

    # Home match with generated ID
    game1 = calendar.add_match(
        opponent=unc_team,
        start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
        venue="The Factory Ice House",
        is_home=True,
    )
    assert game1.game_id == "ECU-2026-2027-01"
    assert game1.home_team.name == "East Carolina University"
    assert game1.away_team == unc_team

    # Away match with custom ID
    game2 = calendar.add_match(
        opponent=unc_team,
        start_time=datetime(2026, 11, 7, 18, 0, tzinfo=UTC),
        venue="Orange County Sportsplex",
        is_home=False,
        game_id="CUSTOM-AWAY-01",
    )
    assert game2.game_id == "CUSTOM-AWAY-01"
    assert game2.home_team == unc_team
    assert game2.away_team.name == "East Carolina University"
    assert calendar.schedule.total_games == 2


def test_add_match_invalid_duration(unc_team: Team) -> None:
    """Test add_match raises ValueError when duration is non-positive."""
    calendar = ECUHockeyCalendar()
    with pytest.raises(
        ValueError,
        match="Duration hours must be greater than zero",
    ):
        calendar.add_match(
            opponent=unc_team,
            start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
            venue="Arena",
            duration_hours=0,
        )


def test_export_ics(unc_team: Team) -> None:
    """Test RFC 5545 iCalendar serialization."""
    calendar = ECUHockeyCalendar(season="2026-2027")
    calendar.add_match(
        opponent=unc_team,
        start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
        venue="The Factory Ice House",
        is_home=True,
    )
    calendar.add_match(
        opponent=unc_team,
        start_time=datetime(2026, 11, 7, 18, 0, tzinfo=UTC),
        venue="Orange County Sportsplex",
        is_home=False,
    )

    ics_content = calendar.export_ics()
    assert ics_content.startswith("BEGIN:VCALENDAR\r\n")
    assert "VERSION:2.0" in ics_content
    assert "PRODID:-//ECU Ice Hockey//Calendar//EN" in ics_content
    assert "SUMMARY:ECU Hockey vs UNC Chapel Hill" in ics_content
    assert "SUMMARY:ECU Hockey at UNC Chapel Hill" in ics_content
    assert "END:VCALENDAR\r\n" in ics_content


def test_export_json(unc_team: Team) -> None:
    """Test JSON serialization output structure and validity."""
    calendar = ECUHockeyCalendar(season="2026-2027")
    calendar.add_match(
        opponent=unc_team,
        start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
        venue="The Factory Ice House",
    )

    json_str = calendar.export_json()
    parsed = json.loads(json_str)

    assert parsed["season"] == "2026-2027"
    assert parsed["team"]["name"] == "East Carolina University"
    assert parsed["schedule"]["total_games"] == 1
    assert len(parsed["schedule"]["games"]) == 1


def test_export_csv(unc_team: Team) -> None:
    """Test CSV export format and values."""
    calendar = ECUHockeyCalendar(season="2026-2027")
    calendar.add_match(
        opponent=unc_team,
        start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
        venue="The Factory Ice House",
        is_home=True,
    )
    calendar.add_match(
        opponent=unc_team,
        start_time=datetime(2026, 11, 7, 18, 0, tzinfo=UTC),
        venue="Orange County Sportsplex",
        is_home=False,
    )

    csv_content = calendar.export_csv()
    lines = csv_content.strip().split("\n")
    assert lines[0] == "game_id,date,time,home_team,away_team,venue,is_home,result"
    assert len(lines) == 3
    ecu_host_str = (
        "East Carolina University,UNC Chapel Hill,The Factory Ice House,Yes,SCHEDULED"
    )
    unc_host_str = (
        "UNC Chapel Hill,East Carolina University,Orange County Sportsplex,No,SCHEDULED"
    )
    assert ecu_host_str in lines[1]
    assert unc_host_str in lines[2]


def test_export_rss(unc_team: Team) -> None:
    """Test RSS 2.0 export on ECUHockeyCalendar."""
    calendar = ECUHockeyCalendar(season="2026-2027")
    calendar.add_match(
        opponent=unc_team,
        start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
        venue="The Factory Ice House",
        is_home=True,
    )
    rss_xml = calendar.export_rss(feed_url="https://ecuhockey.com/feed.rss")
    assert "<rss" in rss_xml
    assert 'version="2.0"' in rss_xml
    assert "ECU Men's Ice Hockey Schedule" in rss_xml
    assert "ECU Hockey vs UNC Chapel Hill" in rss_xml


def test_export_atom(unc_team: Team) -> None:
    """Test Atom 1.0 export on ECUHockeyCalendar."""
    calendar = ECUHockeyCalendar(season="2026-2027")
    calendar.add_match(
        opponent=unc_team,
        start_time=datetime(2026, 11, 6, 19, 30, tzinfo=UTC),
        venue="The Factory Ice House",
        is_home=True,
    )
    atom_xml = calendar.export_atom(feed_url="https://ecuhockey.com/feed.atom")
    assert "<feed" in atom_xml
    assert "http://www.w3.org/2005/Atom" in atom_xml
    assert "ECU Men's Ice Hockey Schedule" in atom_xml
    assert "ECU Hockey vs UNC Chapel Hill" in atom_xml

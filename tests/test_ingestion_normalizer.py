"""Tests for ingestion data normalization utilities."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from ecu_hockey_calendar.ingestion.normalizer import (
    DEFAULT_TIMEZONE,
    normalize_team_name,
    parse_game_datetime,
    parse_game_score,
    parse_game_status,
)
from ecu_hockey_calendar.storage.models import GameStatus


def test_normalize_team_name() -> None:
    """Verify team name normalization across variations, prefixes, and edge cases."""
    assert normalize_team_name("ECU") == "East Carolina University"
    assert normalize_team_name("east carolina") == "East Carolina University"
    assert normalize_team_name("East Carolina Univ") == "East Carolina University"
    assert normalize_team_name("uncw") == "UNC Wilmington"
    assert normalize_team_name("UNC-Wilmington") == "UNC Wilmington"
    assert normalize_team_name("unc") == "UNC Chapel Hill"
    assert normalize_team_name("NC State") == "NC State University"
    assert normalize_team_name("App State") == "Appalachian State University"
    assert normalize_team_name("VT") == "Virginia Tech"
    assert normalize_team_name("Alabama D2") == "University of Alabama (D2)"
    assert normalize_team_name("Alabama D3") == "University of Alabama (D3)"
    assert normalize_team_name("Wake Forest") == "Wake Forest University"
    assert normalize_team_name("High Point") == "High Point University"
    assert normalize_team_name("Duke") == "Duke University"

    assert normalize_team_name("Elon") == "Elon University"
    assert normalize_team_name("Charlotte") == "UNC Charlotte"
    assert normalize_team_name("Georgetown") == "Georgetown University"
    assert normalize_team_name("St Joseph's") == "Saint Joseph's University"
    assert normalize_team_name("St. Joseph's") == "Saint Joseph's University"
    assert normalize_team_name("James Madison") == "James Madison University"
    assert normalize_team_name("James Madison M2") == "James Madison University (M2)"
    assert normalize_team_name("GA Tech") == "Georgia Tech"
    assert normalize_team_name("Georgia Tech") == "Georgia Tech"
    assert normalize_team_name("Clemson") == "Clemson University"
    assert normalize_team_name("Saint Thomas") == "St. Thomas University"
    assert normalize_team_name("St Thomas") == "St. Thomas University"
    assert normalize_team_name("Richmond") == "University of Richmond"
    assert normalize_team_name("Rowan") == "Rowan University"
    assert normalize_team_name("Virginia") == "University of Virginia"
    assert normalize_team_name("UVA") == "University of Virginia"

    # Prefix handling
    assert normalize_team_name("vs. NC State") == "NC State University"
    assert normalize_team_name("@ UNC") == "UNC Chapel Hill"
    assert normalize_team_name("@ Elon") == "Elon University"
    assert normalize_team_name("vs Alabama D2") == "University of Alabama (D2)"

    # Unknown team returns cleaned string
    assert normalize_team_name("Liberty University") == "Liberty University"
    assert normalize_team_name("  Clemson   Tigers  ") == "Clemson Tigers"

    # Empty string
    assert normalize_team_name("") == ""
    assert normalize_team_name("   ") == ""


def test_parse_game_datetime_standard_formats() -> None:
    """Verify datetime parsing across ISO, US, and textual formats."""
    expected_tz = ZoneInfo(DEFAULT_TIMEZONE)
    expected_dt = datetime(2026, 9, 4, 19, 0, tzinfo=expected_tz).astimezone(UTC)

    # ISO format YYYY-MM-DD
    assert parse_game_datetime("2026-09-04", "7:00 PM") == expected_dt

    # US format MM/DD/YYYY
    expected_dt2 = datetime(2026, 9, 4, 11, 30, tzinfo=expected_tz).astimezone(UTC)
    assert parse_game_datetime("09/04/2026", "11:30 AM") == expected_dt2

    # US format MM-DD-YYYY
    assert parse_game_datetime("09-04-2026", "19:00") == expected_dt

    # Textual format
    expected_dt4 = datetime(2026, 9, 4, 0, 0, tzinfo=expected_tz).astimezone(UTC)
    assert parse_game_datetime("September 4, 2026", "12:00 AM") == expected_dt4

    expected_dt5 = datetime(2026, 9, 4, 12, 0, tzinfo=expected_tz).astimezone(UTC)
    assert parse_game_datetime("Sep 4, 2026", "12:00 PM") == expected_dt5

    # Default time 19:00
    assert parse_game_datetime("September 4 2026") == expected_dt


def test_parse_game_datetime_short_collegiate_formats() -> None:
    """Verify collegiate short-date parsing with season and fallback resolution."""
    expected_tz = ZoneInfo(DEFAULT_TIMEZONE)

    # Short collegiate date with season: Fall (Oct) -> 2025
    dt_fall = parse_game_datetime("Sat Oct  4", "8:45 PM EST", season="2025-2026")
    assert dt_fall == datetime(2025, 10, 4, 20, 45, tzinfo=expected_tz).astimezone(UTC)

    # Short collegiate date with season: Spring (Jan) -> 2026
    dt_spring = parse_game_datetime("Fri Jan 23", "7:00 PM", season="2025-2026")
    assert dt_spring == datetime(2026, 1, 23, 19, 0, tzinfo=expected_tz).astimezone(UTC)

    # Short date with default_year
    dt_default_yr = parse_game_datetime("Sat Oct 4", "7:00 PM", default_year=2024)
    assert dt_default_yr == datetime(2024, 10, 4, 19, 0, tzinfo=expected_tz).astimezone(
        UTC,
    )

    # Short date without season or default_year defaults to current year
    dt_now_yr = parse_game_datetime("Sat Oct 4", "-")
    cur_year = datetime.now(UTC).year
    assert dt_now_yr == datetime(cur_year, 10, 4, 19, 0, tzinfo=expected_tz).astimezone(
        UTC,
    )

    # Invalid date raises ValueError
    with pytest.raises(ValueError, match="Unrecognized date format"):
        parse_game_datetime("invalid-date-string")

    with pytest.raises(ValueError, match="Unrecognized date format"):
        parse_game_datetime("Foo 12")


def test_parse_game_datetime_times_and_timezones() -> None:
    """Verify time string variations and fallback handling."""
    # TBD / TBA / '-' defaults to 19:00
    dt_tbd = parse_game_datetime("2026-10-10", "TBD")
    expected_tz = ZoneInfo("America/New_York")
    assert dt_tbd == datetime(2026, 10, 10, 19, 0, tzinfo=expected_tz).astimezone(UTC)

    dt_dash = parse_game_datetime("2026-10-10", "-")
    assert dt_dash == dt_tbd

    dt_empty = parse_game_datetime("2026-10-10", "")
    assert dt_empty == dt_tbd

    # Time string with timezone acronym (EST, EDT)
    dt_est = parse_game_datetime("2026-10-10", "8:45 PM EST")
    assert dt_est == datetime(2026, 10, 10, 20, 45, tzinfo=expected_tz).astimezone(UTC)

    # Unrecognized time string falls back to 19:00
    dt_weird = parse_game_datetime("2026-10-10", "Unknown Time")
    assert dt_weird == dt_tbd

    # Custom timezone
    dt_central = parse_game_datetime("2026-10-10", "7:00 PM", tz_name="America/Chicago")
    expected_central = datetime(
        2026,
        10,
        10,
        19,
        0,
        tzinfo=ZoneInfo("America/Chicago"),
    ).astimezone(UTC)
    assert dt_central == expected_central


def test_parse_game_score() -> None:
    """Verify score parsing across standard, overtime, shootout, and empty strings."""
    assert parse_game_score("5 - 3") == (5, 3, None)
    assert parse_game_score("5-3") == (5, 3, None)
    assert parse_game_score("4:2") == (4, 2, None)
    assert parse_game_score("4 - 5 (OT)") == (4, 5, "OT")
    assert parse_game_score("3 - 2 (SO)") == (3, 2, "SO")
    assert parse_game_score("6 - 5 (2OT)") == (6, 5, "2OT")
    assert parse_game_score("4 - 3 (F/OT)") == (4, 3, "F/OT")
    assert parse_game_score("0-0") == (0, 0, None)

    # Empty or unparsable
    assert parse_game_score(None) == (None, None, None)
    assert parse_game_score("") == (None, None, None)
    assert parse_game_score("Scheduled") == (None, None, None)


def test_parse_game_status() -> None:
    """Verify status parsing and fallback logic."""
    assert parse_game_status("final") == GameStatus.FINAL
    assert parse_game_status("finished") == GameStatus.FINAL
    assert parse_game_status("completed") == GameStatus.FINAL
    assert parse_game_status("postponed") == GameStatus.POSTPONED
    assert parse_game_status("delayed") == GameStatus.POSTPONED
    assert parse_game_status("cancelled") == GameStatus.CANCELLED
    assert parse_game_status("canceled") == GameStatus.CANCELLED
    assert parse_game_status("forfeit") == GameStatus.CANCELLED
    assert parse_game_status("in progress") == GameStatus.IN_PROGRESS
    assert parse_game_status("live") == GameStatus.IN_PROGRESS

    # Status missing or unrecognized with score
    assert parse_game_status(None, has_score=True) == GameStatus.FINAL
    assert parse_game_status("", has_score=True) == GameStatus.FINAL
    assert parse_game_status("upcoming", has_score=True) == GameStatus.FINAL

    # Status missing or unrecognized without score
    assert parse_game_status(None, has_score=False) == GameStatus.SCHEDULED
    assert parse_game_status("", has_score=False) == GameStatus.SCHEDULED
    assert parse_game_status("scheduled", has_score=False) == GameStatus.SCHEDULED
    assert parse_game_status("unknown", has_score=False) == GameStatus.SCHEDULED

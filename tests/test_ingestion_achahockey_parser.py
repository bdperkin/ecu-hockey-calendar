# pylint: disable=too-many-public-methods
"""Unit tests for ACHA Hockey schedule and season parser."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from ecu_hockey_calendar.ingestion.achahockey_parser import (
    CLIENT_CODE,
    DEFAULT_ACHA_PORTAL_URL,
    DEFAULT_APP_KEY,
    DEFAULT_BASE_URL,
    ECU_TEAM_ID,
    KNOWN_SEASON_IDS,
    KNOWN_SEASONS,
    _extract_game_items,
    _extract_overtime_note,
    _extract_season_items,
    _filter_dict_items,
    _is_final_game,
    _is_in_progress_game,
    _is_postponed_game,
    _is_target_season_item,
    _parse_int_score,
    _parse_iso_string,
    _parse_single_season,
    clean_team_name,
    format_achahockey_venue,
    parse_achahockey_datetime,
    parse_achahockey_game_status,
    parse_achahockey_schedule_json,
    parse_achahockey_scores,
    parse_achahockey_seasons_json,
    resolve_achahockey_season,
    resolve_achahockey_teams,
)
from ecu_hockey_calendar.storage.models import GameStatus

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "achahockey"


def _load_fixture(filename: str) -> dict[str, object]:
    """Load JSON fixture file from tests/fixtures/achahockey."""
    filepath = FIXTURES_DIR / filename
    with filepath.open(encoding="utf-8") as f:
        return cast("dict[str, object]", json.load(f))


class TestACHAHockeyParserFixtures:
    """Validate parsing of all 5 target season fixtures against issue requirements."""

    @pytest.mark.parametrize(
        ("filename", "expected_count", "expected_season"),
        [
            ("season_73.json", 6, "2026-2027"),
            ("season_60.json", 16, "2025-2026"),
            ("season_46.json", 11, "2024-2025"),
            ("season_34.json", 14, "2023-2024"),
            ("season_21.json", 11, "2022-2023"),
        ],
    )
    def test_parse_target_seasons(
        self,
        filename: str,
        expected_count: int,
        expected_season: str,
    ) -> None:
        """Verify each target season fixture parses exact required game counts."""
        data = _load_fixture(filename)
        records = parse_achahockey_schedule_json(data)
        assert len(records) == expected_count

        for rec in records:
            assert rec.game_id.startswith("ecu-")
            assert rec.opponent_name
            assert rec.venue
            assert rec.metadata is not None
            assert rec.metadata.get("season") == expected_season
            assert rec.metadata.get("source") == "achahockey"
            assert rec.start_time.tzinfo is not None

    def test_season_73_specific_game(self) -> None:
        """Verify game specifics from 2026-2027 season (Season 73)."""
        data = _load_fixture("season_73.json")
        records = parse_achahockey_schedule_json(data)
        g0 = records[0]

        assert g0.league_game_id == "34694"
        assert g0.opponent_name == "UNC Charlotte"
        assert not g0.is_home
        assert g0.venue == "Extreme Ice Center, Charlotte, NC"
        assert g0.status == GameStatus.SCHEDULED
        assert g0.home_score is None
        assert g0.away_score is None
        assert g0.start_time == datetime(2026, 9, 20, 1, 30, tzinfo=UTC)

    def test_season_60_completed_game(self) -> None:
        """Verify final game specifics from 2025-2026 season (Season 60)."""
        data = _load_fixture("season_60.json")
        records = parse_achahockey_schedule_json(data)
        g0 = records[0]

        assert g0.league_game_id == "28482"
        assert g0.opponent_name == "University of Alabama"
        assert not g0.is_home
        assert g0.status == GameStatus.FINAL
        assert g0.home_score == 6
        assert g0.away_score == 3
        assert g0.calculate_result().value == "L"

    def test_season_34_postponed_game(self) -> None:
        """Verify postponed game in 2023-2024 season (Season 34)."""
        data = _load_fixture("season_34.json")
        records = parse_achahockey_schedule_json(data)
        postponed_games = [r for r in records if r.status == GameStatus.POSTPONED]
        assert len(postponed_games) == 1
        assert postponed_games[0].league_game_id == "13085"

    def test_seasons_discovery_fixture(self) -> None:
        """Verify seasons discovery endpoint extracts all target seasons."""
        data = _load_fixture("seasons.json")
        seasons = parse_achahockey_seasons_json(data)

        assert seasons["2026-2027"] == "73"
        assert seasons["2025-2026"] == "60"
        assert seasons["2024-2025"] == "46"
        assert seasons["2023-2024"] == "34"
        assert seasons["2022-2023"] == "21"
        assert seasons["2021-2022"] == "10"


class TestACHAHockeyParserHelpers:
    """Test individual parsing helper routines and edge cases."""

    def test_clean_team_name(self) -> None:
        """Test removal of division prefixes and normalization."""
        assert (
            clean_team_name("MD2 East Carolina University")
            == "East Carolina University"
        )
        assert clean_team_name("MD2 Georgia Tech ") == "Georgia Tech"
        assert clean_team_name("MD3 Clemson University") == "Clemson University"
        assert (
            clean_team_name("MD1 University of North Carolina")
            == "University of North Carolina"
        )
        assert (
            clean_team_name("M2 East Carolina University") == "East Carolina University"
        )
        assert clean_team_name("W1 Liberty University") == "Liberty University"
        assert clean_team_name("Duke University") == "Duke University"

    def test_parse_game_status_final_variations(self) -> None:
        """Test final game statuses and overtime/shootout notes."""
        st, ot = parse_achahockey_game_status(
            {"final": "1", "game_status": "Final"},
        )
        assert st == GameStatus.FINAL
        assert ot is None

        st, ot = parse_achahockey_game_status(
            {"status": "4", "game_status": "Final OT", "overtime": "1"},
        )
        assert st == GameStatus.FINAL
        assert ot == "OT"

        st, ot = parse_achahockey_game_status(
            {"status": "4", "game_status": "Final SO", "shootout": "1"},
        )
        assert st == GameStatus.FINAL
        assert ot == "SO"

    def test_parse_game_status_non_final(self) -> None:
        """Test non-final statuses: postponed, cancelled, in progress, scheduled."""
        st, _ = parse_achahockey_game_status(
            {"status": "8", "game_status": "Postponed"},
        )
        assert st == GameStatus.POSTPONED

        st, _ = parse_achahockey_game_status({"game_status": "Game Cancelled"})
        assert st == GameStatus.CANCELLED

        st, _ = parse_achahockey_game_status(
            {"started": "1", "game_status": "2nd Period"},
        )
        assert st == GameStatus.IN_PROGRESS

        st, _ = parse_achahockey_game_status(
            {"status": "1", "game_status": "7:00 pm EDT"},
        )
        assert st == GameStatus.SCHEDULED

    def test_extract_overtime_note_none(self) -> None:
        """Test overtime note when neither shootout nor overtime applies."""
        assert _extract_overtime_note({"game_status": "Final"}) is None

    def test_is_in_progress_variations(self) -> None:
        """Test in-progress status flag combinations."""
        assert _is_in_progress_game({}, "2", "period 1")
        assert _is_in_progress_game({}, "3", "period 2")
        assert _is_in_progress_game({}, "0", "game in progress")
        assert not _is_in_progress_game({}, "1", "scheduled")

    def test_is_postponed_variations(self) -> None:
        """Test postponed status flag combinations."""
        assert _is_postponed_game("8", "")
        assert _is_postponed_game("1", "postponed to tomorrow")
        assert not _is_postponed_game("1", "scheduled")

    def test_is_final_variations(self) -> None:
        """Test final status flag combinations."""
        assert _is_final_game({"final": "1"}, "0", "")
        assert _is_final_game({}, "4", "")
        assert _is_final_game({}, "0", "final / ot")
        assert not _is_final_game({}, "1", "scheduled")

    def test_parse_achahockey_datetime_iso(self) -> None:
        """Test datetime parsing with valid ISO strings."""
        game = {"GameDateISO8601": "2026-09-19T21:30:00-04:00"}
        dt = parse_achahockey_datetime(game)
        assert dt == datetime(2026, 9, 20, 1, 30, tzinfo=UTC)

    def test_parse_achahockey_datetime_dt_played(self) -> None:
        """Test datetime parsing fallback with date_time_played."""
        game = {"date_time_played": "2026-09-19T21:30:00Z"}
        dt = parse_achahockey_datetime(game)
        assert dt == datetime(2026, 9, 19, 21, 30, tzinfo=UTC)

    def test_parse_achahockey_datetime_fallback(self) -> None:
        """Test fallback datetime parsing with separate date and time."""
        game = {
            "date_played": "2026-09-19",
            "scheduled_time": "9:30 pm EDT",
            "timezone": "America/New_York",
        }
        dt = parse_achahockey_datetime(game)
        assert dt.year == 2026
        assert dt.month == 9
        assert dt.day == 20
        assert dt.tzinfo is not None

    def test_parse_iso_string_edge_cases(self) -> None:
        """Test ISO string parser with empty, invalid, and naive values."""
        assert _parse_iso_string(None) is None
        assert _parse_iso_string("") is None
        assert _parse_iso_string("invalid-iso") is None
        naive = _parse_iso_string("2026-09-19T21:30:00")
        assert naive is not None
        assert naive.tzinfo == UTC

    def test_format_achahockey_venue(self) -> None:
        """Test venue formatting with different field combinations."""
        assert (
            format_achahockey_venue(
                {"venue_name": "Extreme Ice Center", "venue_location": "Charlotte, NC"},
            )
            == "Extreme Ice Center, Charlotte, NC"
        )
        assert (
            format_achahockey_venue(
                {
                    "venue_name": "Carolina Ice Zone (Greenville, NC)",
                    "venue_location": "Greenville, NC",
                },
            )
            == "Carolina Ice Zone (Greenville, NC)"
        )
        assert (
            format_achahockey_venue({"venue_name": "Extreme Ice Center"})
            == "Extreme Ice Center"
        )
        assert (
            format_achahockey_venue({"venue_location": "Charlotte, NC"})
            == "Charlotte, NC"
        )
        assert format_achahockey_venue({}) == "TBD"

    def test_parse_achahockey_scores(self) -> None:
        """Test score parsing for final vs scheduled games."""
        game = {"home_goal_count": "5", "visiting_goal_count": "2"}
        assert parse_achahockey_scores(game, GameStatus.FINAL) == (5, 2)
        assert parse_achahockey_scores(game, GameStatus.IN_PROGRESS) == (5, 2)
        assert parse_achahockey_scores(game, GameStatus.SCHEDULED) == (None, None)
        assert parse_achahockey_scores(
            {"home_goal_count": "bad", "visiting_goal_count": None},
            GameStatus.FINAL,
        ) == (None, None)

    def test_parse_int_score(self) -> None:
        """Test integer score converter with invalid values."""
        assert _parse_int_score(None) is None
        assert _parse_int_score("10") == 10
        assert _parse_int_score("abc") is None

    def test_resolve_achahockey_teams(self) -> None:
        """Test home/away orientation resolution."""
        home_game = {
            "home_team": "589",
            "home_team_name": "MD2 East Carolina University",
            "visiting_team_name": "MD2 University of Alabama",
        }
        is_home, opp = resolve_achahockey_teams(home_game, target_team_id="589")
        assert is_home
        assert opp == "University of Alabama"

        away_game = {
            "home_team": "738",
            "home_team_name": "MD2 UNC Charlotte",
            "visiting_team_name": "MD2 East Carolina University",
        }
        is_home, opp = resolve_achahockey_teams(away_game, target_team_id="589")
        assert not is_home
        assert opp == "UNC Charlotte"

    def test_resolve_achahockey_season(self) -> None:
        """Test season label resolution from map, known IDs, and start date."""
        dt_fall = datetime(2026, 9, 15, tzinfo=UTC)
        dt_spring = datetime(2027, 2, 10, tzinfo=UTC)

        assert (
            resolve_achahockey_season("custom", dt_fall, {"custom": "2029-2030"})
            == "2029-2030"
        )
        assert resolve_achahockey_season("73", dt_fall) == "2026-2027"
        assert resolve_achahockey_season("999", dt_fall) == "2026-2027"
        assert resolve_achahockey_season("999", dt_spring) == "2026-2027"

    def test_parse_achahockey_schedule_json_payload_types(self) -> None:
        """Test parse_achahockey_schedule_json with string, dict, and list payloads."""
        raw_list = [
            {
                "game_id": "999",
                "home_team": "589",
                "visiting_team_name": "MD2 Duke University",
                "GameDateISO8601": "2026-10-01T19:00:00-04:00",
                "venue_name": "Carolina Ice Zone",
            },
        ]
        recs_list = parse_achahockey_schedule_json(raw_list)
        assert len(recs_list) == 1
        assert recs_list[0].league_game_id == "999"

        json_str = json.dumps(raw_list)
        recs_str = parse_achahockey_schedule_json(json_str)
        assert len(recs_str) == 1

        recs_direct_sched = parse_achahockey_schedule_json({"Schedule": raw_list})
        assert len(recs_direct_sched) == 1

        recs_invalid = parse_achahockey_schedule_json("not-json")
        assert not recs_invalid

        recs_empty = parse_achahockey_schedule_json({})
        assert not recs_empty

    def test_parse_achahockey_schedule_json_skips_invalid_items(self) -> None:
        """Test skipping items without game_id or non-dict items."""
        raw = [
            "invalid-item",
            {"some_key": "no_game_id"},
            {
                "id": "123",
                "home_team": "589",
                "visiting_team_name": "Opponent",
                "GameDateISO8601": "2026-10-01T19:00:00-04:00",
            },
        ]
        recs = parse_achahockey_schedule_json(raw)
        assert len(recs) == 1
        assert recs[0].league_game_id == "123"

    def test_parse_achahockey_seasons_json_variations(self) -> None:
        """Test seasons JSON parsing with dict, direct list, and raw string."""
        sample_seasons = {
            "Seasons": [
                {
                    "season_id": "80",
                    "season_name": "2027-2028 Men's Divisions",
                    "playoff": "0",
                },
                {
                    "season_id": "81",
                    "season_name": "2027-28 Men's Regular Season",
                    "playoff": "0",
                },
                {
                    "season_id": "82",
                    "season_name": "2027-2028 Women's Divisions",
                    "playoff": "0",
                },
                {
                    "season_id": "83",
                    "season_name": "2027 Men's Division 2 Nationals",
                    "playoff": "1",
                },
            ],
        }
        res = parse_achahockey_seasons_json(sample_seasons)
        assert res["2027-2028"] == "81"  # updated or parsed

        res_list = parse_achahockey_seasons_json(sample_seasons["Seasons"])
        assert "2027-2028" in res_list

        res_str = parse_achahockey_seasons_json(json.dumps(sample_seasons))
        assert "2027-2028" in res_str

        res_empty = parse_achahockey_seasons_json("not-json")
        assert not res_empty

    def test_is_target_season_item(self) -> None:
        """Test target season filter criteria."""
        assert _is_target_season_item(
            {"playoff": "0", "season_name": "2026-2027 Men's Divisions"},
        )
        assert not _is_target_season_item(
            {"playoff": "1", "season_name": "2026-2027 Men's Divisions"},
        )
        assert not _is_target_season_item(
            {"playoff": "0", "season_name": "2026-2027 Women's Divisions"},
        )
        assert not _is_target_season_item(
            {"playoff": "0", "season_name": "2026 All Star Game"},
        )

    def test_filter_dict_items_non_list(self) -> None:
        """Test _filter_dict_items returns empty list for non-list input."""
        assert _filter_dict_items("not-a-list") == []

    def test_extract_game_items_non_dict(self) -> None:
        """Test _extract_game_items handles non-dict payloads."""
        assert _extract_game_items(12345) == []

    def test_extract_season_items_non_dict(self) -> None:
        """Test _extract_season_items handles non-dict payloads."""
        assert _extract_season_items(12345) == []

    def test_parse_single_season_invalid(self) -> None:
        """Test _parse_single_season returns None for unmatched season names."""
        assert _parse_single_season({"playoff": "1"}) is None
        assert (
            _parse_single_season(
                {"playoff": "0", "season_name": "Men's Divisions No Year"},
            )
            is None
        )

    def test_constants(self) -> None:
        """Test exported constants."""
        assert CLIENT_CODE == "acha"
        assert DEFAULT_APP_KEY == "e6867b36742a0c9d"  # pragma: allowlist secret
        assert ECU_TEAM_ID == "589"
        assert DEFAULT_BASE_URL == "https://lscluster.hockeytech.com/feed/index.php"
        assert DEFAULT_ACHA_PORTAL_URL == "https://www.achahockey.org"
        assert len(KNOWN_SEASONS) == 5
        assert len(KNOWN_SEASON_IDS) == 5

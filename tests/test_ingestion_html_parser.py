"""Tests for HTML schedule parser using BeautifulSoup4."""

from __future__ import annotations

from datetime import UTC, datetime

from ecu_hockey_calendar.ingestion.html_parser import (
    DEFAULT_ECU_TEAM,
    ParsedGameRecord,
    _clean_text,
    parse_schedule_html,
)
from ecu_hockey_calendar.models import GameResult, Team
from ecu_hockey_calendar.storage.models import GameStatus

SAMPLE_TABLE_HTML = """
<html>
<body>
    <table class="schedule-table">
        <thead>
            <tr><th>Date</th><th>Opponent</th><th>Time</th><th>Location</th><th>Result</th></tr>
        </thead>
        <tbody>
            <tr>
                <td>09/04/2026</td>
                <td>vs. NC State</td>
                <td>7:00 PM</td>
                <td>Carolina Ice Zone</td>
                <td>5 - 3</td>
            </tr>
            <tr>
                <td>09/11/2026</td>
                <td>@ UNC Wilmington</td>
                <td>8:30 PM</td>
                <td>Wilmington Ice House</td>
                <td>2 - 3 (OT)</td>
            </tr>
            <tr>
                <td>09/18/2026</td>
                <td>vs Alabama D2</td>
                <td>7:00 PM</td>
                <td>Carolina Ice Zone</td>
                <td>0 - 0</td>
            </tr>
            <tr>
                <td>10/02/2026</td>
                <td>at Virginia Tech</td>
                <td>TBD</td>
                <td>Lancerlot Sports Complex</td>
                <td>Scheduled</td>
            </tr>
            <!-- Malformed rows to test parser resilience -->
            <tr><td>Invalid Row</td><td>vs Duke</td></tr>
            <tr><td>10/10/2026</td><td></td><td>7:00 PM</td><td>Arena</td></tr>
            <tr><td>unparsable</td><td>vs Duke</td><td>7:00 PM</td><td>Arena</td></tr>
        </tbody>
    </table>
</body>
</html>
"""

SAMPLE_CARDS_HTML = """
<html>
<body>
    <div class="schedule-container">
        <div class="game-card">
            <div class="schedule-date">September 25, 2026</div>
            <div class="team-vs">vs Appalachian State</div>
            <div class="venue-name">Carolina Ice Zone</div>
            <div class="game-score">4 - 2</div>
        </div>
        <div class="game-card">
            <div class="schedule-date">October 16, 2026</div>
            <div class="team-vs">@ Wake Forest</div>
            <div class="venue-name">Winston-Salem Fairgrounds</div>
            <div class="game-score">Upcoming</div>
        </div>
        <div class="game-card">
            <div class="schedule-date">NotADate</div>
            <div class="team-vs">vs Unknown</div>
        </div>
        <div class="game-card">
            <div class="schedule-date">October 20, 2026</div>
            <div class="team-vs">vs </div>
        </div>
        <div class="game-card">
            <div class="schedule-date">October 20, 2026</div>
        </div>
    </div>
</body>
</html>
"""


def test_parse_schedule_html_table() -> None:
    """Verify table parsing extracts structured game records with scores."""
    records = parse_schedule_html(SAMPLE_TABLE_HTML)
    assert len(records) == 4

    # Game 1: Home vs NC State (Win)
    g1 = records[0]
    assert g1.opponent_name == "NC State University"
    assert g1.is_home is True
    assert g1.home_score == 5
    assert g1.away_score == 3
    assert g1.status == GameStatus.FINAL
    assert g1.calculate_result() == GameResult.WIN

    # Game 2: Away @ UNC Wilmington (Overtime loss)
    g2 = records[1]
    assert g2.opponent_name == "UNC Wilmington"
    assert g2.is_home is False
    assert g2.home_score == 3  # UNCW home score
    assert g2.away_score == 2  # ECU away score
    assert g2.overtime_note == "OT"
    assert g2.status == GameStatus.FINAL
    assert g2.calculate_result() == GameResult.OVERTIME_LOSS

    # Game 3: Home vs Alabama D2 (Tie)
    g3 = records[2]
    assert g3.opponent_name == "University of Alabama (D2)"
    assert g3.is_home is True
    assert g3.home_score == 0
    assert g3.away_score == 0
    assert g3.calculate_result() == GameResult.TIE

    # Game 4: Away at Virginia Tech (Scheduled)
    g4 = records[3]
    assert g4.opponent_name == "Virginia Tech"
    assert g4.is_home is False
    assert g4.home_score is None
    assert g4.away_score is None
    assert g4.status == GameStatus.SCHEDULED
    assert g4.calculate_result() == GameResult.SCHEDULED


def test_parse_schedule_html_cards() -> None:
    """Verify card-based HTML layout extracts game items."""
    records = parse_schedule_html(SAMPLE_CARDS_HTML)
    assert len(records) == 2

    c1 = records[0]
    assert c1.opponent_name == "Appalachian State University"
    assert c1.is_home is True
    assert c1.home_score == 4
    assert c1.away_score == 2
    assert c1.venue == "Carolina Ice Zone"

    c2 = records[1]
    assert c2.opponent_name == "Wake Forest University"
    assert c2.is_home is False
    assert c2.venue == "Winston-Salem Fairgrounds"
    assert c2.status == GameStatus.SCHEDULED


def test_parse_schedule_html_empty() -> None:
    """Verify empty or non-schedule HTML returns empty list."""
    assert not parse_schedule_html("")
    assert not parse_schedule_html("<html><body><p>No games</p></body></html>")
    assert _clean_text(None) == ""


def test_parsed_record_to_domain_game() -> None:
    """Verify conversion of ParsedGameRecord to domain Game dataclass."""
    rec = ParsedGameRecord(
        game_id="ecu-home-nc-state-20260904",
        opponent_name="NC State University",
        is_home=True,
        start_time=datetime(2026, 9, 4, 23, 0, tzinfo=UTC),
        venue="Carolina Ice Zone",
        status=GameStatus.FINAL,
        home_score=5,
        away_score=2,
    )
    game = rec.to_domain_game()
    assert game.game_id == "ecu-home-nc-state-20260904"
    assert game.home_team == DEFAULT_ECU_TEAM
    assert game.away_team.name == "NC State University"
    assert game.result == GameResult.WIN

    # Away game scenario
    rec_away = ParsedGameRecord(
        game_id="ecu-away-uncw-20260911",
        opponent_name="UNC Wilmington",
        is_home=False,
        start_time=datetime(2026, 9, 12, 0, 30, tzinfo=UTC),
        venue="Wilmington Ice House",
        status=GameStatus.FINAL,
        home_score=4,
        away_score=1,
    )
    opp = Team(name="UNC Wilmington", city="Wilmington", state="NC")
    game_away = rec_away.to_domain_game(opponent_team=opp)
    assert game_away.home_team == opp
    assert game_away.away_team == DEFAULT_ECU_TEAM
    assert game_away.result == GameResult.LOSS


def test_parsed_record_result_calculations() -> None:
    """Verify result calculation for all combinations of win, loss, OTL, tie."""
    # Away win
    r_away_win = ParsedGameRecord(
        game_id="g1",
        opponent_name="Opp",
        is_home=False,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        venue="Arena",
        home_score=2,
        away_score=4,  # ECU away score
    )
    assert r_away_win.calculate_result() == GameResult.WIN

    # Away OTL with SO
    r_away_so = ParsedGameRecord(
        game_id="g2",
        opponent_name="Opp",
        is_home=False,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        venue="Arena",
        home_score=3,
        away_score=2,
        overtime_note="SO",
    )
    assert r_away_so.calculate_result() == GameResult.OVERTIME_LOSS

    # Away Tie
    r_away_tie = ParsedGameRecord(
        game_id="g3",
        opponent_name="Opp",
        is_home=False,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        venue="Arena",
        home_score=2,
        away_score=2,
    )
    assert r_away_tie.calculate_result() == GameResult.TIE

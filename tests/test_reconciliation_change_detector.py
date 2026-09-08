"""Tests for reconciliation change detection and sync state tracking engine."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from ecu_hockey_calendar.models import GameResult
from ecu_hockey_calendar.reconciliation.change_detector import (
    CANONICAL_CHANGE_CYCLE_PREFIX,
    ChangeDetector,
    _build_human_summary,
    _describe_end_time_change,
)
from ecu_hockey_calendar.reconciliation.models import (
    ConflictField,
    ConflictSeverity,
    DetectedConflict,
    DiscrepancyRecord,
    GameStateTransition,
    ReconciledGame,
)
from ecu_hockey_calendar.storage.models import GameModel, GameStatus


# pylint: disable=too-many-arguments,too-many-positional-arguments
def _create_reconciled_game(  # noqa: PLR0913
    canonical_id: str,
    opponent: str = "NC State Icepack",
    start_dt: datetime | None = None,
    venue: str = "Polar Ice House",
    *,
    is_home: bool = True,
    end_dt: datetime | None = None,
    status: GameStatus = GameStatus.SCHEDULED,
    result: GameResult | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
    conflicts: list[DetectedConflict] | None = None,
) -> ReconciledGame:
    """Helper to build test ReconciledGame entities."""
    return ReconciledGame(
        canonical_game_id=canonical_id,
        opponent_name=opponent,
        start_time=start_dt or datetime(2026, 10, 10, 23, 0, tzinfo=UTC),
        venue=venue,
        is_home=is_home,
        end_time=end_dt,
        status=status,
        result=result,
        home_score=home_score,
        away_score=away_score,
        conflicts=conflicts or [],
    )


def test_change_detector_created_game() -> None:
    """Verify newly introduced game is marked as CREATED."""
    detector = ChangeDetector()
    new_game = _create_reconciled_game("game-1", "Duke Blue Devils")

    result = detector.detect_changes(previous_games=[], current_games=[new_game])
    assert len(result.created_games) == 1
    assert result.total_changes == 1
    assert result.created_games[0].state_transition == GameStateTransition.CREATED
    assert result.created_games[0].previous_snapshot is None
    assert result.created_games[0].current_snapshot is not None
    assert (
        "New game scheduled vs Duke Blue Devils"
        in result.created_games[0].human_summary
    )


def test_change_detector_deleted_game() -> None:
    """Verify removed game is marked as DELETED."""
    detector = ChangeDetector()
    old_game = _create_reconciled_game("game-1", "Duke Blue Devils")

    result = detector.detect_changes(previous_games=[old_game], current_games=[])
    assert len(result.deleted_games) == 1
    assert result.total_changes == 1
    assert result.deleted_games[0].state_transition == GameStateTransition.DELETED
    assert result.deleted_games[0].previous_snapshot is not None
    assert result.deleted_games[0].current_snapshot is None
    assert (
        "Game vs Duke Blue Devils on 2026-10-10 removed"
        in result.deleted_games[0].human_summary
    )


def test_change_detector_unchanged_game() -> None:
    """Verify identical games yield UNCHANGED transition and are counted properly."""
    detector = ChangeDetector()
    old_game = _create_reconciled_game("game-1", "NC State Icepack")
    curr_game = _create_reconciled_game("game-1", "NC State Icepack")

    result = detector.detect_changes(
        previous_games=[old_game],
        current_games=[curr_game],
    )
    assert len(result.unchanged_games) == 1
    assert result.total_changes == 0
    assert result.unchanged_games[0].state_transition == GameStateTransition.UNCHANGED
    assert "No changes detected" in result.unchanged_games[0].human_summary


def test_change_detector_conflict_detected() -> None:
    """Verify game with reconciliation conflicts yields CONFLICT_DETECTED."""
    detector = ChangeDetector()
    conflict = DetectedConflict(
        conflict_id="conf-1",
        game_key="game-1",
        field=ConflictField.START_TIME,
        discrepancies=[
            DiscrepancyRecord(
                field=ConflictField.START_TIME,
                source_a="primary_sot",
                source_b="league",
                value_a="19:00",
                value_b="20:00",
                severity=ConflictSeverity.HIGH,
            ),
        ],
    )
    old_game = _create_reconciled_game("game-1")
    curr_game = _create_reconciled_game("game-1", conflicts=[conflict])

    result = detector.detect_changes(
        previous_games=[old_game],
        current_games=[curr_game],
    )
    assert len(result.conflict_games) == 1
    assert result.total_changes == 1
    assert (
        result.conflict_games[0].state_transition
        == GameStateTransition.CONFLICT_DETECTED
    )
    assert (
        "Conflict detected for game vs NC State Icepack"
        in result.conflict_games[0].human_summary
    )
    assert "start_time" in result.conflict_games[0].human_summary


def test_change_detector_start_time_same_day() -> None:
    """Verify start time shift on the same day generates appropriate diff."""
    detector = ChangeDetector()
    t_old = datetime(2026, 10, 10, 23, 0, tzinfo=UTC)  # 7:00 PM EDT
    t_new = datetime(2026, 10, 11, 0, 30, tzinfo=UTC)  # 8:30 PM EDT (same EDT date)

    old_game = _create_reconciled_game("game-1", start_dt=t_old)
    curr_game = _create_reconciled_game("game-1", start_dt=t_new)

    result = detector.detect_changes(
        previous_games=[old_game],
        current_games=[curr_game],
    )
    assert len(result.updated_games) == 1
    diffs = result.updated_games[0].field_diffs
    assert len(diffs) == 1
    assert diffs[0].field_name == "start_time"
    assert (
        "Start time moved from 7:00 PM to 8:30 PM EDT (2026-10-10)"
        in diffs[0].human_description
    )


def test_change_detector_start_time_rescheduled_date() -> None:
    """Verify start time shift to a different date generates reschedule diff."""
    detector = ChangeDetector()
    t_old = datetime(2026, 10, 10, 23, 0, tzinfo=UTC)
    t_new = datetime(2026, 10, 18, 18, 0, tzinfo=UTC)

    old_game = _create_reconciled_game("game-1", start_dt=t_old)
    curr_game = _create_reconciled_game("game-1", start_dt=t_new)

    result = detector.detect_changes(
        previous_games=[old_game],
        current_games=[curr_game],
    )
    assert len(result.updated_games) == 1
    diff = result.updated_games[0].field_diffs[0]
    assert "Game rescheduled from" in diff.human_description


def test_change_detector_end_time_changes() -> None:
    """Verify end time modifications generate diffs."""
    detector = ChangeDetector()
    t_start = datetime(2026, 10, 10, 23, 0, tzinfo=UTC)
    t_end1 = datetime(2026, 10, 11, 1, 30, tzinfo=UTC)
    t_end2 = datetime(2026, 10, 11, 2, 0, tzinfo=UTC)

    old_game = _create_reconciled_game("game-1", start_dt=t_start, end_dt=t_end1)
    curr_game = _create_reconciled_game("game-1", start_dt=t_start, end_dt=t_end2)

    result = detector.detect_changes(
        previous_games=[old_game],
        current_games=[curr_game],
    )
    assert len(result.updated_games) == 1
    diff = result.updated_games[0].field_diffs[0]
    assert diff.field_name == "end_time"
    assert "End time changed from" in diff.human_description

    # Test helper with None values
    desc = _describe_end_time_change(None, t_end1, "America/New_York")
    assert "End time changed from None to" in desc


def test_change_detector_venue_status_opponent_location() -> None:
    """Verify venue, status, opponent name, and home/away changes."""
    detector = ChangeDetector()
    old_game = _create_reconciled_game(
        "game-1",
        opponent="UNC",
        venue="The Rink",
        status=GameStatus.SCHEDULED,
        is_home=True,
    )
    curr_game = _create_reconciled_game(
        "game-1",
        opponent="North Carolina Tar Heels",
        venue="Polar Ice House",
        status=GameStatus.POSTPONED,
        is_home=False,
    )

    result = detector.detect_changes(
        previous_games=[old_game],
        current_games=[curr_game],
    )
    assert len(result.updated_games) == 1
    diff_names = {d.field_name for d in result.updated_games[0].field_diffs}
    assert diff_names == {"venue", "status", "opponent_name", "is_home"}


def test_change_detector_outcome_and_scores() -> None:
    """Verify result and scores updates."""
    detector = ChangeDetector()
    old_game = _create_reconciled_game(
        "game-1",
        result=None,
        home_score=None,
        away_score=None,
    )
    curr_game = _create_reconciled_game(
        "game-1",
        result=GameResult.WIN,
        home_score=4,
        away_score=2,
    )

    result = detector.detect_changes(
        previous_games=[old_game],
        current_games=[curr_game],
    )
    assert len(result.updated_games) == 1
    diff_names = {d.field_name for d in result.updated_games[0].field_diffs}
    assert diff_names == {"result", "home_score", "away_score"}


def test_change_detector_fuzzy_matching_rescheduled_game() -> None:
    """Verify an unmatched game pairs with an existing game by opponent similarity."""
    detector = ChangeDetector()
    t1 = datetime(2026, 10, 10, 23, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 11, 23, 0, tzinfo=UTC)

    # In previous sync, id was based on t1: game-20261010-unc
    old_game1 = _create_reconciled_game(
        "game-20261010-unc",
        opponent="UNC Tar Heels",
        start_dt=t1,
    )
    old_game2 = _create_reconciled_game(
        "game-20261010-unc-club",
        opponent="UNC Tar Heels Club",
        start_dt=t1,
    )
    # In current sync, id changed because of date shift: game-20261011-unc
    curr_game = _create_reconciled_game(
        "game-20261011-unc",
        opponent="UNC Tar Heels",
        start_dt=t2,
    )

    result = detector.detect_changes(
        previous_games=[old_game1, old_game2],
        current_games=[curr_game],
    )
    assert len(result.updated_games) == 1
    assert len(result.created_games) == 0
    assert len(result.deleted_games) == 1
    assert result.updated_games[0].canonical_game_id == "game-20261011-unc"


def test_change_detector_with_game_model_previous() -> None:
    """Verify ChangeDetector seamlessly normalizes SQLAlchemy GameModel entities."""
    detector = ChangeDetector()

    home_team = MagicMock()
    home_team.name = "East Carolina University"
    away_team = MagicMock()
    away_team.name = "Wake Forest Demon Deacons"

    gm = MagicMock(spec=GameModel)
    gm.game_id = "game-wf"
    gm.home_team = home_team
    gm.away_team = away_team
    gm.start_time = datetime(2026, 11, 15, 19, 0, tzinfo=UTC)
    gm.end_time = None
    gm.venue = "The Ice Rink"
    gm.status = "SCHEDULED"
    gm.result = None
    gm.home_score = None
    gm.away_score = None

    curr_game = _create_reconciled_game(
        "game-wf",
        opponent="Wake Forest Demon Deacons",
        start_dt=datetime(2026, 11, 15, 19, 0, tzinfo=UTC),
        venue="New Wake Arena",
    )

    result = detector.detect_changes(previous_games=[gm], current_games=[curr_game])
    assert len(result.updated_games) == 1
    assert result.updated_games[0].field_diffs[0].field_name == "venue"
    assert result.updated_games[0].field_diffs[0].new_value == "New Wake Arena"


def test_change_detector_cycle_id_and_summary_helpers() -> None:
    """Verify custom cycle ID and summary formatting edge cases."""
    detector = ChangeDetector()
    game = _create_reconciled_game("game-1")

    res_auto_cid = detector.detect_changes(previous_games=[], current_games=[game])
    assert res_auto_cid.cycle_id.startswith(CANONICAL_CHANGE_CYCLE_PREFIX)

    res_custom_cid = detector.detect_changes(
        previous_games=[],
        current_games=[game],
        cycle_id="custom-cid-100",
    )
    assert res_custom_cid.cycle_id == "custom-cid-100"

    # Test _build_human_summary for updated without diffs
    empty_diff_summary = _build_human_summary(
        GameStateTransition.UPDATED,
        game,
        [],
        "America/New_York",
    )
    assert "updated" in empty_diff_summary

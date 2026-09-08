"""Tests for schedule reconciliation domain models and priority configurations."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.reconciliation.models import (
    ChangeDetectionCycleResult,
    ConflictField,
    ConflictSeverity,
    DetectedConflict,
    DiscrepancyRecord,
    FieldDiff,
    GameChangeRecord,
    GameStateTransition,
    ReconciledGame,
    ReconciliationCycleResult,
    ReconciliationStatus,
    SourceGameRecord,
    SourcePriority,
    TimingRelationship,
    _compare_numeric_precedence,
    _extract_team_home_and_opponent,
    _lookup_tiebreaker_order,
    _normalize_source_key,
    _parse_game_result,
    _parse_game_status,
)
from ecu_hockey_calendar.storage.models import DataSourceType, GameStatus


def test_conflict_enums() -> None:
    """Verify enum members and values for conflict representation."""
    assert ConflictSeverity.LOW == "low"
    assert ConflictSeverity.MEDIUM == "medium"
    assert ConflictSeverity.HIGH == "high"
    assert ConflictSeverity.CRITICAL == "critical"

    assert ConflictField.DATE == "date"
    assert ConflictField.START_TIME == "start_time"
    assert ConflictField.VENUE == "venue"
    assert ConflictField.STATUS == "status"
    assert ConflictField.HOME_AWAY == "home_away"
    assert ConflictField.RESULT == "result"
    assert ConflictField.HOME_SCORE == "home_score"
    assert ConflictField.AWAY_SCORE == "away_score"

    assert ReconciliationStatus.UNRESOLVED == "unresolved"
    assert ReconciliationStatus.AUTO_RESOLVED == "auto_resolved"
    assert ReconciliationStatus.FLAGGED_FOR_REVIEW == "flagged_for_review"
    assert ReconciliationStatus.MANUALLY_RESOLVED == "manually_resolved"

    assert TimingRelationship.EXACT_MATCH == "exact_match"
    assert TimingRelationship.WITHIN_TOLERANCE == "within_tolerance"
    assert TimingRelationship.TIME_TBD_MATCH == "time_tbd_match"
    assert TimingRelationship.TIME_DISCREPANCY == "time_discrepancy"
    assert TimingRelationship.DATE_ADJACENT == "date_adjacent"
    assert TimingRelationship.DATE_MISMATCH == "date_mismatch"


def test_private_model_helpers() -> None:
    """Verify internal conversion and normalization utility functions."""
    # _normalize_source_key
    assert _normalize_source_key(DataSourceType.PRIMARY_SOT) == "primary_sot"
    assert _normalize_source_key("TICKETS") == "tickets"

    # _compare_numeric_precedence
    assert _compare_numeric_precedence(1, 2) == -1
    assert _compare_numeric_precedence(3, 2) == 1
    assert _compare_numeric_precedence(2, 2) == 0

    # Verify tiebreaker lookup ordering
    order = ("a", "b", "c")
    assert _lookup_tiebreaker_order("b", order) == 1
    assert _lookup_tiebreaker_order("z", order) == 3

    # _extract_team_home_and_opponent
    is_h1, opp1 = _extract_team_home_and_opponent("East Carolina Club", "Duke")
    assert is_h1 is True
    assert opp1 == "Duke"

    is_h2, opp2 = _extract_team_home_and_opponent("ECU Ice Hockey", "UNC")
    assert is_h2 is True
    assert opp2 == "UNC"

    is_h3, opp3 = _extract_team_home_and_opponent("NC State Icepack", "ECU")
    assert is_h3 is False
    assert opp3 == "NC State Icepack"

    # _parse_game_status
    assert _parse_game_status("SCHEDULED") == GameStatus.SCHEDULED
    assert _parse_game_status("FINAL") == GameStatus.FINAL
    assert _parse_game_status("completed") == GameStatus.FINAL
    assert _parse_game_status("unknown_status_val") == GameStatus.SCHEDULED

    # _parse_game_result
    assert _parse_game_result(None) is None
    assert _parse_game_result("") is None
    assert _parse_game_result("W") == GameResult.WIN
    assert _parse_game_result("w") == GameResult.WIN
    assert _parse_game_result("invalid_res") is None


def test_source_priority_defaults_and_custom() -> None:
    """Verify default and customized tier lookups and priority comparisons."""
    sp = SourcePriority()
    assert sp.get_tier(DataSourceType.PRIMARY_SOT) == 1
    assert sp.get_tier(DataSourceType.LEAGUE) == 1
    assert sp.get_tier(DataSourceType.TICKETS) == 2
    assert sp.get_tier(DataSourceType.SOCIAL) == 2
    assert sp.get_tier(DataSourceType.OPPONENT) == 3
    assert sp.get_tier("unknown_source") == 4

    # Tier differences
    assert sp.compare_priority(DataSourceType.PRIMARY_SOT, DataSourceType.TICKETS) == -1
    assert sp.compare_priority(DataSourceType.OPPONENT, DataSourceType.LEAGUE) == 1

    # Tie breaker in same tier
    assert sp.compare_priority(DataSourceType.PRIMARY_SOT, DataSourceType.LEAGUE) == -1
    assert sp.compare_priority(DataSourceType.LEAGUE, DataSourceType.PRIMARY_SOT) == 1
    assert sp.compare_priority(DataSourceType.SOCIAL, DataSourceType.TICKETS) == 1

    # Identical sources
    assert (
        sp.compare_priority(DataSourceType.PRIMARY_SOT, DataSourceType.PRIMARY_SOT) == 0
    )


def test_source_game_record_from_game() -> None:
    """Verify SourceGameRecord construction from domain Game."""
    team_ecu = Team(
        name="East Carolina University",
        city="Greenville",
        state="NC",
        division="ACHA M2",
        conference="ACCHL",
    )
    team_unc = Team(
        name="UNC Chapel Hill",
        city="Chapel Hill",
        state="NC",
        division="ACHA M2",
        conference="ACCHL",
    )
    now = datetime(2026, 10, 10, 19, 0, tzinfo=UTC)
    end = datetime(2026, 10, 10, 21, 30, tzinfo=UTC)

    # ECU as Home
    game_home = Game(
        game_id="G1",
        home_team=team_ecu,
        away_team=team_unc,
        start_time=now,
        venue="The Factory",
        result=GameResult.WIN,
        home_score=5,
        away_score=2,
    )
    rec_home = SourceGameRecord.from_game(
        game_home,
        source_type=DataSourceType.PRIMARY_SOT,
        source_code="ecuhockey",
        end_time=end,
        is_time_tbd=False,
        confidence_score=0.95,
        raw_snapshot_id=12,
        scraped_at=now,
    )
    assert rec_home.is_home is True
    assert rec_home.opponent_name == "UNC Chapel Hill"
    assert rec_home.end_time == end
    assert rec_home.confidence_score == 0.95
    assert rec_home.raw_snapshot_id == 12

    # ECU as Away and default scraped_at
    game_away = Game(
        game_id="G2",
        home_team=team_unc,
        away_team=team_ecu,
        start_time=now,
        venue="Orange County Sportsplex",
    )
    rec_away = SourceGameRecord.from_game(game_away)
    assert rec_away.is_home is False
    assert rec_away.opponent_name == "UNC Chapel Hill"
    assert rec_away.scraped_at is not None

    d = rec_home.to_dict()
    assert d["source_type"] == "primary_sot"
    assert d["source_code"] == "ecuhockey"
    assert d["game_id"] == "G1"
    assert d["opponent_name"] == "UNC Chapel Hill"
    assert d["end_time"] == end.isoformat()
    assert d["result"] == "W"

    d_away = rec_away.to_dict()
    assert d_away["end_time"] is None
    assert d_away["result"] == "SCHEDULED"


def test_source_game_record_from_game_model() -> None:
    """Verify SourceGameRecord construction from SQLAlchemy GameModel."""
    model = MagicMock()
    model.home_team.name = "East Carolina University"
    model.away_team.name = "NC State Icepack"
    model.game_id = "GM-100"
    model.start_time = datetime(2026, 11, 5, 20, 0, tzinfo=UTC)
    model.end_time = None
    model.venue = "Invisalign Arena"
    model.status = "FINAL"
    model.result = "W"
    model.home_score = 4
    model.away_score = 3
    model.updated_at = datetime(2026, 11, 6, 1, 0, tzinfo=UTC)

    rec = SourceGameRecord.from_game_model(model)
    assert rec.is_home is True
    assert rec.opponent_name == "NC State Icepack"
    assert rec.status == GameStatus.FINAL
    assert rec.result == GameResult.WIN
    assert rec.home_score == 4

    # Away game, invalid status and invalid result
    model.home_team.name = "NC State Icepack"
    model.away_team.name = "East Carolina University"
    model.status = "unknown_status"
    model.result = "invalid_outcome"
    rec2 = SourceGameRecord.from_game_model(model)
    assert rec2.is_home is False
    assert rec2.status == GameStatus.SCHEDULED
    assert rec2.result is None


def test_discrepancy_and_conflict_records() -> None:
    """Verify DiscrepancyRecord and DetectedConflict dataclass serialization."""
    disc = DiscrepancyRecord(
        field=ConflictField.START_TIME,
        source_a="ecuhockey",
        source_b="tickets",
        value_a="19:00",
        value_b="20:00",
        severity=ConflictSeverity.MEDIUM,
        notes="Start time difference",
    )
    dd = disc.to_dict()
    assert dd["field"] == "start_time"
    assert dd["source_a"] == "ecuhockey"
    assert dd["value_a"] == "19:00"
    assert dd["severity"] == "medium"

    conf = DetectedConflict(
        conflict_id="C-1",
        game_key="2026-10-10-unc",
        field=ConflictField.START_TIME,
        discrepancies=[disc],
        severity=ConflictSeverity.MEDIUM,
        requires_review=False,
        resolved=True,
        resolved_value="19:00",
        resolved_by_source="ecuhockey",
        notes="Resolved via Tier 1",
    )
    cd = conf.to_dict()
    assert cd["conflict_id"] == "C-1"
    assert cd["field"] == "start_time"
    assert cd["resolved_value"] == "19:00"
    assert len(cd["discrepancies"]) == 1

    conf_unresolved = DetectedConflict(
        conflict_id="C-2",
        game_key="2026-10-10-unc",
        field=ConflictField.VENUE,
    )
    cd2 = conf_unresolved.to_dict()
    assert cd2["resolved_value"] is None


def test_reconciled_game_and_cycle_result() -> None:
    """Verify ReconciledGame domain conversion and cycle output serialization."""
    st = datetime(2026, 10, 20, 19, 0, tzinfo=UTC)
    et = datetime(2026, 10, 20, 21, 30, tzinfo=UTC)

    # Home game with explicit win
    rec_game = ReconciledGame(
        canonical_game_id="2026-10-20-duke",
        opponent_name="Duke Blue Devils",
        start_time=st,
        venue="The Factory",
        is_home=True,
        is_time_tbd=False,
        end_time=et,
        status=GameStatus.FINAL,
        result=GameResult.WIN,
        home_score=6,
        away_score=2,
        contributing_sources=["ecuhockey", "acchockey"],
        field_provenance={"start_time": "ecuhockey"},
        status_reconciliation=ReconciliationStatus.AUTO_RESOLVED,
        requires_admin_review=False,
        confidence_score=0.98,
    )
    domain_game = rec_game.to_domain_game()
    assert domain_game.game_id == "2026-10-20-duke"
    assert domain_game.home_team.name == "East Carolina University"
    assert domain_game.away_team.name == "Duke Blue Devils"
    assert domain_game.result == GameResult.WIN
    assert domain_game.home_score == 6

    # Away game with None result (defaults to SCHEDULED)
    rec_game_away = ReconciledGame(
        canonical_game_id="2026-10-25-duke",
        opponent_name="Duke Blue Devils",
        start_time=st,
        venue="Orange County Sportsplex",
        is_home=False,
        result=None,
    )
    domain_game_away = rec_game_away.to_domain_game()
    assert domain_game_away.home_team.name == "Duke Blue Devils"
    assert domain_game_away.away_team.name == "East Carolina University"
    assert domain_game_away.result == GameResult.SCHEDULED

    rd = rec_game.to_dict()
    assert rd["canonical_game_id"] == "2026-10-20-duke"
    assert rd["end_time"] == et.isoformat()
    assert rd["result"] == "W"

    rd_away = rec_game_away.to_dict()
    assert rd_away["end_time"] is None
    assert rd_away["result"] is None

    cycle = ReconciliationCycleResult(
        cycle_id="CYC-001",
        total_source_records=2,
        reconciled_games=[rec_game],
        total_conflicts_detected=1,
        auto_resolved_conflicts=1,
        flagged_conflicts=0,
    )
    cyd = cycle.to_dict()
    assert cyd["cycle_id"] == "CYC-001"
    assert cyd["total_source_records"] == 2
    assert len(cyd["reconciled_games"]) == 1
    assert cyd["total_conflicts_detected"] == 1


def test_reconciled_game_from_game_model() -> None:
    """Verify ReconciledGame construction from database GameModel."""
    home_team = MagicMock()
    home_team.name = "East Carolina University"
    away_team = MagicMock()
    away_team.name = "UNC Tar Heels"

    st = datetime(2026, 11, 10, 19, 0, tzinfo=UTC)
    et = datetime(2026, 11, 10, 21, 30, tzinfo=UTC)

    model = MagicMock()
    model.game_id = "game-20261110-unc-home"
    model.home_team = home_team
    model.away_team = away_team
    model.start_time = st
    model.end_time = et
    model.venue = "Polar Ice House"
    model.status = "FINAL"
    model.result = "W"
    model.home_score = 5
    model.away_score = 3

    reconciled = ReconciledGame.from_game_model(model)
    assert reconciled.canonical_game_id == "game-20261110-unc-home"
    assert reconciled.opponent_name == "UNC Tar Heels"
    assert reconciled.is_home is True
    assert reconciled.status == GameStatus.FINAL
    assert reconciled.result == GameResult.WIN
    assert reconciled.home_score == 5
    assert reconciled.away_score == 3
    assert reconciled.contributing_sources == ["database"]
    assert reconciled.confidence_score == 1.0


def test_change_detection_models() -> None:
    """Verify FieldDiff, GameChangeRecord, and ChangeDetectionCycleResult."""
    # GameStateTransition enum
    assert GameStateTransition.CREATED == "CREATED"
    assert GameStateTransition.UPDATED == "UPDATED"
    assert GameStateTransition.DELETED == "DELETED"
    assert GameStateTransition.CONFLICT_DETECTED == "CONFLICT_DETECTED"
    assert GameStateTransition.UNCHANGED == "UNCHANGED"

    # FieldDiff
    fd = FieldDiff(
        field_name="venue",
        old_value="TBD",
        new_value="The Ice House",
        human_description="Venue changed from 'TBD' to 'The Ice House'",
    )
    fdd = fd.to_dict()
    assert fdd["field_name"] == "venue"
    assert fdd["old_value"] == "TBD"
    assert fdd["new_value"] == "The Ice House"
    assert fdd["human_description"] == "Venue changed from 'TBD' to 'The Ice House'"

    # GameChangeRecord
    rec = GameChangeRecord(
        canonical_game_id="game-001",
        state_transition=GameStateTransition.UPDATED,
        field_diffs=[fd],
        previous_snapshot={"venue": "TBD"},
        current_snapshot={"venue": "The Ice House"},
        human_summary=fd.human_description,
    )
    recd = rec.to_dict()
    assert recd["canonical_game_id"] == "game-001"
    assert recd["state_transition"] == "UPDATED"
    assert len(recd["field_diffs"]) == 1
    assert recd["previous_snapshot"] == {"venue": "TBD"}
    assert recd["current_snapshot"] == {"venue": "The Ice House"}
    assert recd["human_summary"] == fd.human_description
    assert recd["recorded_at"] is not None

    rec_created = GameChangeRecord(
        canonical_game_id="game-002",
        state_transition=GameStateTransition.CREATED,
    )
    rec_deleted = GameChangeRecord(
        canonical_game_id="game-003",
        state_transition=GameStateTransition.DELETED,
    )
    rec_conflict = GameChangeRecord(
        canonical_game_id="game-004",
        state_transition=GameStateTransition.CONFLICT_DETECTED,
    )
    rec_unchanged = GameChangeRecord(
        canonical_game_id="game-005",
        state_transition=GameStateTransition.UNCHANGED,
    )

    cycle_res = ChangeDetectionCycleResult(
        cycle_id="cycle-test-1",
        changes=[rec, rec_created, rec_deleted, rec_conflict, rec_unchanged],
    )

    assert cycle_res.created_games == [rec_created]
    assert cycle_res.updated_games == [rec]
    assert cycle_res.deleted_games == [rec_deleted]
    assert cycle_res.conflict_games == [rec_conflict]
    assert cycle_res.unchanged_games == [rec_unchanged]
    assert cycle_res.total_changes == 4

    cyd = cycle_res.to_dict()
    assert cyd["cycle_id"] == "cycle-test-1"
    assert cyd["total_changes"] == 4
    assert cyd["total_created"] == 1
    assert cyd["total_updated"] == 1
    assert cyd["total_deleted"] == 1
    assert cyd["total_conflicts"] == 1
    assert cyd["total_unchanged"] == 1
    assert len(cyd["changes"]) == 5

"""Comprehensive unit tests for ReconciliationEngine and conflict resolution."""

# pylint: disable=protected-access,too-many-arguments,too-many-locals

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ecu_hockey_calendar.models import GameResult
from ecu_hockey_calendar.reconciliation.engine import (
    CANONICAL_ECU_NAME,
    CANONICAL_SEASON,
    ReconciliationEngine,
    _are_both_venues_specified,
    _build_conflict_from_discrepancies,
    _build_date_discrepancy,
    _build_home_away_discrepancy,
    _build_initial_provenance,
    _build_score_discrepancy,
    _build_status_discrepancy,
    _build_time_discrepancy,
    _build_venue_discrepancy,
    _check_record_match_criteria,
    _collect_pairwise_discrepancies,
    _compute_cluster_confidence,
    _determine_reconciliation_status,
    _generate_canonical_game_id,
    _has_identical_game_ids,
    _has_review_requirement,
    _is_high_tier_source,
    _mark_conflicts_resolved,
    _resolve_game_identity,
    _resolve_pairwise_severity,
)
from ecu_hockey_calendar.reconciliation.models import (
    ConflictField,
    ConflictSeverity,
    DiscrepancyRecord,
    ReconciliationStatus,
    SourceGameRecord,
    SourcePriority,
    TimingRelationship,
)
from ecu_hockey_calendar.storage.models import DataSourceType, GameStatus


def _create_record(  # noqa: PLR0913
    opponent: str,
    dt: datetime,
    source_type: DataSourceType = DataSourceType.PRIMARY_SOT,
    source_code: str = "ecuhockey",
    venue: str = "The Factory",
    *,
    is_home: bool = True,
    is_tbd: bool = False,
    game_id: str | None = None,
    status: GameStatus = GameStatus.SCHEDULED,
    result: GameResult | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
    confidence: float = 1.0,
) -> SourceGameRecord:
    """Helper to instantiate test SourceGameRecord instances."""
    return SourceGameRecord(
        source_type=source_type,
        source_code=source_code,
        game_id=game_id,
        opponent_name=opponent,
        start_time=dt,
        end_time=None,
        is_home=is_home,
        is_time_tbd=is_tbd,
        venue=venue,
        status=status,
        result=result,
        home_score=home_score,
        away_score=away_score,
        confidence_score=confidence,
    )


def test_constants_and_game_id_generation() -> None:
    """Verify package constants and canonical identifier generation."""
    assert CANONICAL_ECU_NAME == "East Carolina University"
    assert CANONICAL_SEASON == "2026-2027"

    t = datetime(2026, 10, 15, 23, 0, tzinfo=UTC)  # 19:00 EDT Oct 15
    gid_home = _generate_canonical_game_id("UNC Chapel Hill", t, is_home=True)
    assert gid_home == "game-20261015-uncchapelhill-home"

    gid_away = _generate_canonical_game_id("NC State Icepack", t, is_home=False)
    assert gid_away == "game-20261015-ncstateicepack-away"


def test_match_criteria_and_helpers() -> None:
    """Verify pairwise match evaluation logic and identity resolution."""
    sp = SourcePriority()
    assert _is_high_tier_source("primary_sot", sp) is True
    assert _is_high_tier_source("league", sp) is True
    assert _is_high_tier_source("tickets", sp) is False

    t1 = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
    r1 = _create_record("UNC", t1, game_id="G-1")
    r2 = _create_record("UNC", t1, game_id="G-1")
    r3 = _create_record("Duke", t1, game_id="G-2")
    r_no_id = _create_record("UNC", t1, game_id=None)

    assert _has_identical_game_ids(r1, r2) is True
    assert _has_identical_game_ids(r1, r3) is False
    assert _has_identical_game_ids(r1, r_no_id) is False

    # Match criteria: identical game IDs
    assert (
        _check_record_match_criteria(r1, r2, 0.5, 0.8, time_aligned=False, days_diff=5)
        is True
    )
    # Low opponent similarity
    assert (
        _check_record_match_criteria(r1, r3, 0.4, 0.8, time_aligned=True, days_diff=0)
        is False
    )
    # Not time aligned
    assert (
        _check_record_match_criteria(
            r1,
            r_no_id,
            0.9,
            0.8,
            time_aligned=False,
            days_diff=2,
        )
        is False
    )
    # Adjacent day match with same home/away
    assert (
        _check_record_match_criteria(
            r1,
            r_no_id,
            0.9,
            0.8,
            time_aligned=True,
            days_diff=1,
        )
        is True
    )
    # Adjacent day match with differing home/away
    r_away = _create_record("UNC", t1, is_home=False)
    assert (
        _check_record_match_criteria(
            r1,
            r_away,
            0.9,
            0.8,
            time_aligned=True,
            days_diff=1,
        )
        is False
    )


def test_pairwise_severity_resolution() -> None:
    """Verify conflict severity calculation based on source precedence tiers."""
    sp = SourcePriority()
    # Both Tier 1 (primary_sot, league) -> HIGH
    assert (
        _resolve_pairwise_severity("primary_sot", "league", sp) == ConflictSeverity.HIGH
    )
    # One is Tier 2 or Tier 3 -> MEDIUM
    assert (
        _resolve_pairwise_severity("primary_sot", "tickets", sp)
        == ConflictSeverity.MEDIUM
    )
    assert (
        _resolve_pairwise_severity("tickets", "social", sp) == ConflictSeverity.MEDIUM
    )


def test_discrepancy_builders() -> None:
    """Verify builders for status, venue, time, date, home_away, and score."""
    sp = SourcePriority()
    t1 = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 15, 20, 30, tzinfo=UTC)

    # Status discrepancy
    r_sched = _create_record("UNC", t1, status=GameStatus.SCHEDULED)
    r_canc = _create_record("UNC", t1, status=GameStatus.CANCELLED)
    d_status = _build_status_discrepancy(r_sched, r_canc, sp)
    assert d_status is not None
    assert d_status.field == ConflictField.STATUS
    assert _build_status_discrepancy(r_sched, r_sched, sp) is None

    # Venue discrepancy
    assert _are_both_venues_specified("The Factory", "TBD") is False
    assert _are_both_venues_specified("The Factory", "Orange County Sportsplex") is True
    r_v1 = _create_record("UNC", t1, venue="The Factory")
    r_v2 = _create_record("UNC", t1, venue="Orange County Sportsplex")
    d_venue = _build_venue_discrepancy(r_v1, r_v2, 0.70, sp)
    assert d_venue is not None
    assert d_venue.field == ConflictField.VENUE
    assert _build_venue_discrepancy(r_v1, r_v1, 0.70, sp) is None
    r_unspec = _create_record("UNC", t1, venue="TBD")
    assert _build_venue_discrepancy(r_v1, r_unspec, 0.70, sp) is None

    # Time discrepancy
    r_t2 = _create_record("UNC", t2)
    d_time = _build_time_discrepancy(
        r_sched,
        r_t2,
        TimingRelationship.TIME_DISCREPANCY,
        90,
        sp,
    )
    assert d_time is not None
    assert d_time.field == ConflictField.START_TIME
    assert (
        _build_time_discrepancy(r_sched, r_sched, TimingRelationship.EXACT_MATCH, 0, sp)
        is None
    )
    assert (
        _build_time_discrepancy(
            r_sched,
            r_t2,
            TimingRelationship.TIME_DISCREPANCY,
            None,
            sp,
        )
        is None
    )

    # Date discrepancy
    t_other_day = datetime(2026, 10, 16, 19, 0, tzinfo=UTC)
    r_next_day = _create_record("UNC", t_other_day)
    d_date = _build_date_discrepancy(r_sched, r_next_day, 1, sp, "America/New_York")
    assert d_date is not None
    assert d_date.field == ConflictField.DATE
    assert _build_date_discrepancy(r_sched, r_sched, 0, sp, "America/New_York") is None

    # Home/Away discrepancy
    r_away = _create_record("UNC", t1, is_home=False)
    d_ha = _build_home_away_discrepancy(r_sched, r_away)
    assert d_ha is not None
    assert d_ha.field == ConflictField.HOME_AWAY
    assert _build_home_away_discrepancy(r_sched, r_sched) is None

    # Score discrepancy
    r_s1 = _create_record("UNC", t1, home_score=5, away_score=3)
    r_s2 = _create_record("UNC", t1, home_score=4, away_score=3)
    r_no_score = _create_record("UNC", t1, home_score=None, away_score=None)
    d_score = _build_score_discrepancy(r_s1, r_s2)
    assert d_score is not None
    assert d_score.field == ConflictField.HOME_SCORE
    assert _build_score_discrepancy(r_s1, r_s1) is None
    assert _build_score_discrepancy(r_s1, r_no_score) is None


def test_collect_pairwise_discrepancies() -> None:
    """Verify multi-field discrepancy accumulation across records."""
    sp = SourcePriority()
    t1 = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 15, 21, 0, tzinfo=UTC)
    r1 = _create_record("UNC", t1, venue="The Factory", status=GameStatus.SCHEDULED)
    r2 = _create_record(
        "UNC",
        t2,
        venue="Orange County Sportsplex",
        status=GameStatus.POSTPONED,
    )

    discs = _collect_pairwise_discrepancies(
        r1,
        r2,
        sp,
        venue_thresh=0.70,
        tz_name="America/New_York",
        exact_tol=15,
        near_tol=60,
    )
    fields = {d.field for d in discs}
    assert ConflictField.START_TIME in fields
    assert ConflictField.VENUE in fields
    assert ConflictField.STATUS in fields


def test_conflict_aggregation_and_resolution_helpers() -> None:
    """Verify conflict generation, marking resolved, and review flags."""
    d_high = DiscrepancyRecord(
        field=ConflictField.DATE,
        source_a="ecuhockey",
        source_b="acchockey",
        value_a="2026-10-15",
        value_b="2026-10-16",
        severity=ConflictSeverity.HIGH,
        notes="High conflict",
    )
    d_med = DiscrepancyRecord(
        field=ConflictField.START_TIME,
        source_a="ecuhockey",
        source_b="tickets",
        value_a="19:00",
        value_b="19:30",
        severity=ConflictSeverity.MEDIUM,
        notes="Medium time diff",
    )
    c_high = _build_conflict_from_discrepancies(ConflictField.DATE, [d_high], "G-1")
    assert c_high.severity == ConflictSeverity.HIGH
    assert c_high.requires_review is True

    c_med = _build_conflict_from_discrepancies(ConflictField.START_TIME, [d_med], "G-1")
    assert c_med.severity == ConflictSeverity.MEDIUM
    assert c_med.requires_review is False

    # _has_review_requirement
    assert _has_review_requirement([c_high, c_med]) is True
    assert _has_review_requirement([c_med]) is False

    # _mark_conflicts_resolved
    prov = {"date": "ecuhockey"}
    _mark_conflicts_resolved([c_high, c_med], prov, "default_src")
    assert c_high.resolved is True
    assert c_high.resolved_by_source == "ecuhockey"
    assert c_med.resolved is True
    assert c_med.resolved_by_source == "default_src"

    # _determine_reconciliation_status
    assert (
        _determine_reconciliation_status(has_conflicts=False, requires_review=False)
        == ReconciliationStatus.UNRESOLVED
    )
    assert (
        _determine_reconciliation_status(has_conflicts=True, requires_review=True)
        == ReconciliationStatus.FLAGGED_FOR_REVIEW
    )
    assert (
        _determine_reconciliation_status(has_conflicts=True, requires_review=False)
        == ReconciliationStatus.AUTO_RESOLVED
    )


def test_identity_and_provenance_helpers() -> None:
    """Verify identity resolution and initial provenance creation."""
    t = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
    r_with_id = _create_record("UNC", t, game_id="EXPLICIT-ID-1")
    r_no_id = _create_record("UNC", t, game_id=None)

    assert _resolve_game_identity(r_with_id, t, "America/New_York") == "EXPLICIT-ID-1"
    canon = _resolve_game_identity(r_no_id, t, "America/New_York")
    assert "unc" in canon

    prov = _build_initial_provenance(r_with_id)
    assert prov["opponent_name"] == "ecuhockey"
    assert prov["is_home"] == "ecuhockey"

    assert _compute_cluster_confidence([r_with_id, r_no_id]) == 1.0


def test_engine_initialization_and_matching() -> None:
    """Verify engine instantiation and pairwise record matching."""
    engine = ReconciliationEngine()
    t1 = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
    r1 = _create_record("UNC Chapel Hill", t1)
    r2 = _create_record(
        "UNC",
        t1,
        source_type=DataSourceType.LEAGUE,
        source_code="acchockey",
    )
    r_diff = _create_record("Duke", t1)

    is_m1, conf1, discs1 = engine.match_records(r1, r2)
    assert is_m1 is True
    assert conf1 > 0.8
    assert len(discs1) == 0

    is_m2, conf2, discs2 = engine.match_records(r1, r_diff)
    assert is_m2 is False
    assert conf2 == 0.0
    assert len(discs2) == 0


def test_engine_clustering() -> None:
    """Verify clustering of multi-source records for identical and distinct games."""
    engine = ReconciliationEngine()
    t1 = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 22, 19, 0, tzinfo=UTC)

    r1 = _create_record("UNC", t1, source_code="sot")
    r2 = _create_record("UNC Chapel Hill", t1, source_code="league")
    r3 = _create_record("Duke", t2, source_code="sot")

    # Empty list
    assert not engine.cluster_records([])

    # 3 records into 2 clusters
    clusters = engine.cluster_records([r1, r2, r3])
    assert len(clusters) == 2
    assert len(clusters[0]) == 2
    assert len(clusters[1]) == 1


def test_engine_time_and_venue_resolution() -> None:
    """Verify precedence hierarchy when selecting canonical time and venue fields."""
    engine = ReconciliationEngine()
    t_sched = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
    t_tbd = datetime(2026, 10, 15, 0, 0, tzinfo=ZoneInfo("America/New_York"))

    # Time fields: non-TBD wins even if sorted second
    r_tbd = _create_record(
        "UNC",
        t_tbd,
        source_type=DataSourceType.PRIMARY_SOT,
        source_code="sot",
        is_tbd=True,
    )
    r_time = _create_record(
        "UNC",
        t_sched,
        source_type=DataSourceType.TICKETS,
        source_code="tickets",
        is_tbd=False,
    )
    prov_time: dict[str, str] = {}
    st, _, is_tbd = engine._resolve_time_fields([r_tbd, r_time], prov_time)
    assert is_tbd is False
    assert st == t_sched
    assert prov_time["start_time"] == "tickets"

    # Time fields: when all records are TBD, falls back to top record
    r_tbd2 = _create_record(
        "UNC",
        t_tbd,
        source_type=DataSourceType.LEAGUE,
        source_code="league",
        is_tbd=True,
    )
    prov_all_tbd: dict[str, str] = {}
    st_tbd, _, all_tbd = engine._resolve_time_fields([r_tbd, r_tbd2], prov_all_tbd)
    assert all_tbd is True
    assert st_tbd == t_tbd

    # Venue fields: specified venue wins over unspecified
    r_no_ven = _create_record("UNC", t_sched, venue="TBD", source_code="sot")
    r_ven = _create_record("UNC", t_sched, venue="The Factory", source_code="league")
    prov_ven: dict[str, str] = {}
    venue = engine._resolve_venue_field([r_no_ven, r_ven], prov_ven)
    assert venue == "The Factory"
    assert prov_ven["venue"] == "league"

    # Venue fields: when all records have unspecified venue, falls back to top record
    r_no_ven2 = _create_record("UNC", t_sched, venue="TBA", source_code="league")
    prov_all_unspec: dict[str, str] = {}
    ven_unspec = engine._resolve_venue_field([r_no_ven, r_no_ven2], prov_all_unspec)
    assert ven_unspec == "TBD"


def test_engine_status_and_score_resolution() -> None:
    """Verify precedence hierarchy when selecting canonical status and score fields."""
    engine = ReconciliationEngine()
    t_sched = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)

    # Status fields: cancelled or postponed from Tier 1 wins over scheduled
    r_s = _create_record("UNC", t_sched, status=GameStatus.SCHEDULED, source_code="sot")
    r_c = _create_record(
        "UNC",
        t_sched,
        status=GameStatus.CANCELLED,
        source_type=DataSourceType.LEAGUE,
        source_code="league",
    )
    prov_stat: dict[str, str] = {}
    status = engine._resolve_status_field([r_s, r_c], prov_stat)
    assert status == GameStatus.CANCELLED
    assert prov_stat["status"] == "league"

    r_post = _create_record(
        "UNC",
        t_sched,
        status=GameStatus.POSTPONED,
        source_type=DataSourceType.PRIMARY_SOT,
        source_code="sot",
    )
    prov_post: dict[str, str] = {}
    assert engine._resolve_status_field([r_post], prov_post) == GameStatus.POSTPONED

    # Status fallback when no high-tier cancelled/postponed
    prov_stat_norm: dict[str, str] = {}
    status_norm = engine._resolve_status_field([r_s], prov_stat_norm)
    assert status_norm == GameStatus.SCHEDULED

    # Score fields: record with scores wins
    r_score = _create_record(
        "UNC",
        t_sched,
        home_score=5,
        away_score=2,
        result=GameResult.WIN,
        source_code="sot",
    )
    r_noscore = _create_record(
        "UNC",
        t_sched,
        home_score=None,
        away_score=None,
        source_code="tickets",
    )
    prov_score: dict[str, str] = {}
    res, hs, ascore = engine._resolve_scores_and_result(
        [r_noscore, r_score],
        prov_score,
    )
    assert res == GameResult.WIN
    assert hs == 5
    assert ascore == 2
    assert prov_score["result"] == "sot"

    # Score fields: when no records have scores, returns defaults from top
    prov_noscore: dict[str, str] = {}
    r_def, h_def, a_def = engine._resolve_scores_and_result([r_noscore], prov_noscore)
    assert r_def is None
    assert h_def is None
    assert a_def is None


def test_engine_reconcile_games_end_to_end() -> None:
    """Verify end-to-end reconciliation cycle with auto-resolved and flagged games."""
    engine = ReconciliationEngine()
    t1 = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
    t1_near = datetime(2026, 10, 15, 19, 30, tzinfo=UTC)

    # Game 1: Clean/auto-resolved match with minor time discrepancy
    g1_src1 = _create_record(
        "UNC",
        t1,
        source_type=DataSourceType.PRIMARY_SOT,
        source_code="sot",
    )
    g1_src2 = _create_record(
        "UNC Chapel Hill",
        t1_near,
        source_type=DataSourceType.TICKETS,
        source_code="tickets",
    )

    # Game 2: High conflict on status between Tier 1 sources (scheduled vs cancelled)
    t2 = datetime(2026, 10, 22, 19, 0, tzinfo=UTC)
    g2_src1 = _create_record(
        "NC State",
        t2,
        source_type=DataSourceType.PRIMARY_SOT,
        source_code="sot",
        status=GameStatus.SCHEDULED,
    )
    g2_src2 = _create_record(
        "NC State Icepack",
        t2,
        source_type=DataSourceType.LEAGUE,
        source_code="league",
        status=GameStatus.CANCELLED,
    )

    records = [g1_src1, g1_src2, g2_src1, g2_src2]
    result = engine.reconcile_games(records, cycle_id="CYCLE-TEST-1")

    assert result.cycle_id == "CYCLE-TEST-1"
    assert result.total_source_records == 4
    assert len(result.reconciled_games) == 2
    assert result.total_conflicts_detected >= 1
    assert result.completed_at >= result.started_at

    # Check game with flagged conflict
    flagged_games = [g for g in result.reconciled_games if g.requires_admin_review]
    assert len(flagged_games) == 1
    assert (
        flagged_games[0].status_reconciliation
        == ReconciliationStatus.FLAGGED_FOR_REVIEW
    )

    # Check auto-resolved or clean game
    clean_games = [g for g in result.reconciled_games if not g.requires_admin_review]
    assert len(clean_games) == 1

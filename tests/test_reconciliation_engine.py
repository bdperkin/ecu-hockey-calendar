"""Comprehensive unit tests for ReconciliationEngine and conflict resolution."""

# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-lines

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
    _has_both_scores,
    _has_conflicting_scores,
    _has_differing_source_game_ids,
    _has_identical_game_ids,
    _has_review_requirement,
    _is_adjacent_day_rollover,
    _is_candidate_prefiltered,
    _is_distinct_by_date_or_score,
    _is_high_tier_source,
    _is_identical_id_match,
    _is_same_source_distinct,
    _is_team_compatible,
    _is_temporal_match,
    _mark_conflicts_resolved,
    _resolve_game_identity,
    _resolve_pairwise_severity,
    _scores_equal,
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

    # Helper unit tests
    assert _has_differing_source_game_ids(r1, r2) is False
    assert _has_differing_source_game_ids(r1, r3) is True
    assert _has_differing_source_game_ids(r1, r_no_id) is False

    r_cross = _create_record(
        "UNC",
        t1,
        source_code="acchockey",
        source_type=DataSourceType.LEAGUE,
    )
    assert _is_same_source_distinct(r1, r_cross, days_diff=1) is False
    assert _is_same_source_distinct(r1, r3, days_diff=0) is True
    assert _is_same_source_distinct(r1, r_no_id, days_diff=1) is True
    assert _is_same_source_distinct(r1, r_no_id, days_diff=0) is False

    assert (
        _is_adjacent_day_rollover(
            days_diff=0,
            time_diff_minutes=30,
            tolerance_minutes=60,
        )
        is False
    )
    assert (
        _is_adjacent_day_rollover(
            days_diff=1,
            time_diff_minutes=None,
            tolerance_minutes=60,
        )
        is False
    )
    assert (
        _is_adjacent_day_rollover(
            days_diff=1,
            time_diff_minutes=30,
            tolerance_minutes=60,
        )
        is True
    )
    assert (
        _is_adjacent_day_rollover(
            days_diff=1,
            time_diff_minutes=1440,
            tolerance_minutes=60,
        )
        is False
    )

    assert (
        _is_temporal_match(
            days_diff=0,
            time_aligned=False,
            is_cross_source=True,
            time_diff_minutes=30,
            near_tolerance_min=60,
        )
        is False
    )
    assert (
        _is_temporal_match(
            days_diff=0,
            time_aligned=True,
            is_cross_source=False,
            time_diff_minutes=0,
            near_tolerance_min=60,
        )
        is True
    )
    assert (
        _is_temporal_match(
            days_diff=1,
            time_aligned=True,
            is_cross_source=True,
            time_diff_minutes=30,
            near_tolerance_min=60,
        )
        is True
    )
    assert (
        _is_temporal_match(
            days_diff=1,
            time_aligned=True,
            is_cross_source=False,
            time_diff_minutes=30,
            near_tolerance_min=60,
        )
        is False
    )

    # Match criteria: identical game IDs on same day
    assert (
        _check_record_match_criteria(r1, r2, 0.5, 0.8, time_aligned=False, days_diff=0)
        is True
    )
    # Identical game IDs on different days (days_diff > 0) -> must NOT match
    assert (
        _check_record_match_criteria(r1, r2, 0.5, 0.8, time_aligned=False, days_diff=5)
        is False
    )
    r_cross_same_id = _create_record(
        "UNC",
        t1,
        game_id="G-1",
        source_code="acchockey",
        source_type=DataSourceType.LEAGUE,
    )
    assert (
        _check_record_match_criteria(
            r1,
            r_cross_same_id,
            0.5,
            0.8,
            time_aligned=True,
            days_diff=1,
            time_diff_minutes=30,
        )
        is True
    )
    assert (
        _check_record_match_criteria(
            r1,
            r_cross_same_id,
            0.5,
            0.8,
            time_aligned=True,
            days_diff=1,
            time_diff_minutes=1440,
        )
        is False
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
    # Same source on adjacent day (weekend series) -> must NOT match
    assert (
        _check_record_match_criteria(
            r1,
            r_no_id,
            0.9,
            0.8,
            time_aligned=True,
            days_diff=1,
        )
        is False
    )
    # Cross source on same day with same home/away -> matches
    assert (
        _check_record_match_criteria(
            r1,
            r_cross,
            0.9,
            0.8,
            time_aligned=True,
            days_diff=0,
        )
        is True
    )
    # Cross source adjacent day with midnight rollover -> matches
    assert (
        _check_record_match_criteria(
            r1,
            r_cross,
            0.9,
            0.8,
            time_aligned=True,
            days_diff=1,
            time_diff_minutes=30,
            near_tolerance_min=60,
        )
        is True
    )
    # Cross source adjacent day without midnight rollover
    # (e.g. weekend series) -> does NOT match
    assert (
        _check_record_match_criteria(
            r1,
            r_cross,
            0.9,
            0.8,
            time_aligned=True,
            days_diff=1,
            time_diff_minutes=1440,
            near_tolerance_min=60,
        )
        is False
    )
    # Adjacent day match with differing home/away
    r_cross_away = _create_record(
        "UNC",
        t1,
        is_home=False,
        source_code="acchockey",
        source_type=DataSourceType.LEAGUE,
    )
    assert (
        _check_record_match_criteria(
            r1,
            r_cross_away,
            0.9,
            0.8,
            time_aligned=True,
            days_diff=1,
            time_diff_minutes=30,
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
    fb_id = _resolve_game_identity(
        r_no_id,
        t,
        "America/New_York",
        fallback_records=[r_with_id],
    )
    assert fb_id == "EXPLICIT-ID-1"

    r_sec_with_id = _create_record(
        "UNC",
        t,
        source_type=DataSourceType.OPPONENT,
        game_id="SECONDARY-ID-1",
    )
    sec_id = _resolve_game_identity(
        r_no_id,
        t,
        "America/New_York",
        fallback_records=[r_sec_with_id],
    )
    assert sec_id == "SECONDARY-ID-1"

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
    assert venue == "The Factory Ice House"
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


def test_engine_extract_cluster_fields() -> None:
    """Verify _extract_cluster_fields ensures unplayed fixtures clear scores."""
    engine = ReconciliationEngine()
    t_sched = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
    r_s = _create_record("UNC", t_sched, status=GameStatus.SCHEDULED, source_code="sot")
    r_c = _create_record(
        "UNC",
        t_sched,
        status=GameStatus.CANCELLED,
        source_type=DataSourceType.LEAGUE,
        source_code="league",
    )
    r_post = _create_record(
        "UNC",
        t_sched,
        status=GameStatus.POSTPONED,
        source_type=DataSourceType.PRIMARY_SOT,
        source_code="sot",
    )
    r_score = _create_record(
        "UNC",
        t_sched,
        home_score=5,
        away_score=2,
        result=GameResult.WIN,
        source_code="sot",
    )

    prov_cluster: dict[str, str] = {}
    f_sched = engine._extract_cluster_fields([r_s, r_score], prov_cluster)
    assert f_sched["status"] == GameStatus.SCHEDULED
    assert f_sched["result"] == GameResult.SCHEDULED
    assert f_sched["home_score"] is None
    assert f_sched["away_score"] is None

    prov_canc: dict[str, str] = {}
    f_canc = engine._extract_cluster_fields([r_c, r_score], prov_canc)
    assert f_canc["status"] == GameStatus.CANCELLED
    assert f_canc["result"] == GameResult.CANCELLED
    assert f_canc["home_score"] is None
    assert f_canc["away_score"] is None

    prov_post_cl: dict[str, str] = {}
    f_post = engine._extract_cluster_fields([r_post, r_score], prov_post_cl)
    assert f_post["status"] == GameStatus.POSTPONED
    assert f_post["result"] == GameResult.POSTPONED
    assert f_post["home_score"] is None
    assert f_post["away_score"] is None

    r_fin = _create_record("UNC", t_sched, status=GameStatus.FINAL, source_code="sot")
    prov_fin: dict[str, str] = {}
    f_fin = engine._extract_cluster_fields([r_fin, r_score], prov_fin)
    assert f_fin["status"] == GameStatus.FINAL
    assert f_fin["result"] == GameResult.WIN
    assert f_fin["home_score"] == 5
    assert f_fin["away_score"] == 2


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


def test_weekend_series_clustering_and_midnight_rollover() -> None:
    """Verify distinct weekend series games are kept separate and rollovers cluster."""
    engine = ReconciliationEngine()
    t_fri = datetime(2026, 10, 16, 23, 0, tzinfo=UTC)  # Friday 7:00 PM EDT
    t_sat = datetime(
        2026,
        10,
        17,
        23,
        0,
        tzinfo=UTC,
    )  # Saturday 7:00 PM EDT (24h later)

    # 1. Single source weekend series against same opponent
    rec_fri_ecu = _create_record(
        "Old Dominion",
        t_fri,
        game_id="game-fri",
        source_code="ecuhockey",
    )
    rec_sat_ecu = _create_record(
        "Old Dominion",
        t_sat,
        game_id="game-sat",
        source_code="ecuhockey",
    )
    clusters_single = engine.cluster_records([rec_fri_ecu, rec_sat_ecu])
    assert len(clusters_single) == 2

    # 2. Multi-source weekend series (ecuhockey + acchockey)
    rec_fri_acc = _create_record(
        "Old Dominion",
        t_fri,
        game_id="acc-fri",
        source_code="acchockey",
        source_type=DataSourceType.LEAGUE,
    )
    rec_sat_acc = _create_record(
        "Old Dominion",
        t_sat,
        game_id="acc-sat",
        source_code="acchockey",
        source_type=DataSourceType.LEAGUE,
    )
    clusters_multi = engine.cluster_records(
        [rec_fri_ecu, rec_sat_ecu, rec_fri_acc, rec_sat_acc],
    )
    assert len(clusters_multi) == 2
    assert len(clusters_multi[0]) == 2
    assert len(clusters_multi[1]) == 2

    # 3. Cross-source midnight rollover (30m difference across midnight)
    t_late = datetime(2026, 10, 17, 3, 45, tzinfo=UTC)  # Friday 11:45 PM EDT
    t_early = datetime(2026, 10, 17, 4, 15, tzinfo=UTC)  # Saturday 12:15 AM EDT
    rec_late = _create_record("UNC", t_late, source_code="ecuhockey")
    rec_early = _create_record(
        "UNC",
        t_early,
        source_code="acchockey",
        source_type=DataSourceType.LEAGUE,
    )
    clusters_rollover = engine.cluster_records([rec_late, rec_early])
    assert len(clusters_rollover) == 1
    assert len(clusters_rollover[0]) == 2


def test_engine_consensus_and_source_weighting() -> None:
    """Verify multi-source consensus and away host weighting over visiting team."""
    engine = ReconciliationEngine()
    t_wrong = datetime(2026, 9, 20, 0, 0, tzinfo=UTC)  # 8:00 PM EDT
    t_correct = datetime(2026, 9, 20, 1, 30, tzinfo=UTC)  # 9:30 PM EDT

    r_ecu = _create_record(
        "UNC Charlotte",
        t_wrong,
        source_type=DataSourceType.PRIMARY_SOT,
        source_code="ecuhockey",
        venue="Indian Trail",
        is_home=False,
        game_id="game-vs-charlotte-on-09192026-mrxgmz79",
    )
    r_opp = _create_record(
        "UNC Charlotte",
        t_correct,
        source_type=DataSourceType.OPPONENT,
        source_code="opponent",
        venue="Extreme Ice Center - 4705 Indian Trail Fairview Rd, Indian Trail, NC",
        is_home=False,
    )
    r_acha = _create_record(
        "UNC Charlotte",
        t_correct,
        source_type=DataSourceType.LEAGUE,
        source_code="achahockey",
        venue="Extreme Ice Center",
        is_home=False,
        game_id="ecu-away-university-of-north-carolina-charlotte-20260920",
    )

    cluster = [r_ecu, r_opp, r_acha]
    rec_game = engine.resolve_cluster(cluster)

    assert rec_game.canonical_game_id == "game-vs-charlotte-on-09192026-mrxgmz79"
    assert rec_game.start_time == t_correct
    assert rec_game.venue == "Extreme Ice Center"
    assert not rec_game.is_home
    assert rec_game.field_provenance["start_time"] == "opponent"
    assert rec_game.field_provenance["venue"] == "opponent"
    assert rec_game.status_reconciliation == ReconciliationStatus.AUTO_RESOLVED
    assert not rec_game.requires_admin_review


def test_engine_home_game_weighting() -> None:
    """Verify home game weights ECU primary source higher than opponent."""
    engine = ReconciliationEngine()
    t_ecu = datetime(2026, 10, 10, 23, 0, tzinfo=UTC)  # 7:00 PM EDT
    t_opp = datetime(2026, 10, 11, 0, 30, tzinfo=UTC)  # 8:30 PM EDT

    r_ecu = _create_record(
        "UNC Charlotte",
        t_ecu,
        source_type=DataSourceType.PRIMARY_SOT,
        source_code="ecuhockey",
        venue="Carolina Ice Zone",
        is_home=True,
    )
    r_opp = _create_record(
        "UNC Charlotte",
        t_opp,
        source_type=DataSourceType.OPPONENT,
        source_code="opponent",
        venue="Carolina Ice Zone",
        is_home=True,
    )

    rec_game = engine.resolve_cluster([r_ecu, r_opp])
    assert rec_game.start_time == t_ecu
    assert rec_game.venue == "Carolina Ice Zone"
    assert rec_game.is_home
    assert rec_game.field_provenance["start_time"] == "ecuhockey"


def test_candidate_grouping_multiple_groups() -> None:
    """Verify time and venue grouping with multiple existing groups."""
    engine = ReconciliationEngine()
    t1 = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 15, 21, 30, tzinfo=UTC)
    r_a = _create_record(
        "UNC",
        t1,
        venue="The Factory Ice House",
        source_type=DataSourceType.PRIMARY_SOT,
    )
    r_b = _create_record(
        "UNC",
        t2,
        venue="Extreme Ice Center",
        source_type=DataSourceType.LEAGUE,
    )
    r_b2 = _create_record(
        "UNC",
        t2,
        venue="Extreme Ice Center - 4705 Indian Trail",
        source_type=DataSourceType.OPPONENT,
    )

    prov_t: dict[str, str] = {}
    st, _, _ = engine._resolve_time_fields([r_a, r_b, r_b2], prov_t)
    assert st == t2

    prov_v: dict[str, str] = {}
    v = engine._resolve_venue_field([r_a, r_b, r_b2], prov_v)
    assert v == "Extreme Ice Center"


def test_date_and_score_distinction_helpers() -> None:
    """Verify all helper functions for score comparison and event distinction."""
    t1 = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 16, 19, 0, tzinfo=UTC)

    r_none = _create_record("UNC", t1)
    r_home_only = _create_record("UNC", t1, home_score=5)
    r_score_a = _create_record("UNC", t1, home_score=4, away_score=6)
    r_score_a_dup = _create_record("UNC", t1, home_score=4, away_score=6)
    r_score_b = _create_record("UNC", t2, home_score=4, away_score=13)

    # _has_both_scores
    assert _has_both_scores(r_none) is False
    assert _has_both_scores(r_home_only) is False
    assert _has_both_scores(r_score_a) is True

    # _scores_equal
    assert _scores_equal(r_score_a, r_score_a_dup) is True
    assert _scores_equal(r_score_a, r_score_b) is False

    # _has_conflicting_scores
    assert _has_conflicting_scores(r_none, r_score_a) is False
    assert _has_conflicting_scores(r_score_a, r_score_a_dup) is False
    assert _has_conflicting_scores(r_score_a, r_score_b) is True

    # _is_distinct_by_date_or_score
    assert (
        _is_distinct_by_date_or_score(
            r_none,
            r_score_a,
            days_diff=1,
            time_diff_minutes=60,
            near_tolerance_min=60,
        )
        is False
    )
    assert (
        _is_distinct_by_date_or_score(
            r_score_a,
            r_score_b,
            days_diff=1,
            time_diff_minutes=60,
            near_tolerance_min=60,
        )
        is True
    )
    assert (
        _is_distinct_by_date_or_score(
            r_score_a,
            r_score_b,
            days_diff=0,
            time_diff_minutes=30,
            near_tolerance_min=60,
        )
        is False
    )
    assert (
        _is_distinct_by_date_or_score(
            r_score_a,
            r_score_b,
            days_diff=0,
            time_diff_minutes=120,
            near_tolerance_min=60,
        )
        is True
    )

    # _is_identical_id_match
    r_id1 = _create_record("UNC", t1, game_id="ID-1")
    r_id2 = _create_record("UNC", t1, game_id="ID-2")
    r_id1_dup = _create_record("UNC", t1, game_id="ID-1")
    assert (
        _is_identical_id_match(
            r_id1,
            r_id2,
            days_diff=0,
            time_diff_minutes=0,
            near_tolerance_min=60,
        )
        is False
    )
    assert (
        _is_identical_id_match(
            r_id1,
            r_id1_dup,
            days_diff=0,
            time_diff_minutes=0,
            near_tolerance_min=60,
        )
        is True
    )
    assert (
        _is_identical_id_match(
            r_id1,
            r_id1_dup,
            days_diff=1,
            time_diff_minutes=30,
            near_tolerance_min=60,
        )
        is True
    )
    assert (
        _is_identical_id_match(
            r_id1,
            r_id1_dup,
            days_diff=1,
            time_diff_minutes=120,
            near_tolerance_min=60,
        )
        is False
    )

    # _is_team_compatible
    r_home = _create_record("UNC", t1, is_home=True)
    r_away = _create_record("UNC", t1, is_home=False)
    assert _is_team_compatible(r_home, r_home, opp_sim=0.9, opp_thresh=0.8) is True
    assert _is_team_compatible(r_home, r_home, opp_sim=0.7, opp_thresh=0.8) is False
    assert _is_team_compatible(r_home, r_away, opp_sim=0.9, opp_thresh=0.8) is False

    # _is_candidate_prefiltered
    assert (
        _is_candidate_prefiltered(
            r_score_a,
            r_score_b,
            days_diff=1,
            time_diff_minutes=60,
            near_tolerance_min=60,
        )
        is True
    )
    assert (
        _is_candidate_prefiltered(
            r_none,
            r_none,
            days_diff=0,
            time_diff_minutes=0,
            near_tolerance_min=60,
        )
        is False
    )


def test_weekend_series_distinct_dates_and_scores_not_clustered() -> None:
    """Verify weekend series on different days and scores are two unique events."""
    engine = ReconciliationEngine()
    t_sat = datetime(2025, 1, 11, 21, 0, tzinfo=UTC)
    t_sun = datetime(2025, 1, 12, 16, 0, tzinfo=UTC)

    # 1. Distinct IDs
    r_sat = _create_record(
        "UCF",
        t_sat,
        is_home=False,
        home_score=4,
        away_score=6,
        game_id="game-vs-ucf-on-01112025-lyiwyiqy",
        source_code="ecuhockey",
    )
    r_sun = _create_record(
        "UCF",
        t_sun,
        is_home=False,
        home_score=4,
        away_score=13,
        game_id="game-vs-ucf-on-01102025-lyiwxkmn",
        source_code="ecuhockey",
    )

    is_same, _, discs = engine.match_records(r_sat, r_sun)
    assert is_same is False
    assert len(discs) == 0

    clusters = engine.cluster_records([r_sat, r_sun])
    assert len(clusters) == 2

    cycle_res = engine.reconcile_games([r_sat, r_sun])
    assert len(cycle_res.reconciled_games) == 2
    assert cycle_res.total_conflicts_detected == 0

    # 2. Identical game IDs across different days with different scores
    r_sun_shared_id = _create_record(
        "UCF",
        t_sun,
        is_home=False,
        home_score=4,
        away_score=13,
        game_id="game-vs-ucf-on-01102025-lyiwxkmn",
        source_code="ecuhockey",
    )
    r_sat_shared_id = _create_record(
        "UCF",
        t_sat,
        is_home=False,
        home_score=4,
        away_score=6,
        game_id="game-vs-ucf-on-01102025-lyiwxkmn",
        source_code="ecuhockey",
    )

    is_same_shared, _, _ = engine.match_records(r_sat_shared_id, r_sun_shared_id)
    assert is_same_shared is False

    clusters_shared = engine.cluster_records([r_sat_shared_id, r_sun_shared_id])
    assert len(clusters_shared) == 2

    cycle_res_shared = engine.reconcile_games([r_sat_shared_id, r_sun_shared_id])
    assert len(cycle_res_shared.reconciled_games) == 2
    assert cycle_res_shared.total_conflicts_detected == 0

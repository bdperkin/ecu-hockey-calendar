"""Unit tests for timezone-aware date and time alignment engine."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from ecu_hockey_calendar.reconciliation.date_aligner import (
    DateTimeAlignmentResult,
    align_game_datetimes,
    compute_date_distance_days,
    compute_time_difference_minutes,
    is_start_time_tbd,
    to_local_date,
    to_local_datetime,
)
from ecu_hockey_calendar.reconciliation.models import TimingRelationship


def test_date_time_alignment_result_to_dict() -> None:
    """Verify serialization of DateTimeAlignmentResult to dictionary."""
    res = DateTimeAlignmentResult(
        relationship=TimingRelationship.EXACT_MATCH,
        date_difference_days=0,
        time_difference_minutes=5,
        aligned=True,
        is_tbd=False,
        confidence_factor=1.0,
        notes="Exact match",
    )
    d = res.to_dict()
    assert d["relationship"] == "exact_match"
    assert d["date_difference_days"] == 0
    assert d["time_difference_minutes"] == 5
    assert d["aligned"] is True
    assert d["is_tbd"] is False
    assert d["confidence_factor"] == 1.0
    assert d["notes"] == "Exact match"


def test_to_local_datetime_and_date() -> None:
    """Verify timezone conversions for naive and aware datetimes."""
    # Aware datetime in UTC
    utc_dt = datetime(2026, 10, 15, 23, 0, tzinfo=UTC)
    local_dt = to_local_datetime(utc_dt, "America/New_York")
    assert local_dt.tzinfo == ZoneInfo("America/New_York")
    # EDT is UTC-4: 23:00 UTC = 19:00 EDT
    assert local_dt.hour == 19
    assert to_local_date(utc_dt, "America/New_York") == date(2026, 10, 15)

    # Cross-midnight date rollover: 02:00 UTC Oct 16 is 22:00 EDT Oct 15
    rollover_utc = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)
    assert to_local_date(rollover_utc, "America/New_York") == date(2026, 10, 15)

    # Naive datetime
    naive_dt = datetime(2026, 10, 15, 19, 0)  # noqa: DTZ001
    local_naive = to_local_datetime(naive_dt, "America/New_York")
    assert local_naive.tzinfo == ZoneInfo("America/New_York")
    assert local_naive.hour == 19


def test_is_start_time_tbd() -> None:
    """Verify detection of TBD/tentative start times and midnight placeholders."""
    # Explicit flag
    any_dt = datetime(2026, 10, 15, 19, 30, tzinfo=UTC)
    assert is_start_time_tbd(any_dt, is_explicit_tbd=True) is True

    # Local midnight placeholder (00:00:00 EDT is 04:00:00 UTC in EDT)
    ny_tz = ZoneInfo("America/New_York")
    midnight_local = datetime(2026, 10, 15, 0, 0, 0, tzinfo=ny_tz)
    assert is_start_time_tbd(midnight_local) is True

    # Normal scheduled time
    game_local = datetime(2026, 10, 15, 19, 0, 0, tzinfo=ny_tz)
    assert is_start_time_tbd(game_local) is False


def test_compute_time_difference_minutes() -> None:
    """Verify absolute minute differences across timezones and naive datetimes."""
    t1 = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 15, 19, 45, tzinfo=UTC)
    assert compute_time_difference_minutes(t1, t2) == 45
    assert compute_time_difference_minutes(t2, t1) == 45

    # Naive datetimes
    n1 = datetime(2026, 10, 15, 19, 0)  # noqa: DTZ001
    n2 = datetime(2026, 10, 15, 20, 15)  # noqa: DTZ001
    assert compute_time_difference_minutes(n1, n2) == 75


def test_compute_date_distance_days() -> None:
    """Verify calendar day distance in target local timezone."""
    d1 = datetime(2026, 10, 15, 23, 0, tzinfo=UTC)  # 19:00 EDT Oct 15
    d2 = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)  # 23:00 EDT Oct 15
    assert compute_date_distance_days(d1, d2, "America/New_York") == 0

    d3 = datetime(2026, 10, 17, 19, 0, tzinfo=UTC)  # Oct 17
    assert compute_date_distance_days(d1, d3, "America/New_York") == 2


def test_align_game_datetimes_exact_and_near() -> None:
    """Verify same-day exact and near tolerance alignments."""
    t1 = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
    # Exactly matching time
    res_exact = align_game_datetimes(t1, t1)
    assert res_exact.relationship == TimingRelationship.EXACT_MATCH
    assert res_exact.aligned is True
    assert res_exact.confidence_factor == 1.0

    # Within exact tolerance (e.g. 10m difference <= 15m)
    t_10m = datetime(2026, 10, 15, 19, 10, tzinfo=UTC)
    res_exact_tol = align_game_datetimes(t1, t_10m)
    assert res_exact_tol.relationship == TimingRelationship.EXACT_MATCH
    assert res_exact_tol.aligned is True

    # Within near tolerance (e.g. 45m difference <= 60m)
    t_45m = datetime(2026, 10, 15, 19, 45, tzinfo=UTC)
    res_near = align_game_datetimes(t1, t_45m)
    assert res_near.relationship == TimingRelationship.WITHIN_TOLERANCE
    assert res_near.aligned is True
    assert res_near.confidence_factor == 0.90

    # Large time discrepancy (e.g. 120m difference > 60m)
    t_120m = datetime(2026, 10, 15, 21, 0, tzinfo=UTC)
    res_disc = align_game_datetimes(t1, t_120m)
    assert res_disc.relationship == TimingRelationship.TIME_DISCREPANCY
    assert res_disc.aligned is True
    assert res_disc.confidence_factor == 0.60


def test_align_game_datetimes_tbd() -> None:
    """Verify TBD alignment when one source has tentative start time."""
    t_scheduled = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
    t_tbd = datetime(2026, 10, 15, 0, 0, tzinfo=ZoneInfo("America/New_York"))

    res = align_game_datetimes(t_scheduled, t_tbd, b_tbd=True)
    assert res.relationship == TimingRelationship.TIME_TBD_MATCH
    assert res.aligned is True
    assert res.is_tbd is True
    assert res.confidence_factor == 0.85
    assert res.time_difference_minutes is None


def test_align_game_datetimes_adjacent_and_mismatch() -> None:
    """Verify adjacent-day rollover and multi-day mismatch alignments."""
    t1 = datetime(2026, 10, 15, 19, 0, tzinfo=UTC)
    # Adjacent day (Oct 16)
    t_next_day = datetime(2026, 10, 16, 19, 0, tzinfo=UTC)
    res_adj = align_game_datetimes(t1, t_next_day)
    assert res_adj.relationship == TimingRelationship.DATE_ADJACENT
    assert res_adj.aligned is True
    assert res_adj.date_difference_days == 1
    assert res_adj.confidence_factor == 0.40

    # 3-day mismatch
    t_3days = datetime(2026, 10, 18, 19, 0, tzinfo=UTC)
    res_mismatch = align_game_datetimes(t1, t_3days)
    assert res_mismatch.relationship == TimingRelationship.DATE_MISMATCH
    assert res_mismatch.aligned is False
    assert res_mismatch.date_difference_days == 3
    assert res_mismatch.confidence_factor == 0.0

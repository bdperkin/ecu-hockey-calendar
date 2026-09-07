"""Timezone-aware date and time alignment engine for schedule reconciliation.

This module resolves date and time differences across ingestion sources,
accounting for local timezone conversions, DST boundaries, tentative or
TBD start times, and tolerance thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from ecu_hockey_calendar.reconciliation.models import TimingRelationship

DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_EXACT_TOLERANCE_MINUTES = 15
DEFAULT_NEAR_TOLERANCE_MINUTES = 60
ADJACENT_DAY_DIFF_DAYS = 1
CONFIDENCE_EXACT = 1.0
CONFIDENCE_NEAR = 0.90
CONFIDENCE_TBD = 0.85
CONFIDENCE_TIME_DISCREPANCY = 0.60
CONFIDENCE_ADJACENT_DAY = 0.40
CONFIDENCE_MISMATCH = 0.0
SECONDS_PER_MINUTE = 60


@dataclass(frozen=True)
class DateTimeAlignmentResult:
    """Outcome of temporal alignment between two game timestamps."""

    relationship: TimingRelationship
    date_difference_days: int
    time_difference_minutes: int | None
    aligned: bool
    is_tbd: bool
    confidence_factor: float
    notes: str = ""

    def to_dict(self) -> dict[str, str | int | float | bool | None]:
        """Serialize alignment result to dictionary."""
        return {
            "relationship": self.relationship.value,
            "date_difference_days": self.date_difference_days,
            "time_difference_minutes": self.time_difference_minutes,
            "aligned": self.aligned,
            "is_tbd": self.is_tbd,
            "confidence_factor": round(self.confidence_factor, 2),
            "notes": self.notes,
        }


def to_local_datetime(
    dt: datetime,
    tz_name: str = DEFAULT_TIMEZONE,
) -> datetime:
    """Convert an arbitrary datetime to the target local timezone.

    Args:
        dt: Aware or naive datetime object.
        tz_name: IANA timezone identifier string.

    Returns:
        Timezone-aware datetime in the target timezone.
    """
    tz = ZoneInfo(tz_name)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)

    return dt.astimezone(tz)


def to_local_date(
    dt: datetime,
    tz_name: str = DEFAULT_TIMEZONE,
) -> date:
    """Extract local calendar date for a timestamp.

    Args:
        dt: Datetime object.
        tz_name: IANA timezone identifier string.

    Returns:
        datetime.date instance in target local timezone.
    """
    return to_local_datetime(dt, tz_name).date()


def is_start_time_tbd(
    dt: datetime,
    *,
    is_explicit_tbd: bool = False,
    tz_name: str = DEFAULT_TIMEZONE,
) -> bool:
    """Determine if a start time represents a tentative or TBD schedule entry.

    Args:
        dt: Game start datetime.
        is_explicit_tbd: Explicit flag from upstream metadata.
        tz_name: Target local timezone.

    Returns:
        True if start time is unknown, midnight placeholder, or explicit TBD.
    """
    if is_explicit_tbd:
        return True

    local_dt = to_local_datetime(dt, tz_name)
    return local_dt.hour == 0 and local_dt.minute == 0 and local_dt.second == 0


def compute_time_difference_minutes(dt_a: datetime, dt_b: datetime) -> int:
    """Calculate absolute difference in minutes between two timestamps in UTC.

    Args:
        dt_a: First datetime object.
        dt_b: Second datetime object.

    Returns:
        Absolute difference in integer minutes.
    """
    utc_a = dt_a.astimezone(UTC) if dt_a.tzinfo else dt_a.replace(tzinfo=UTC)
    utc_b = dt_b.astimezone(UTC) if dt_b.tzinfo else dt_b.replace(tzinfo=UTC)
    delta_sec = abs((utc_a - utc_b).total_seconds())
    return int(delta_sec // SECONDS_PER_MINUTE)


def compute_date_distance_days(
    dt_a: datetime,
    dt_b: datetime,
    tz_name: str = DEFAULT_TIMEZONE,
) -> int:
    """Calculate absolute difference in calendar days in local timezone.

    Args:
        dt_a: First datetime.
        dt_b: Second datetime.
        tz_name: Target local timezone identifier.

    Returns:
        Absolute difference in days.
    """
    date_a = to_local_date(dt_a, tz_name)
    date_b = to_local_date(dt_b, tz_name)
    return abs((date_a - date_b).days)


def _evaluate_same_day_time(
    diff_minutes: int,
    exact_tolerance: int,
    near_tolerance: int,
) -> tuple[TimingRelationship, float, str]:
    """Evaluate timing relationship when dates match and neither is TBD."""
    if diff_minutes <= exact_tolerance:
        return (
            TimingRelationship.EXACT_MATCH,
            CONFIDENCE_EXACT,
            f"Exact time match within {exact_tolerance}m tolerance",
        )

    if diff_minutes <= near_tolerance:
        return (
            TimingRelationship.WITHIN_TOLERANCE,
            CONFIDENCE_NEAR,
            f"Time match within near tolerance ({diff_minutes}m diff)",
        )

    return (
        TimingRelationship.TIME_DISCREPANCY,
        CONFIDENCE_TIME_DISCREPANCY,
        f"Significant time discrepancy ({diff_minutes}m diff)",
    )


def _evaluate_same_day_alignment(
    dt_a: datetime,
    dt_b: datetime,
    *,
    is_tbd: bool,
    exact_tolerance: int,
    near_tolerance: int,
) -> DateTimeAlignmentResult:
    """Construct alignment result when fixtures fall on the same local date."""
    if is_tbd:
        return DateTimeAlignmentResult(
            relationship=TimingRelationship.TIME_TBD_MATCH,
            date_difference_days=0,
            time_difference_minutes=None,
            aligned=True,
            is_tbd=True,
            confidence_factor=CONFIDENCE_TBD,
            notes="Same-day date match with TBD/tentative start time",
        )

    diff_min = compute_time_difference_minutes(dt_a, dt_b)
    rel, conf, note = _evaluate_same_day_time(
        diff_min,
        exact_tolerance,
        near_tolerance,
    )
    return DateTimeAlignmentResult(
        relationship=rel,
        date_difference_days=0,
        time_difference_minutes=diff_min,
        aligned=True,
        is_tbd=False,
        confidence_factor=conf,
        notes=note,
    )


def align_game_datetimes(
    dt_a: datetime,
    dt_b: datetime,
    *,
    a_tbd: bool = False,
    b_tbd: bool = False,
    exact_tolerance_min: int = DEFAULT_EXACT_TOLERANCE_MINUTES,
    near_tolerance_min: int = DEFAULT_NEAR_TOLERANCE_MINUTES,
    tz_name: str = DEFAULT_TIMEZONE,
) -> DateTimeAlignmentResult:
    """Compare and align game timestamps across sources.

    Evaluates local calendar day agreement, tolerance windows, and TBD status.

    Args:
        dt_a: First game start datetime.
        dt_b: Second game start datetime.
        a_tbd: Whether first timestamp has TBD start time.
        b_tbd: Whether second timestamp has TBD start time.
        exact_tolerance_min: Maximum minute difference for exact match.
        near_tolerance_min: Maximum minute difference for near match.
        tz_name: Target local timezone identifier.

    Returns:
        DateTimeAlignmentResult containing classification and metrics.
    """
    days_diff = compute_date_distance_days(dt_a, dt_b, tz_name)
    either_tbd = is_start_time_tbd(
        dt_a,
        is_explicit_tbd=a_tbd,
        tz_name=tz_name,
    ) or is_start_time_tbd(dt_b, is_explicit_tbd=b_tbd, tz_name=tz_name)

    if days_diff == 0:
        return _evaluate_same_day_alignment(
            dt_a,
            dt_b,
            is_tbd=either_tbd,
            exact_tolerance=exact_tolerance_min,
            near_tolerance=near_tolerance_min,
        )

    diff_min = compute_time_difference_minutes(dt_a, dt_b)
    if days_diff == ADJACENT_DAY_DIFF_DAYS:
        return DateTimeAlignmentResult(
            relationship=TimingRelationship.DATE_ADJACENT,
            date_difference_days=days_diff,
            time_difference_minutes=diff_min,
            aligned=True,
            is_tbd=either_tbd,
            confidence_factor=CONFIDENCE_ADJACENT_DAY,
            notes="Adjacent day fixture alignment (potential date shift or rollover)",
        )

    return DateTimeAlignmentResult(
        relationship=TimingRelationship.DATE_MISMATCH,
        date_difference_days=days_diff,
        time_difference_minutes=diff_min,
        aligned=False,
        is_tbd=either_tbd,
        confidence_factor=CONFIDENCE_MISMATCH,
        notes=f"Dates differ by {days_diff} calendar days in {tz_name}",
    )


__all__ = [
    "ADJACENT_DAY_DIFF_DAYS",
    "CONFIDENCE_ADJACENT_DAY",
    "CONFIDENCE_EXACT",
    "CONFIDENCE_MISMATCH",
    "CONFIDENCE_NEAR",
    "CONFIDENCE_TBD",
    "CONFIDENCE_TIME_DISCREPANCY",
    "DEFAULT_EXACT_TOLERANCE_MINUTES",
    "DEFAULT_NEAR_TOLERANCE_MINUTES",
    "DEFAULT_TIMEZONE",
    "DateTimeAlignmentResult",
    "align_game_datetimes",
    "compute_date_distance_days",
    "compute_time_difference_minutes",
    "is_start_time_tbd",
    "to_local_date",
    "to_local_datetime",
]

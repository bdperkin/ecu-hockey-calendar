"""Multi-source schedule reconciliation and conflict resolution engine.

This module clusters game fixtures from disparate ingestion sources, detects
discrepancies in date, start time, venue, status, and home/away designations,
applies configurable source priority hierarchies, and flags high-confidence
conflicts for administrative review.
"""
# pylint: disable=too-many-lines

from __future__ import annotations

from datetime import UTC, datetime
from itertools import combinations
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ecu_hockey_calendar.models import GameResult
from ecu_hockey_calendar.reconciliation.date_aligner import (
    DEFAULT_EXACT_TOLERANCE_MINUTES,
    DEFAULT_NEAR_TOLERANCE_MINUTES,
    DEFAULT_TIMEZONE,
    align_game_datetimes,
    to_local_date,
)
from ecu_hockey_calendar.reconciliation.fuzzy_matcher import (
    DEFAULT_OPPONENT_MATCH_THRESHOLD,
    DEFAULT_VENUE_MATCH_THRESHOLD,
    compute_opponent_similarity,
    is_venue_match,
    is_venue_unspecified,
    resolve_canonical_venue,
)
from ecu_hockey_calendar.reconciliation.models import (
    ConflictField,
    ConflictSeverity,
    DetectedConflict,
    DiscrepancyRecord,
    ReconciledGame,
    ReconciliationCycleResult,
    ReconciliationStatus,
    SourceGameRecord,
    SourcePriority,
    TimingRelationship,
    lookup_tiebreaker_order,
    normalize_source_key,
)
from ecu_hockey_calendar.storage.models import DataSourceType, GameStatus

if TYPE_CHECKING:
    from collections.abc import Sequence

CANONICAL_ECU_NAME = "East Carolina University"
CANONICAL_SEASON = "2026-2027"


def _is_high_tier_source(
    source_type: str,
    priority: SourcePriority,
    *,
    is_home: bool = True,
) -> bool:
    """Check if source belongs to the highest precedence tier (Tier 1)."""
    return priority.get_tier(source_type, is_home=is_home) == 1


def _generate_canonical_game_id(
    opponent_name: str,
    start_time: datetime,
    *,
    is_home: bool,
    tz_name: str = DEFAULT_TIMEZONE,
) -> str:
    """Generate a deterministic canonical game identifier."""
    local_d = to_local_date(start_time, tz_name).strftime("%Y%m%d")
    slug = "".join(c for c in opponent_name.lower() if c.isalnum() or c == "-")
    ha = "home" if is_home else "away"
    return f"game-{local_d}-{slug[:16]}-{ha}"


def _has_identical_game_ids(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
) -> bool:
    """Check if both records possess identical non-null game identifiers."""
    return bool(rec_a.game_id and rec_a.game_id == rec_b.game_id)


def _has_differing_source_game_ids(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
) -> bool:
    """Check if both records have different non-empty source game IDs."""
    if not (rec_a.game_id and rec_b.game_id):
        return False

    return rec_a.game_id != rec_b.game_id


def _has_both_scores(rec: SourceGameRecord) -> bool:
    """Check if a source record contains complete home and away scores."""
    return rec.home_score is not None and rec.away_score is not None


def _scores_equal(rec_a: SourceGameRecord, rec_b: SourceGameRecord) -> bool:
    """Check if scores between two records match exactly."""
    return rec_a.home_score == rec_b.home_score and rec_a.away_score == rec_b.away_score


def _has_conflicting_scores(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
) -> bool:
    """Check if both records possess complete scores that do not match."""
    return (
        _has_both_scores(rec_a)
        and _has_both_scores(rec_b)
        and not _scores_equal(rec_a, rec_b)
    )


def _is_distinct_by_date_or_score(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
    days_diff: int,
    time_diff_minutes: int | None,
    near_tolerance_min: int,
) -> bool:
    """Check if records must be treated as unique events due to dates or scores."""
    if not _has_conflicting_scores(rec_a, rec_b):
        return False

    if days_diff > 0:
        return True

    return time_diff_minutes is not None and time_diff_minutes > near_tolerance_min


def _is_same_source_distinct(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
    days_diff: int,
) -> bool:
    """Check if records are distinct fixtures originating from the same source."""
    if rec_a.source_code != rec_b.source_code:
        return False

    if _has_differing_source_game_ids(rec_a, rec_b):
        return True

    return days_diff > 0


def _is_candidate_prefiltered(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
    days_diff: int,
    time_diff_minutes: int | None,
    near_tolerance_min: int,
) -> bool:
    """Check if candidate pair is disqualified by date, score, or source."""
    if _is_distinct_by_date_or_score(
        rec_a,
        rec_b,
        days_diff,
        time_diff_minutes,
        near_tolerance_min,
    ):
        return True

    return _is_same_source_distinct(rec_a, rec_b, days_diff)


def _is_adjacent_day_rollover(
    days_diff: int,
    time_diff_minutes: int | None,
    tolerance_minutes: int,
) -> bool:
    """Check if adjacent day difference is a valid midnight rollover."""
    if days_diff != 1:
        return False

    if time_diff_minutes is None:
        return False

    return time_diff_minutes <= tolerance_minutes


def _is_identical_id_match(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
    days_diff: int,
    time_diff_minutes: int | None,
    near_tolerance_min: int,
) -> bool:
    """Check if records match via identical non-null game IDs."""
    if not _has_identical_game_ids(rec_a, rec_b):
        return False

    if days_diff == 0:
        return True

    return _is_adjacent_day_rollover(
        days_diff,
        time_diff_minutes,
        near_tolerance_min,
    )


def _is_team_compatible(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
    opp_sim: float,
    opp_thresh: float,
) -> bool:
    """Check if opponent similarity and home/away designations match."""
    return opp_sim >= opp_thresh and rec_a.is_home == rec_b.is_home


def _is_temporal_match(
    days_diff: int,
    *,
    time_aligned: bool,
    is_cross_source: bool,
    time_diff_minutes: int | None = None,
    near_tolerance_min: int = DEFAULT_NEAR_TOLERANCE_MINUTES,
) -> bool:
    """Evaluate temporal alignment between candidate records."""
    if not time_aligned:
        return False

    if days_diff == 0:
        return True

    if is_cross_source:
        return _is_adjacent_day_rollover(
            days_diff,
            time_diff_minutes,
            near_tolerance_min,
        )

    return False


def _check_record_match_criteria(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
    opp_sim: float,
    opp_thresh: float,
    *,
    time_aligned: bool,
    days_diff: int,
    time_diff_minutes: int | None = None,
    near_tolerance_min: int = DEFAULT_NEAR_TOLERANCE_MINUTES,
) -> bool:
    """Evaluate match criteria between two source records."""
    if _is_candidate_prefiltered(
        rec_a,
        rec_b,
        days_diff,
        time_diff_minutes,
        near_tolerance_min,
    ):
        return False

    if _is_identical_id_match(
        rec_a,
        rec_b,
        days_diff,
        time_diff_minutes,
        near_tolerance_min,
    ):
        return True

    if not _is_team_compatible(rec_a, rec_b, opp_sim, opp_thresh):
        return False

    return _is_temporal_match(
        days_diff,
        time_aligned=time_aligned,
        is_cross_source=rec_a.source_code != rec_b.source_code,
        time_diff_minutes=time_diff_minutes,
        near_tolerance_min=near_tolerance_min,
    )


def _resolve_pairwise_severity(
    src_a: str,
    src_b: str,
    priority: SourcePriority,
    *,
    is_home: bool = True,
) -> ConflictSeverity:
    """Determine conflict severity based on participating source tiers."""
    is_high = _is_high_tier_source(
        src_a,
        priority,
        is_home=is_home,
    ) and _is_high_tier_source(
        src_b,
        priority,
        is_home=is_home,
    )
    return ConflictSeverity.HIGH if is_high else ConflictSeverity.MEDIUM


def _are_both_venues_specified(v_a: str, v_b: str) -> bool:
    """Check that neither venue is unspecified or TBD."""
    return not (is_venue_unspecified(v_a) or is_venue_unspecified(v_b))


def _build_status_discrepancy(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
    priority: SourcePriority,
) -> DiscrepancyRecord | None:
    """Check and construct status discrepancy between two records."""
    if rec_a.status == rec_b.status:
        return None

    sev = _resolve_pairwise_severity(
        rec_a.source_type.value,
        rec_b.source_type.value,
        priority,
        is_home=rec_a.is_home,
    )
    return DiscrepancyRecord(
        field=ConflictField.STATUS,
        source_a=rec_a.source_code,
        source_b=rec_b.source_code,
        value_a=rec_a.status.value,
        value_b=rec_b.status.value,
        severity=sev,
        notes=f"Conflicting status: {rec_a.status.value} vs {rec_b.status.value}",
    )


def _build_venue_discrepancy(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
    venue_thresh: float,
    priority: SourcePriority,
) -> DiscrepancyRecord | None:
    """Check and construct venue discrepancy if both venues are specified."""
    if not _are_both_venues_specified(rec_a.venue, rec_b.venue):
        return None

    if is_venue_match(rec_a.venue, rec_b.venue, venue_thresh):
        return None

    sev = _resolve_pairwise_severity(
        rec_a.source_type.value,
        rec_b.source_type.value,
        priority,
        is_home=rec_a.is_home,
    )
    return DiscrepancyRecord(
        field=ConflictField.VENUE,
        source_a=rec_a.source_code,
        source_b=rec_b.source_code,
        value_a=rec_a.venue,
        value_b=rec_b.venue,
        severity=sev,
        notes=f"Conflicting venues: '{rec_a.venue}' vs '{rec_b.venue}'",
    )


def _build_time_discrepancy(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
    rel: TimingRelationship,
    diff_min: int | None,
    priority: SourcePriority,
) -> DiscrepancyRecord | None:
    """Check and construct start time discrepancy when times significantly differ."""
    if rel != TimingRelationship.TIME_DISCREPANCY or diff_min is None:
        return None

    sev = _resolve_pairwise_severity(
        rec_a.source_type.value,
        rec_b.source_type.value,
        priority,
        is_home=rec_a.is_home,
    )
    return DiscrepancyRecord(
        field=ConflictField.START_TIME,
        source_a=rec_a.source_code,
        source_b=rec_b.source_code,
        value_a=rec_a.start_time.isoformat(),
        value_b=rec_b.start_time.isoformat(),
        severity=sev,
        notes=f"Start times differ by {diff_min} minutes",
    )


def _build_date_discrepancy(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
    days_diff: int,
    priority: SourcePriority,
    tz_name: str,
) -> DiscrepancyRecord | None:
    """Check and construct date discrepancy for adjacent or differing dates."""
    if days_diff == 0:
        return None

    d_a = to_local_date(rec_a.start_time, tz_name)
    d_b = to_local_date(rec_b.start_time, tz_name)
    sev = _resolve_pairwise_severity(
        rec_a.source_type.value,
        rec_b.source_type.value,
        priority,
        is_home=rec_a.is_home,
    )
    return DiscrepancyRecord(
        field=ConflictField.DATE,
        source_a=rec_a.source_code,
        source_b=rec_b.source_code,
        value_a=str(d_a),
        value_b=str(d_b),
        severity=sev,
        notes=f"Game scheduled on different dates ({d_a} vs {d_b})",
    )


def _build_home_away_discrepancy(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
) -> DiscrepancyRecord | None:
    """Check and construct home/away alignment discrepancy."""
    if rec_a.is_home == rec_b.is_home:
        return None

    return DiscrepancyRecord(
        field=ConflictField.HOME_AWAY,
        source_a=rec_a.source_code,
        source_b=rec_b.source_code,
        value_a=f"Home={rec_a.is_home}",
        value_b=f"Home={rec_b.is_home}",
        severity=ConflictSeverity.HIGH,
        notes="Home/away designation mismatch between sources",
    )


def _build_score_discrepancy(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
) -> DiscrepancyRecord | None:
    """Check and construct final score discrepancy if both records have scores."""
    if not _has_conflicting_scores(rec_a, rec_b):
        return None

    return DiscrepancyRecord(
        field=ConflictField.HOME_SCORE,
        source_a=rec_a.source_code,
        source_b=rec_b.source_code,
        value_a=f"{rec_a.home_score}-{rec_a.away_score}",
        value_b=f"{rec_b.home_score}-{rec_b.away_score}",
        severity=ConflictSeverity.MEDIUM,
        notes="Conflicting game scores recorded",
    )


def _collect_pairwise_discrepancies(
    rec_a: SourceGameRecord,
    rec_b: SourceGameRecord,
    priority: SourcePriority,
    *,
    venue_thresh: float,
    tz_name: str,
    exact_tol: int,
    near_tol: int,
) -> list[DiscrepancyRecord]:
    """Inspect all field pairs between two matching records for discrepancies."""
    t_res = align_game_datetimes(
        rec_a.start_time,
        rec_b.start_time,
        a_tbd=rec_a.is_time_tbd,
        b_tbd=rec_b.is_time_tbd,
        exact_tolerance_min=exact_tol,
        near_tolerance_min=near_tol,
        tz_name=tz_name,
    )

    candidates = (
        _build_date_discrepancy(
            rec_a,
            rec_b,
            t_res.date_difference_days,
            priority,
            tz_name,
        ),
        _build_time_discrepancy(
            rec_a,
            rec_b,
            t_res.relationship,
            t_res.time_difference_minutes,
            priority,
        ),
        _build_venue_discrepancy(rec_a, rec_b, venue_thresh, priority),
        _build_status_discrepancy(rec_a, rec_b, priority),
        _build_home_away_discrepancy(rec_a, rec_b),
        _build_score_discrepancy(rec_a, rec_b),
    )
    return [d for d in candidates if d is not None]


def _build_conflict_from_discrepancies(
    c_field: ConflictField,
    d_list: list[DiscrepancyRecord],
    game_key: str,
) -> DetectedConflict:
    """Create a DetectedConflict from a list of field discrepancies."""
    has_high = any(d.severity == ConflictSeverity.HIGH for d in d_list)
    return DetectedConflict(
        conflict_id=str(uuid4())[:8],
        game_key=game_key,
        field=c_field,
        discrepancies=d_list,
        severity=ConflictSeverity.HIGH if has_high else ConflictSeverity.MEDIUM,
        requires_review=has_high,
        notes=f"Discrepancy detected across {len(d_list)} source comparisons",
    )


def _mark_conflicts_resolved(
    conflicts: list[DetectedConflict],
    provenance: dict[str, str],
    default_source: str,
) -> None:
    """Mark all detected conflicts as resolved with source attribution."""
    for conf in conflicts:
        conf.resolved = True
        conf.resolved_by_source = provenance.get(conf.field.value, default_source)


def _determine_reconciliation_status(
    *,
    has_conflicts: bool,
    requires_review: bool,
) -> ReconciliationStatus:
    """Determine final operational status for reconciled game."""
    if not has_conflicts:
        return ReconciliationStatus.UNRESOLVED

    return (
        ReconciliationStatus.FLAGGED_FOR_REVIEW
        if requires_review
        else ReconciliationStatus.AUTO_RESOLVED
    )


def _find_primary_game_id(records: Sequence[SourceGameRecord]) -> str | None:
    """Find explicit game identifier from primary source of truth records."""
    for r in records:
        if r.source_type == DataSourceType.PRIMARY_SOT and r.game_id is not None:
            return r.game_id

    return None


def _find_any_game_id(records: Sequence[SourceGameRecord]) -> str | None:
    """Find first explicit game identifier from candidate records."""
    for r in records:
        if r.game_id is not None:
            return r.game_id

    return None


def _resolve_game_identity(
    record: SourceGameRecord,
    start_time: datetime,
    tz_name: str,
    *,
    fallback_records: Sequence[SourceGameRecord] | None = None,
) -> str:
    """Return explicit game_id or generate canonical ID."""
    records = list(fallback_records or [])
    primary_id = _find_primary_game_id(records)
    if primary_id is not None:
        return primary_id

    if record.game_id is not None:
        return record.game_id

    any_id = _find_any_game_id(records)
    if any_id is not None:
        return any_id

    return _generate_canonical_game_id(
        record.opponent_name,
        start_time,
        is_home=record.is_home,
        tz_name=tz_name,
    )


def _compute_cluster_confidence(cluster: Sequence[SourceGameRecord]) -> float:
    """Compute average confidence score across cluster records."""
    total = sum(r.confidence_score for r in cluster)
    return total / len(cluster)


def _has_review_requirement(conflicts: Sequence[DetectedConflict]) -> bool:
    """Check if any conflict in the sequence requires admin review."""
    return any(c.requires_review for c in conflicts)


def _build_initial_provenance(top: SourceGameRecord) -> dict[str, str]:
    """Create initial provenance mapping from the top source record."""
    return {
        "opponent_name": top.source_code,
        "is_home": top.source_code,
    }


def _compute_source_weight(
    record: SourceGameRecord,
    priority: SourcePriority,
    *,
    is_home: bool,
) -> int:
    """Compute numeric weight for a source record (higher is better)."""
    tier = priority.get_tier(record.source_type.value, is_home=is_home)
    return max(1, 5 - tier)


def _score_candidate_group(
    group: list[SourceGameRecord],
    priority: SourcePriority,
    *,
    is_home: bool,
) -> tuple[int, int, int, int]:
    """Score candidate group by count, weight, tier, and tiebreaker."""
    tie_breakers = priority.tie_breakers if is_home else priority.away_tie_breakers
    count = len(group)
    total_weight = sum(
        _compute_source_weight(r, priority, is_home=is_home) for r in group
    )
    best_tier = min(
        priority.get_tier(r.source_type.value, is_home=is_home) for r in group
    )
    best_tb = min(
        lookup_tiebreaker_order(
            normalize_source_key(r.source_type.value),
            tie_breakers,
        )
        for r in group
    )
    return count, total_weight, -best_tier, -best_tb


def _find_matching_time_group(
    rec: SourceGameRecord,
    groups: list[list[SourceGameRecord]],
    exact_tolerance_min: int,
) -> list[SourceGameRecord] | None:
    """Find first existing time group matching the candidate within tolerance."""
    for grp in groups:
        diff_min = abs((rec.start_time - grp[0].start_time).total_seconds()) / 60
        if diff_min <= exact_tolerance_min:
            return grp

    return None


def _group_time_candidates(
    records: Sequence[SourceGameRecord],
    exact_tolerance_min: int,
) -> list[list[SourceGameRecord]]:
    """Group non-TBD records by start time within exact tolerance."""
    groups: list[list[SourceGameRecord]] = []
    for rec in records:
        target = _find_matching_time_group(rec, groups, exact_tolerance_min)
        if target is not None:
            target.append(rec)
        else:
            groups.append([rec])

    return groups


def _find_matching_venue_group(
    rec: SourceGameRecord,
    groups: list[list[SourceGameRecord]],
    venue_threshold: float,
) -> list[SourceGameRecord] | None:
    """Find first existing venue group compatible with the candidate."""
    for grp in groups:
        if is_venue_match(rec.venue, grp[0].venue, threshold=venue_threshold):
            return grp

    return None


def _group_venue_candidates(
    records: Sequence[SourceGameRecord],
    venue_threshold: float,
) -> list[list[SourceGameRecord]]:
    """Group records with specified venues by compatibility."""
    groups: list[list[SourceGameRecord]] = []
    for rec in records:
        target = _find_matching_venue_group(rec, groups, venue_threshold)
        if target is not None:
            target.append(rec)
        else:
            groups.append([rec])

    return groups


class ReconciliationEngine:
    """Core multi-source schedule reconciliation and conflict resolution engine."""

    def _select_sorted_candidates(
        self,
        cluster: Sequence[SourceGameRecord],
        *,
        is_home: bool = True,
    ) -> list[SourceGameRecord]:
        """Sort cluster records by source priority hierarchy."""
        tie_breakers = (
            self.priority.tie_breakers if is_home else self.priority.away_tie_breakers
        )
        return sorted(
            cluster,
            key=lambda r: (
                self.priority.get_tier(r.source_type.value, is_home=is_home),
                lookup_tiebreaker_order(
                    normalize_source_key(r.source_type.value),
                    tie_breakers,
                ),
                r.is_time_tbd,
                is_venue_unspecified(r.venue),
            ),
        )

    # Alias for internal use
    select_sorted_candidates = _select_sorted_candidates

    def __init__(
        self,
        priority: SourcePriority | None = None,
        *,
        exact_tolerance_min: int = DEFAULT_EXACT_TOLERANCE_MINUTES,
        near_tolerance_min: int = DEFAULT_NEAR_TOLERANCE_MINUTES,
        opponent_similarity_threshold: float = DEFAULT_OPPONENT_MATCH_THRESHOLD,
        venue_similarity_threshold: float = DEFAULT_VENUE_MATCH_THRESHOLD,
        tz_name: str = DEFAULT_TIMEZONE,
    ) -> None:
        """Initialize reconciliation engine with configuration options.

        Args:
            priority: Configurable source precedence hierarchy.
            exact_tolerance_min: Minute threshold for exact start time match.
            near_tolerance_min: Minute threshold for near start time match.
            opponent_similarity_threshold: Fuzzy matching threshold for opponents.
            venue_similarity_threshold: Fuzzy matching threshold for venues.
            tz_name: Target local timezone identifier.
        """
        self.priority = priority or SourcePriority()
        self.exact_tolerance_min = exact_tolerance_min
        self.near_tolerance_min = near_tolerance_min
        self.opponent_similarity_threshold = opponent_similarity_threshold
        self.venue_similarity_threshold = venue_similarity_threshold
        self.tz_name = tz_name

    def match_records(
        self,
        rec_a: SourceGameRecord,
        rec_b: SourceGameRecord,
    ) -> tuple[bool, float, list[DiscrepancyRecord]]:
        """Evaluate whether two records refer to the same game event.

        Args:
            rec_a: First source record.
            rec_b: Second source record.

        Returns:
            Tuple of (is_match, confidence_score, discrepancies_list).
        """
        opp_sim = compute_opponent_similarity(rec_a.opponent_name, rec_b.opponent_name)
        t_res = align_game_datetimes(
            rec_a.start_time,
            rec_b.start_time,
            a_tbd=rec_a.is_time_tbd,
            b_tbd=rec_b.is_time_tbd,
            exact_tolerance_min=self.exact_tolerance_min,
            near_tolerance_min=self.near_tolerance_min,
            tz_name=self.tz_name,
        )

        is_match = _check_record_match_criteria(
            rec_a,
            rec_b,
            opp_sim,
            self.opponent_similarity_threshold,
            time_aligned=t_res.aligned,
            days_diff=t_res.date_difference_days,
            time_diff_minutes=t_res.time_difference_minutes,
            near_tolerance_min=self.near_tolerance_min,
        )
        if not is_match:
            return False, 0.0, []

        discs = _collect_pairwise_discrepancies(
            rec_a,
            rec_b,
            self.priority,
            venue_thresh=self.venue_similarity_threshold,
            tz_name=self.tz_name,
            exact_tol=self.exact_tolerance_min,
            near_tol=self.near_tolerance_min,
        )
        confidence = float(opp_sim * t_res.confidence_factor)
        return True, confidence, discs

    def cluster_records(
        self,
        records: Sequence[SourceGameRecord],
    ) -> list[list[SourceGameRecord]]:
        """Partition source records into clusters representing unique games.

        Args:
            records: Sequence of input source game records.

        Returns:
            List of game record clusters.
        """
        clusters: list[list[SourceGameRecord]] = []
        for record in records:
            matched_cluster: list[SourceGameRecord] | None = None
            for cluster in clusters:
                is_same, _, _ = self.match_records(record, cluster[0])
                if is_same:
                    matched_cluster = cluster
                    break

            if matched_cluster is not None:
                matched_cluster.append(record)
            else:
                clusters.append([record])

        return clusters

    def _gather_cluster_discrepancies(
        self,
        cluster: Sequence[SourceGameRecord],
    ) -> dict[ConflictField, list[DiscrepancyRecord]]:
        """Collect discrepancies across all pairs in a cluster."""
        all_discs: dict[ConflictField, list[DiscrepancyRecord]] = {}
        for rec_a, rec_b in combinations(cluster, 2):
            _, _, discs = self.match_records(rec_a, rec_b)
            for d in discs:
                all_discs.setdefault(d.field, []).append(d)

        return all_discs

    def detect_conflicts(
        self,
        cluster: Sequence[SourceGameRecord],
        game_key: str,
    ) -> list[DetectedConflict]:
        """Aggregate pairwise discrepancies across a cluster into detected conflicts.

        Args:
            cluster: Cluster of matching records for a single game.
            game_key: Identifier key for the game.

        Returns:
            List of DetectedConflict objects.
        """
        all_discs = self._gather_cluster_discrepancies(cluster)
        return [
            _build_conflict_from_discrepancies(c_field, d_list, game_key)
            for c_field, d_list in all_discs.items()
        ]

    def _resolve_time_fields(
        self,
        sorted_records: Sequence[SourceGameRecord],
        provenance: dict[str, str],
        *,
        is_home: bool = True,
    ) -> tuple[datetime, datetime | None, bool]:
        """Select start time, end time, and TBD flag via consensus and priority."""
        valid_records = [r for r in sorted_records if not r.is_time_tbd]
        if not valid_records:
            fallback = sorted_records[0]
            provenance["start_time"] = fallback.source_code
            provenance["is_time_tbd"] = fallback.source_code
            return fallback.start_time, fallback.end_time, fallback.is_time_tbd

        groups = _group_time_candidates(valid_records, self.exact_tolerance_min)
        groups.sort(
            key=lambda grp: _score_candidate_group(grp, self.priority, is_home=is_home),
            reverse=True,
        )
        time_winner = groups[0][0]
        provenance["start_time"] = time_winner.source_code
        provenance["is_time_tbd"] = time_winner.source_code
        return time_winner.start_time, time_winner.end_time, time_winner.is_time_tbd

    def _resolve_venue_field(
        self,
        sorted_records: Sequence[SourceGameRecord],
        provenance: dict[str, str],
        *,
        is_home: bool = True,
    ) -> str:
        """Select canonical venue string by consensus and source priority."""
        valid_records = [r for r in sorted_records if not is_venue_unspecified(r.venue)]
        if not valid_records:
            fallback = sorted_records[0]
            provenance["venue"] = fallback.source_code
            return fallback.venue

        groups = _group_venue_candidates(valid_records, self.venue_similarity_threshold)
        groups.sort(
            key=lambda grp: _score_candidate_group(grp, self.priority, is_home=is_home),
            reverse=True,
        )
        venue_winner = groups[0][0]
        provenance["venue"] = venue_winner.source_code
        return resolve_canonical_venue(venue_winner.venue)

    def _resolve_status_field(
        self,
        sorted_records: Sequence[SourceGameRecord],
        provenance: dict[str, str],
        *,
        is_home: bool = True,
    ) -> GameStatus:
        """Select canonical operational status."""
        for r in sorted_records:
            if r.status in {
                GameStatus.CANCELLED,
                GameStatus.POSTPONED,
            } and _is_high_tier_source(
                r.source_type.value,
                self.priority,
                is_home=is_home,
            ):
                provenance["status"] = r.source_code
                return r.status

        top = sorted_records[0]
        provenance["status"] = top.source_code
        return top.status

    def _resolve_scores_and_result(
        self,
        sorted_records: Sequence[SourceGameRecord],
        provenance: dict[str, str],
    ) -> tuple[Any, int | None, int | None]:
        """Select canonical game outcome and scores."""
        score_winner = sorted_records[0]
        for r in sorted_records:
            if r.home_score is not None and r.away_score is not None:
                score_winner = r
                break

        provenance["result"] = score_winner.source_code
        provenance["home_score"] = score_winner.source_code
        provenance["away_score"] = score_winner.source_code
        return score_winner.result, score_winner.home_score, score_winner.away_score

    def _extract_cluster_fields(
        self,
        sorted_records: Sequence[SourceGameRecord],
        provenance: dict[str, str],
        *,
        is_home: bool = True,
    ) -> dict[str, Any]:
        """Resolve all field values and populate provenance tracking."""
        st, et, tbd = self._resolve_time_fields(
            sorted_records,
            provenance,
            is_home=is_home,
        )
        venue = self._resolve_venue_field(
            sorted_records,
            provenance,
            is_home=is_home,
        )
        status = self._resolve_status_field(
            sorted_records,
            provenance,
            is_home=is_home,
        )
        res, hs, ascore = self._resolve_scores_and_result(sorted_records, provenance)
        if status in {GameStatus.SCHEDULED, GameStatus.CANCELLED, GameStatus.POSTPONED}:
            if status == GameStatus.CANCELLED:
                res = GameResult.CANCELLED
            elif status == GameStatus.POSTPONED:
                res = GameResult.POSTPONED
            else:
                res = GameResult.SCHEDULED

            hs = None
            ascore = None

        return {
            "start_time": st,
            "end_time": et,
            "is_time_tbd": tbd,
            "venue": venue,
            "status": status,
            "result": res,
            "home_score": hs,
            "away_score": ascore,
        }

    @staticmethod
    def _resolve_cluster_logo(
        records: Sequence[SourceGameRecord],
    ) -> str | None:
        """Find first available opponent logo from sorted records."""
        for r in records:
            if r.opponent_logo_url:
                return r.opponent_logo_url

        return None

    def resolve_cluster(
        self,
        cluster: Sequence[SourceGameRecord],
    ) -> ReconciledGame:
        """Merge a cluster of source records into a canonical ReconciledGame.

        Args:
            cluster: Sequence of matched source records for a single game.

        Returns:
            ReconciledGame instance with provenance and resolved conflicts.
        """
        is_home = cluster[0].is_home if cluster else True
        sorted_recs = self.select_sorted_candidates(cluster, is_home=is_home)
        top = sorted_recs[0]

        temp_id = _resolve_game_identity(
            top,
            top.start_time,
            self.tz_name,
            fallback_records=cluster,
        )
        conflicts = self.detect_conflicts(cluster, temp_id)

        provenance = _build_initial_provenance(top)
        f_vals = self._extract_cluster_fields(
            sorted_recs,
            provenance,
            is_home=is_home,
        )

        canonical_id = _resolve_game_identity(
            top,
            f_vals["start_time"],
            self.tz_name,
            fallback_records=cluster,
        )
        requires_review = _has_review_requirement(conflicts)
        _mark_conflicts_resolved(conflicts, provenance, top.source_code)
        rec_status = _determine_reconciliation_status(
            has_conflicts=bool(conflicts),
            requires_review=requires_review,
        )

        return ReconciledGame(
            canonical_game_id=canonical_id,
            opponent_name=top.opponent_name,
            start_time=f_vals["start_time"],
            venue=f_vals["venue"],
            is_home=top.is_home,
            is_time_tbd=f_vals["is_time_tbd"],
            end_time=f_vals["end_time"],
            status=f_vals["status"],
            result=f_vals["result"],
            home_score=f_vals["home_score"],
            away_score=f_vals["away_score"],
            contributing_sources=[r.source_code for r in cluster],
            field_provenance=provenance,
            status_reconciliation=rec_status,
            conflicts=conflicts,
            requires_admin_review=requires_review,
            confidence_score=_compute_cluster_confidence(cluster),
            opponent_logo_url=self._resolve_cluster_logo(sorted_recs),
        )

    def reconcile_games(
        self,
        records: Sequence[SourceGameRecord],
        cycle_id: str | None = None,
    ) -> ReconciliationCycleResult:
        """Execute end-to-end reconciliation cycle across all input records.

        Args:
            records: Sequence of input source game records.
            cycle_id: Optional tracking identifier for this cycle.

        Returns:
            ReconciliationCycleResult summary with reconciled games.
        """
        cid = cycle_id or str(uuid4())[:12]
        started = datetime.now(UTC)

        clusters = self.cluster_records(records)
        reconciled: list[ReconciledGame] = []
        total_conflicts = 0
        auto_resolved = 0
        flagged = 0

        for cluster in clusters:
            rec_game = self.resolve_cluster(cluster)
            reconciled.append(rec_game)
            c_count = len(rec_game.conflicts)
            total_conflicts += c_count
            if rec_game.requires_admin_review:
                flagged += c_count
            else:
                auto_resolved += c_count

        completed = datetime.now(UTC)
        return ReconciliationCycleResult(
            cycle_id=cid,
            total_source_records=len(records),
            reconciled_games=reconciled,
            total_conflicts_detected=total_conflicts,
            auto_resolved_conflicts=auto_resolved,
            flagged_conflicts=flagged,
            unmatched_records=[],
            started_at=started,
            completed_at=completed,
        )


__all__ = [
    "CANONICAL_ECU_NAME",
    "CANONICAL_SEASON",
    "ReconciliationEngine",
]

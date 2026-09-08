"""Change detection and schedule state transition tracking engine.

This module compares game schedules between reconciliation cycles, generates
granular field-level diffs, and classifies atomic state transitions:
CREATED, UPDATED, DELETED, CONFLICT_DETECTED, and UNCHANGED.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from ecu_hockey_calendar.reconciliation.date_aligner import (
    DEFAULT_TIMEZONE,
    to_local_date,
    to_local_datetime,
)
from ecu_hockey_calendar.reconciliation.fuzzy_matcher import (
    DEFAULT_OPPONENT_MATCH_THRESHOLD,
    compute_opponent_similarity,
)
from ecu_hockey_calendar.reconciliation.models import (
    ChangeDetectionCycleResult,
    FieldDiff,
    GameChangeRecord,
    GameStateTransition,
    ReconciledGame,
)
from ecu_hockey_calendar.storage.models import GameModel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ecu_hockey_calendar.models import GameResult

CANONICAL_CHANGE_CYCLE_PREFIX = "sync-change-"


def _format_time_str(dt: datetime, tz_name: str, *, include_tz: bool = False) -> str:
    """Format a datetime into human-friendly time string."""
    loc = to_local_datetime(dt, tz_name)
    fmt = "%I:%M %p %Z" if include_tz else "%I:%M %p"
    return loc.strftime(fmt).lstrip("0")


def _describe_time_change(old_dt: datetime, new_dt: datetime, tz_name: str) -> str:
    """Build human-readable description for game start time changes."""
    old_loc = to_local_datetime(old_dt, tz_name)
    new_loc = to_local_datetime(new_dt, tz_name)

    if old_loc.date() == new_loc.date():
        old_time = _format_time_str(old_dt, tz_name, include_tz=False)
        new_time = _format_time_str(new_dt, tz_name, include_tz=True)
        return (
            f"Start time moved from {old_time} to {new_time} "
            f"({old_loc.strftime('%Y-%m-%d')})"
        )

    old_full = old_loc.strftime("%Y-%m-%d %I:%M %p").replace(" 0", " ")
    new_full = new_loc.strftime("%Y-%m-%d %I:%M %p %Z").replace(" 0", " ")
    return f"Game rescheduled from {old_full} to {new_full}"


def _describe_end_time_change(
    old_dt: datetime | None,
    new_dt: datetime | None,
    tz_name: str,
) -> str:
    """Build human-readable description for game end time changes."""
    old_str = _format_time_str(old_dt, tz_name, include_tz=True) if old_dt else "None"
    new_str = _format_time_str(new_dt, tz_name, include_tz=True) if new_dt else "None"
    return f"End time changed from {old_str} to {new_str}"


def _describe_score_change(
    team_side: str,
    old_val: int | None,
    new_val: int | None,
) -> str:
    """Build human-readable description for score updates."""
    old_s = str(old_val) if old_val is not None else "None"
    new_s = str(new_val) if new_val is not None else "None"
    return f"{team_side} score updated from {old_s} to {new_s}"


def _check_temporal_diffs(
    old_g: ReconciledGame,
    new_g: ReconciledGame,
    tz_name: str,
) -> list[FieldDiff]:
    """Check start and end time differences between games."""
    diffs: list[FieldDiff] = []
    if old_g.start_time != new_g.start_time:
        diffs.append(
            FieldDiff(
                field_name="start_time",
                old_value=old_g.start_time.isoformat(),
                new_value=new_g.start_time.isoformat(),
                human_description=_describe_time_change(
                    old_g.start_time,
                    new_g.start_time,
                    tz_name,
                ),
            ),
        )

    if old_g.end_time != new_g.end_time:
        diffs.append(
            FieldDiff(
                field_name="end_time",
                old_value=(old_g.end_time.isoformat() if old_g.end_time else None),
                new_value=(new_g.end_time.isoformat() if new_g.end_time else None),
                human_description=_describe_end_time_change(
                    old_g.end_time,
                    new_g.end_time,
                    tz_name,
                ),
            ),
        )

    return diffs


def _check_venue_and_status(
    old_g: ReconciledGame,
    new_g: ReconciledGame,
) -> list[FieldDiff]:
    """Check venue and status changes between games."""
    diffs: list[FieldDiff] = []
    if old_g.venue != new_g.venue:
        diffs.append(
            FieldDiff(
                field_name="venue",
                old_value=old_g.venue,
                new_value=new_g.venue,
                human_description=(
                    f"Venue changed from '{old_g.venue}' to '{new_g.venue}'"
                ),
            ),
        )

    if old_g.status != new_g.status:
        st_desc = (
            f"Game status changed from {old_g.status.value} to {new_g.status.value}"
        )
        diffs.append(
            FieldDiff(
                field_name="status",
                old_value=old_g.status.value,
                new_value=new_g.status.value,
                human_description=st_desc,
            ),
        )

    return diffs


def _check_opponent_and_location(
    old_g: ReconciledGame,
    new_g: ReconciledGame,
) -> list[FieldDiff]:
    """Check opponent name and home/away location changes."""
    diffs: list[FieldDiff] = []
    if old_g.opponent_name != new_g.opponent_name:
        diffs.append(
            FieldDiff(
                field_name="opponent_name",
                old_value=old_g.opponent_name,
                new_value=new_g.opponent_name,
                human_description=(
                    f"Opponent name updated from '{old_g.opponent_name}' to "
                    f"'{new_g.opponent_name}'"
                ),
            ),
        )

    if old_g.is_home != new_g.is_home:
        old_h = "Home" if old_g.is_home else "Away"
        new_h = "Home" if new_g.is_home else "Away"
        diffs.append(
            FieldDiff(
                field_name="is_home",
                old_value=old_g.is_home,
                new_value=new_g.is_home,
                human_description=f"Location changed from {old_h} to {new_h}",
            ),
        )

    return diffs


def _check_attribute_diffs(
    old_g: ReconciledGame,
    new_g: ReconciledGame,
) -> list[FieldDiff]:
    """Check venue, status, opponent, and home/away differences."""
    diffs: list[FieldDiff] = []
    diffs.extend(_check_venue_and_status(old_g, new_g))
    diffs.extend(_check_opponent_and_location(old_g, new_g))
    return diffs


def _extract_result_val(res: GameResult | None) -> str | None:
    """Extract string value from GameResult or return None."""
    return res.value if res else None


def _check_result_diff(
    old_g: ReconciledGame,
    new_g: ReconciledGame,
) -> FieldDiff | None:
    """Check game result differences."""
    if old_g.result == new_g.result:
        return None

    old_r = _extract_result_val(old_g.result)
    new_r = _extract_result_val(new_g.result)
    return FieldDiff(
        field_name="result",
        old_value=old_r,
        new_value=new_r,
        human_description=(
            f"Game result changed from {old_r or 'None'} to {new_r or 'None'}"
        ),
    )


def _check_score_diffs(
    old_g: ReconciledGame,
    new_g: ReconciledGame,
) -> list[FieldDiff]:
    """Check home and away score differences."""
    diffs: list[FieldDiff] = []
    if old_g.home_score != new_g.home_score:
        diffs.append(
            FieldDiff(
                field_name="home_score",
                old_value=old_g.home_score,
                new_value=new_g.home_score,
                human_description=_describe_score_change(
                    "Home",
                    old_g.home_score,
                    new_g.home_score,
                ),
            ),
        )

    if old_g.away_score != new_g.away_score:
        diffs.append(
            FieldDiff(
                field_name="away_score",
                old_value=old_g.away_score,
                new_value=new_g.away_score,
                human_description=_describe_score_change(
                    "Away",
                    old_g.away_score,
                    new_g.away_score,
                ),
            ),
        )

    return diffs


def _check_outcome_diffs(
    old_g: ReconciledGame,
    new_g: ReconciledGame,
) -> list[FieldDiff]:
    """Check game result and score differences."""
    diffs: list[FieldDiff] = []
    res_diff = _check_result_diff(old_g, new_g)
    if res_diff:
        diffs.append(res_diff)

    diffs.extend(_check_score_diffs(old_g, new_g))
    return diffs


def _format_game_date(game: ReconciledGame, tz_name: str) -> str:
    """Format local calendar date string for a game."""
    return to_local_date(game.start_time, tz_name).strftime("%Y-%m-%d")


def _format_created_summary(game: ReconciledGame, date_str: str) -> str:
    """Format summary for newly created game."""
    return f"New game scheduled vs {game.opponent_name} on {date_str} at {game.venue}"


def _format_deleted_summary(game: ReconciledGame, date_str: str) -> str:
    """Format summary for deleted game."""
    return f"Game vs {game.opponent_name} on {date_str} removed from schedule"


def _format_conflict_summary(game: ReconciledGame, date_str: str) -> str:
    """Format summary for game with detected conflicts."""
    fields = ", ".join(c.field.value for c in game.conflicts)
    return (
        f"Conflict detected for game vs {game.opponent_name} on {date_str}: "
        f"fields=[{fields}]"
    )


def _format_updated_summary(
    game: ReconciledGame,
    date_str: str,
    diffs: list[FieldDiff],
) -> str:
    """Format summary for updated game with field diffs."""
    if not diffs:
        return f"Game vs {game.opponent_name} on {date_str} updated"

    return "; ".join(d.human_description for d in diffs)


def _build_human_summary(
    transition: GameStateTransition,
    game: ReconciledGame,
    diffs: list[FieldDiff],
    tz_name: str,
) -> str:
    """Build human-friendly text summary for a state transition."""
    date_str = _format_game_date(game, tz_name)

    if transition == GameStateTransition.CREATED:
        return _format_created_summary(game, date_str)

    if transition == GameStateTransition.DELETED:
        return _format_deleted_summary(game, date_str)

    if transition == GameStateTransition.CONFLICT_DETECTED:
        return _format_conflict_summary(game, date_str)

    if transition == GameStateTransition.UPDATED:
        return _format_updated_summary(game, date_str, diffs)

    return f"No changes detected for game vs {game.opponent_name} on {date_str}"


def _normalize_previous_records(
    previous_games: Sequence[ReconciledGame | GameModel],
) -> list[ReconciledGame]:
    """Convert any GameModel instances to ReconciledGame representations."""
    normalized: list[ReconciledGame] = []
    for g in previous_games:
        if isinstance(g, GameModel):
            normalized.append(ReconciledGame.from_game_model(g))
        else:
            normalized.append(g)

    return normalized


def _find_best_fuzzy_match(
    curr: ReconciledGame,
    unmatched_prev: list[ReconciledGame],
    threshold: float,
) -> ReconciledGame | None:
    """Locate unmatched previous game matching opponent within threshold."""
    best_match: ReconciledGame | None = None
    best_sim = 0.0

    for prev in unmatched_prev:
        sim = compute_opponent_similarity(curr.opponent_name, prev.opponent_name)
        if sim >= threshold and sim > best_sim:
            best_sim = sim
            best_match = prev

    return best_match


def _match_exact_game_ids(
    prev_by_id: dict[str, ReconciledGame],
    curr_games: Sequence[ReconciledGame],
) -> tuple[
    list[tuple[ReconciledGame | None, ReconciledGame]],
    set[str],
    list[ReconciledGame],
]:
    """Match current games with previous games using exact canonical game ID."""
    paired: list[tuple[ReconciledGame | None, ReconciledGame]] = []
    matched_prev_ids: set[str] = set()
    unmatched_curr: list[ReconciledGame] = []

    for curr in curr_games:
        if curr.canonical_game_id in prev_by_id:
            prev = prev_by_id[curr.canonical_game_id]
            paired.append((prev, curr))
            matched_prev_ids.add(prev.canonical_game_id)
        else:
            unmatched_curr.append(curr)

    return paired, matched_prev_ids, unmatched_curr


def _match_fuzzy_unmatched(
    unmatched_curr: list[ReconciledGame],
    unmatched_prev: list[ReconciledGame],
    threshold: float,
) -> list[tuple[ReconciledGame | None, ReconciledGame]]:
    """Pair unmatched current games with previous games using fuzzy matching."""
    fuzzy_paired: list[tuple[ReconciledGame | None, ReconciledGame]] = []
    for curr in unmatched_curr:
        match = _find_best_fuzzy_match(curr, unmatched_prev, threshold)
        if match:
            fuzzy_paired.append((match, curr))
            unmatched_prev.remove(match)
        else:
            fuzzy_paired.append((None, curr))

    return fuzzy_paired


class ChangeDetector:
    """Engine to detect schedule diffs and atomic transitions across sync cycles."""

    def __init__(
        self,
        tz_name: str = DEFAULT_TIMEZONE,
        opponent_match_threshold: float = DEFAULT_OPPONENT_MATCH_THRESHOLD,
    ) -> None:
        """Initialize ChangeDetector with timezone and matching configuration.

        Args:
            tz_name: Target timezone string for local date formatting.
            opponent_match_threshold: Similarity score required for fuzzy matching.
        """
        self.tz_name = tz_name
        self.opponent_threshold = opponent_match_threshold

    def compute_field_diffs(
        self,
        old_game: ReconciledGame,
        new_game: ReconciledGame,
    ) -> list[FieldDiff]:
        """Compute all field-level differences between old and new game states.

        Args:
            old_game: Previous reconciled game state.
            new_game: Current reconciled game state.

        Returns:
            List of FieldDiff instances describing all detected changes.
        """
        diffs: list[FieldDiff] = []
        diffs.extend(_check_temporal_diffs(old_game, new_game, self.tz_name))
        diffs.extend(_check_attribute_diffs(old_game, new_game))
        diffs.extend(_check_outcome_diffs(old_game, new_game))
        return diffs

    def _determine_game_transition(
        self,
        prev_game: ReconciledGame | None,
        curr_game: ReconciledGame,
        diffs: list[FieldDiff],
    ) -> GameStateTransition:
        """Determine atomic transition state for a current game."""
        if curr_game.conflicts:
            return GameStateTransition.CONFLICT_DETECTED

        if prev_game is None:
            return GameStateTransition.CREATED

        if diffs:
            return GameStateTransition.UPDATED

        return GameStateTransition.UNCHANGED

    def _pair_games(
        self,
        prev_games: list[ReconciledGame],
        curr_games: Sequence[ReconciledGame],
    ) -> tuple[
        list[tuple[ReconciledGame | None, ReconciledGame]],
        list[ReconciledGame],
    ]:
        """Pair current games with previous games using exact and fuzzy matching."""
        prev_by_id = {g.canonical_game_id: g for g in prev_games}
        paired, matched_ids, unmatched_curr = _match_exact_game_ids(
            prev_by_id,
            curr_games,
        )
        unmatched_prev = [
            g for g in prev_games if g.canonical_game_id not in matched_ids
        ]
        fuzzy_paired = _match_fuzzy_unmatched(
            unmatched_curr,
            unmatched_prev,
            self.opponent_threshold,
        )
        paired.extend(fuzzy_paired)
        return paired, unmatched_prev

    def _build_paired_change_record(
        self,
        prev: ReconciledGame | None,
        curr: ReconciledGame,
    ) -> GameChangeRecord:
        """Construct GameChangeRecord for a paired current game."""
        diffs = self.compute_field_diffs(prev, curr) if prev else []
        transition = self._determine_game_transition(prev, curr, diffs)
        summary = _build_human_summary(transition, curr, diffs, self.tz_name)

        return GameChangeRecord(
            canonical_game_id=curr.canonical_game_id,
            state_transition=transition,
            field_diffs=diffs,
            previous_snapshot=prev.to_dict() if prev else None,
            current_snapshot=curr.to_dict(),
            detected_conflicts=list(curr.conflicts),
            human_summary=summary,
            recorded_at=datetime.now(UTC),
        )

    def _build_deleted_change_record(
        self,
        deleted: ReconciledGame,
    ) -> GameChangeRecord:
        """Construct GameChangeRecord for a deleted game."""
        summary = _build_human_summary(
            GameStateTransition.DELETED,
            deleted,
            [],
            self.tz_name,
        )
        return GameChangeRecord(
            canonical_game_id=deleted.canonical_game_id,
            state_transition=GameStateTransition.DELETED,
            field_diffs=[],
            previous_snapshot=deleted.to_dict(),
            current_snapshot=None,
            detected_conflicts=[],
            human_summary=summary,
            recorded_at=datetime.now(UTC),
        )

    def detect_changes(
        self,
        previous_games: Sequence[ReconciledGame | GameModel],
        current_games: Sequence[ReconciledGame],
        *,
        cycle_id: str | None = None,
    ) -> ChangeDetectionCycleResult:
        """Analyze previous and current schedules to compute atomic transitions.

        Args:
            previous_games: Schedule state from prior sync cycle or database.
            current_games: Newly reconciled game schedule.
            cycle_id: Optional tracking identifier for the change detection cycle.

        Returns:
            ChangeDetectionCycleResult summary containing all recorded changes.
        """
        cid = cycle_id or f"{CANONICAL_CHANGE_CYCLE_PREFIX}{uuid4().hex[:12]}"
        started_at = datetime.now(UTC)

        normalized_prev = _normalize_previous_records(previous_games)
        paired, deleted_prev = self._pair_games(normalized_prev, current_games)

        records: list[GameChangeRecord] = [
            self._build_paired_change_record(prev, curr) for prev, curr in paired
        ]
        records.extend(
            self._build_deleted_change_record(deleted) for deleted in deleted_prev
        )

        completed_at = datetime.now(UTC)
        return ChangeDetectionCycleResult(
            cycle_id=cid,
            changes=records,
            started_at=started_at,
            completed_at=completed_at,
        )


__all__ = [
    "CANONICAL_CHANGE_CYCLE_PREFIX",
    "ChangeDetector",
]

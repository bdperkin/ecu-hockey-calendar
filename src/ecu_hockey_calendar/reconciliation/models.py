"""Data structures and domain entities for schedule reconciliation.

This module defines models for multi-source game records, source priority
hierarchies, detected schedule discrepancies, conflicts, and reconciled
canonical game representations.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.storage.models import DataSourceType, GameStatus

if TYPE_CHECKING:
    from ecu_hockey_calendar.storage.models import GameModel


class ConflictSeverity(StrEnum):
    """Severity classification for detected schedule conflicts."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConflictField(StrEnum):
    """Categorization of fields subject to multi-source conflict."""

    DATE = "date"
    START_TIME = "start_time"
    VENUE = "venue"
    STATUS = "status"
    HOME_AWAY = "home_away"
    RESULT = "result"
    HOME_SCORE = "home_score"
    AWAY_SCORE = "away_score"


class ReconciliationStatus(StrEnum):
    """Operational lifecycle state of a reconciled schedule record."""

    UNRESOLVED = "unresolved"
    AUTO_RESOLVED = "auto_resolved"
    FLAGGED_FOR_REVIEW = "flagged_for_review"
    MANUALLY_RESOLVED = "manually_resolved"


class TimingRelationship(StrEnum):
    """Classification of temporal alignment between two game records."""

    EXACT_MATCH = "exact_match"
    WITHIN_TOLERANCE = "within_tolerance"
    TIME_TBD_MATCH = "time_tbd_match"
    TIME_DISCREPANCY = "time_discrepancy"
    DATE_ADJACENT = "date_adjacent"
    DATE_MISMATCH = "date_mismatch"


DEFAULT_SOURCE_TIERS: dict[str, int] = {
    DataSourceType.PRIMARY_SOT.value: 1,
    DataSourceType.LEAGUE.value: 1,
    DataSourceType.TICKETS.value: 2,
    DataSourceType.SOCIAL.value: 2,
    DataSourceType.OPPONENT.value: 3,
}

DEFAULT_SOURCE_TIE_BREAKERS: tuple[str, ...] = (
    DataSourceType.PRIMARY_SOT.value,
    DataSourceType.LEAGUE.value,
    DataSourceType.TICKETS.value,
    DataSourceType.SOCIAL.value,
    DataSourceType.OPPONENT.value,
)


def _normalize_source_key(source: DataSourceType | str) -> str:
    """Normalize DataSourceType or string to lowercase string."""
    if isinstance(source, DataSourceType):
        return source.value

    return str(source).lower()


def _compare_numeric_precedence(val_a: int, val_b: int) -> int:
    """Compare two precedence values: -1 if a < b, 1 if b < a, 0 if equal."""
    if val_a < val_b:
        return -1

    if val_b < val_a:
        return 1

    return 0


def _lookup_tiebreaker_order(key: str, tie_breakers: tuple[str, ...]) -> int:
    """Find index in tie breakers or return length if absent."""
    try:
        return tie_breakers.index(key)
    except ValueError:
        return len(tie_breakers)


@dataclass
class SourcePriority:
    """Configurable hierarchy and precedence rules across data sources.

    Lower tier values indicate higher precedence (Tier 1 > Tier 2 > Tier 3).
    """

    tier_map: dict[str, int] = dataclass_field(
        default_factory=lambda: dict(DEFAULT_SOURCE_TIERS),
    )
    tie_breakers: tuple[str, ...] = DEFAULT_SOURCE_TIE_BREAKERS
    default_tier: int = 4

    def get_tier(self, source_type: DataSourceType | str) -> int:
        """Lookup precedence tier for a data source type.

        Args:
            source_type: Source type enum or string identifier.

        Returns:
            Precedence tier integer (lower number = higher precedence).
        """
        key = _normalize_source_key(source_type)
        return self.tier_map.get(key, self.default_tier)

    def compare_priority(
        self,
        source_a: DataSourceType | str,
        source_b: DataSourceType | str,
    ) -> int:
        """Compare two sources by precedence tier and tie-breaker ordering.

        Args:
            source_a: First source identifier.
            source_b: Second source identifier.

        Returns:
            -1 if source_a has higher precedence, 1 if source_b has higher
            precedence, 0 if both are identical.
        """
        key_a = _normalize_source_key(source_a)
        key_b = _normalize_source_key(source_b)
        tier_cmp = _compare_numeric_precedence(
            self.get_tier(key_a),
            self.get_tier(key_b),
        )
        if tier_cmp != 0:
            return tier_cmp

        idx_a = _lookup_tiebreaker_order(key_a, self.tie_breakers)
        idx_b = _lookup_tiebreaker_order(key_b, self.tie_breakers)
        return _compare_numeric_precedence(idx_a, idx_b)


def _extract_team_home_and_opponent(
    home_name: str,
    away_name: str,
) -> tuple[bool, str]:
    """Determine home flag and opponent name from team names."""
    h_lower = home_name.lower()
    is_home = "east carolina" in h_lower or "ecu" in h_lower
    opponent = away_name if is_home else home_name
    return is_home, opponent


def _parse_game_status(status_str: str) -> GameStatus:
    """Parse GameStatus safely, defaulting to SCHEDULED."""
    norm = status_str.upper()
    if norm == "COMPLETED":
        return GameStatus.FINAL

    try:
        return GameStatus(norm)
    except ValueError:
        return GameStatus.SCHEDULED


def _parse_game_result(result_str: str | None) -> GameResult | None:
    """Parse GameResult safely."""
    if not result_str:
        return None

    try:
        return GameResult(result_str.upper())
    except ValueError:
        return None


@dataclass
class SourceGameRecord:  # pylint: disable=too-many-instance-attributes
    """Normalized ingested game record from an upstream source."""

    source_type: DataSourceType
    source_code: str
    opponent_name: str
    start_time: datetime
    game_id: str | None = None
    end_time: datetime | None = None
    is_home: bool = True
    is_time_tbd: bool = False
    venue: str = "TBD"
    status: GameStatus = GameStatus.SCHEDULED
    result: GameResult | None = None
    home_score: int | None = None
    away_score: int | None = None
    confidence_score: float = 1.0
    raw_snapshot_id: int | None = None
    scraped_at: datetime | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    @classmethod
    def from_game(
        cls,
        game: Game,
        source_type: DataSourceType = DataSourceType.PRIMARY_SOT,
        source_code: str = "ecuhockey",
        *,
        end_time: datetime | None = None,
        is_time_tbd: bool = False,
        confidence_score: float = 1.0,
        raw_snapshot_id: int | None = None,
        scraped_at: datetime | None = None,
    ) -> SourceGameRecord:
        """Construct a SourceGameRecord from a domain Game instance.

        Args:
            game: Domain Game dataclass instance.
            source_type: Associated data source type.
            source_code: Associated source code identifier.
            end_time: Optional end datetime for the game.
            is_time_tbd: Whether start time is tentative or unknown.
            confidence_score: Source confidence score.
            raw_snapshot_id: Optional snapshot foreign key.
            scraped_at: Optional scrape timestamp.

        Returns:
            SourceGameRecord instance.
        """
        is_home, opponent = _extract_team_home_and_opponent(
            game.home_team.name,
            game.away_team.name,
        )
        return cls(
            source_type=source_type,
            source_code=source_code,
            game_id=game.game_id,
            opponent_name=opponent,
            start_time=game.start_time,
            end_time=end_time,
            is_home=is_home,
            is_time_tbd=is_time_tbd,
            venue=game.venue,
            status=GameStatus.SCHEDULED,
            result=game.result,
            home_score=game.home_score,
            away_score=game.away_score,
            confidence_score=confidence_score,
            raw_snapshot_id=raw_snapshot_id,
            scraped_at=scraped_at or datetime.now(UTC),
        )

    @classmethod
    def from_game_model(
        cls,
        model: GameModel,
        source_type: DataSourceType = DataSourceType.PRIMARY_SOT,
        source_code: str = "database",
    ) -> SourceGameRecord:
        """Construct a SourceGameRecord from a database GameModel entity.

        Args:
            model: SQLAlchemy GameModel entity.
            source_type: Data source type.
            source_code: Data source code.

        Returns:
            SourceGameRecord instance.
        """
        is_home, opponent = _extract_team_home_and_opponent(
            model.home_team.name,
            model.away_team.name,
        )
        st = _parse_game_status(model.status)
        outcome = _parse_game_result(model.result)

        return cls(
            source_type=source_type,
            source_code=source_code,
            game_id=model.game_id,
            opponent_name=opponent,
            start_time=model.start_time,
            end_time=model.end_time,
            is_home=is_home,
            is_time_tbd=False,
            venue=model.venue,
            status=st,
            result=outcome,
            home_score=model.home_score,
            away_score=model.away_score,
            confidence_score=1.0,
            scraped_at=model.updated_at,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize source game record to dictionary representation."""
        return {
            "source_type": self.source_type.value,
            "source_code": self.source_code,
            "game_id": self.game_id,
            "opponent_name": self.opponent_name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "is_home": self.is_home,
            "is_time_tbd": self.is_time_tbd,
            "venue": self.venue,
            "status": self.status.value,
            "result": self.result.value if self.result else None,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "confidence_score": self.confidence_score,
            "raw_snapshot_id": self.raw_snapshot_id,
            "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class DiscrepancyRecord:
    """Record of a single detected field discrepancy between two sources."""

    field: ConflictField
    source_a: str
    source_b: str
    value_a: Any
    value_b: Any
    severity: ConflictSeverity = ConflictSeverity.MEDIUM
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize discrepancy record to dictionary."""
        return {
            "field": self.field.value,
            "source_a": self.source_a,
            "source_b": self.source_b,
            "value_a": str(self.value_a),
            "value_b": str(self.value_b),
            "severity": self.severity.value,
            "notes": self.notes,
        }


@dataclass
class DetectedConflict:
    """Aggregated conflict detected across sources for a specific game."""

    conflict_id: str
    game_key: str
    field: ConflictField
    discrepancies: list[DiscrepancyRecord] = dataclass_field(default_factory=list)
    severity: ConflictSeverity = ConflictSeverity.MEDIUM
    requires_review: bool = False
    resolved: bool = False
    resolved_value: Any = None
    resolved_by_source: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize detected conflict to dictionary."""
        return {
            "conflict_id": self.conflict_id,
            "game_key": self.game_key,
            "field": self.field.value,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
            "severity": self.severity.value,
            "requires_review": self.requires_review,
            "resolved": self.resolved,
            "resolved_value": (
                str(self.resolved_value) if self.resolved_value is not None else None
            ),
            "resolved_by_source": self.resolved_by_source,
            "notes": self.notes,
        }


@dataclass
class ReconciledGame:  # pylint: disable=too-many-instance-attributes
    """Canonical game record produced after multi-source reconciliation."""

    canonical_game_id: str
    opponent_name: str
    start_time: datetime
    venue: str
    is_home: bool = True
    is_time_tbd: bool = False
    end_time: datetime | None = None
    status: GameStatus = GameStatus.SCHEDULED
    result: GameResult | None = None
    home_score: int | None = None
    away_score: int | None = None
    contributing_sources: list[str] = dataclass_field(default_factory=list)
    field_provenance: dict[str, str] = dataclass_field(default_factory=dict)
    status_reconciliation: ReconciliationStatus = ReconciliationStatus.UNRESOLVED
    conflicts: list[DetectedConflict] = dataclass_field(default_factory=list)
    requires_admin_review: bool = False
    confidence_score: float = 1.0

    def to_domain_game(self) -> Game:
        """Convert reconciled game to standard domain Game dataclass.

        Returns:
            Domain Game entity.
        """
        ecu_team = Team(
            name="East Carolina University",
            city="Greenville",
            state="NC",
        )
        opp_team = Team(
            name=self.opponent_name,
            city="Unknown",
            state="NC",
        )
        home = ecu_team if self.is_home else opp_team
        away = opp_team if self.is_home else ecu_team

        return Game(
            game_id=self.canonical_game_id,
            home_team=home,
            away_team=away,
            start_time=self.start_time,
            venue=self.venue,
            result=self.result or GameResult.SCHEDULED,
            home_score=self.home_score,
            away_score=self.away_score,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize reconciled game to dictionary representation."""
        return {
            "canonical_game_id": self.canonical_game_id,
            "opponent_name": self.opponent_name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "venue": self.venue,
            "is_home": self.is_home,
            "is_time_tbd": self.is_time_tbd,
            "status": self.status.value,
            "result": self.result.value if self.result else None,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "contributing_sources": self.contributing_sources,
            "field_provenance": self.field_provenance,
            "status_reconciliation": self.status_reconciliation.value,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "requires_admin_review": self.requires_admin_review,
            "confidence_score": round(self.confidence_score, 2),
        }


@dataclass
class ReconciliationCycleResult:
    """Summary of execution metrics and outputs from a reconciliation run."""

    cycle_id: str
    total_source_records: int
    reconciled_games: list[ReconciledGame] = dataclass_field(default_factory=list)
    total_conflicts_detected: int = 0
    auto_resolved_conflicts: int = 0
    flagged_conflicts: int = 0
    unmatched_records: list[SourceGameRecord] = dataclass_field(default_factory=list)
    started_at: datetime = dataclass_field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = dataclass_field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialize reconciliation cycle result to dictionary."""
        return {
            "cycle_id": self.cycle_id,
            "total_source_records": self.total_source_records,
            "reconciled_games": [g.to_dict() for g in self.reconciled_games],
            "total_conflicts_detected": self.total_conflicts_detected,
            "auto_resolved_conflicts": self.auto_resolved_conflicts,
            "flagged_conflicts": self.flagged_conflicts,
            "unmatched_records": [r.to_dict() for r in self.unmatched_records],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
        }


__all__ = [
    "DEFAULT_SOURCE_TIERS",
    "DEFAULT_SOURCE_TIE_BREAKERS",
    "ConflictField",
    "ConflictSeverity",
    "DetectedConflict",
    "DiscrepancyRecord",
    "ReconciledGame",
    "ReconciliationCycleResult",
    "ReconciliationStatus",
    "SourceGameRecord",
    "SourcePriority",
    "TimingRelationship",
]

"""Core synchronization service and in-process execution manager.

Provides the shared, reusable synchronization pipeline orchestrating
crawler execution, multi-source reconciliation, database persistence,
and notification dispatching. Also provides SyncManager for managing
FastAPI BackgroundTasks execution with concurrency protection (HTTP 409)
and rate-limiting cooldown intervals (HTTP 429).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import os
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from ecu_hockey_calendar.ingestion.acchockey_crawler import ACCHockeyCrawler
from ecu_hockey_calendar.ingestion.ecuhockey_crawler import ECUHockeyCrawler
from ecu_hockey_calendar.notifications.dispatcher import NotificationDispatcher
from ecu_hockey_calendar.reconciliation.change_detector import ChangeDetector
from ecu_hockey_calendar.reconciliation.engine import ReconciliationEngine
from ecu_hockey_calendar.reconciliation.models import (
    ChangeDetectionCycleResult,
    DataSourceType,
    DetectedConflict,
    ReconciledGame,
    SourceGameRecord,
)
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.engine import get_sync_session
from ecu_hockey_calendar.storage.models import (
    DataSourceModel,
    GameModel,
    SyncAuditModel,
    SyncStatus,
    TeamModel,
)
from ecu_hockey_calendar.storage.service import (
    _build_game_change_entities,
    record_change_cycle,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

    from ecu_hockey_calendar.ingestion.html_parser import ParsedGameRecord
    from ecu_hockey_calendar.models import GameResult

logger = logging.getLogger(__name__)

DEFAULT_COOLDOWN_SECONDS: int = 900  # 15 minutes
MIN_COOLDOWN_SECONDS: int = 300  # 5 minutes
MILLIS_PER_SECOND: int = 1000


def _convert_parsed_to_source_record(
    record: ParsedGameRecord,
    source_type: DataSourceType,
    source_code: str,
) -> SourceGameRecord:
    """Convert an ingested ParsedGameRecord into a reconciliation SourceGameRecord.

    Args:
        record: Ingested parsed game fixture.
        source_type: Data source type enum.
        source_code: Unique source identifier code.

    Returns:
        Structured SourceGameRecord ready for reconciliation.
    """
    outcome: GameResult | None = None
    if record.home_score is not None and record.away_score is not None:
        outcome = record.calculate_result()

    return SourceGameRecord(
        source_type=source_type,
        source_code=source_code,
        opponent_name=record.opponent_name,
        start_time=record.start_time,
        game_id=record.game_id,
        is_home=record.is_home,
        venue=record.venue,
        status=record.status,
        result=outcome,
        home_score=record.home_score,
        away_score=record.away_score,
        confidence_score=1.0,
        metadata=dict(record.metadata) if record.metadata else {},
    )


async def _run_ecuhockey_crawler() -> tuple[list[SourceGameRecord], str, float]:
    """Execute the primary ECU Hockey crawler.

    Returns:
        Tuple of (source_records, status_string, duration_seconds).
    """
    t0 = datetime.now(UTC)
    crawler = ECUHockeyCrawler()
    records, _, _, _ = await crawler.crawl()
    dur = (datetime.now(UTC) - t0).total_seconds()
    src_records = [
        _convert_parsed_to_source_record(
            r,
            DataSourceType.PRIMARY_SOT,
            "ecuhockey",
        )
        for r in records
    ]
    return src_records, "SUCCESS", dur


async def _run_acchockey_crawler() -> tuple[list[SourceGameRecord], str, float]:
    """Execute the ACC Hockey league schedule crawler.

    Returns:
        Tuple of (source_records, status_string, duration_seconds).
    """
    t0 = datetime.now(UTC)
    crawler = ACCHockeyCrawler()
    records, _, _, _ = await crawler.crawl()
    dur = (datetime.now(UTC) - t0).total_seconds()
    src_records = [
        _convert_parsed_to_source_record(
            r,
            DataSourceType.LEAGUE,
            "acchockey",
        )
        for r in records
    ]
    return src_records, "SUCCESS", dur


async def _execute_crawlers(
    source_filter: str,
) -> tuple[list[SourceGameRecord], list[dict[str, Any]]]:
    """Execute active crawlers based on source filter and collect telemetry.

    Args:
        source_filter: Filter for source execution ('all', 'ecuhockey', 'acchockey').

    Returns:
        Tuple of (all_source_records, crawl_telemetry_list).
    """
    all_source_records: list[SourceGameRecord] = []
    crawl_telemetry: list[dict[str, Any]] = []

    if source_filter in ("all", "ecuhockey"):
        try:
            records, status_val, dur = await _run_ecuhockey_crawler()
            all_source_records.extend(records)
            crawl_telemetry.append(
                {
                    "source": "ecuhockey",
                    "name": "ECU Hockey Official",
                    "records": len(records),
                    "status": status_val,
                    "duration": dur,
                },
            )
        except Exception as err:  # noqa: BLE001 # pylint: disable=broad-exception-caught
            crawl_telemetry.append(
                {
                    "source": "ecuhockey",
                    "name": "ECU Hockey Official",
                    "records": 0,
                    "status": f"FAILED: {err}",
                    "duration": 0.0,
                },
            )

    if source_filter in ("all", "acchockey"):
        try:
            records, status_val, dur = await _run_acchockey_crawler()
            all_source_records.extend(records)
            crawl_telemetry.append(
                {
                    "source": "acchockey",
                    "name": "ACC Hockey League",
                    "records": len(records),
                    "status": status_val,
                    "duration": dur,
                },
            )
        except Exception as err:  # noqa: BLE001 # pylint: disable=broad-exception-caught
            crawl_telemetry.append(
                {
                    "source": "acchockey",
                    "name": "ACC Hockey League",
                    "records": 0,
                    "status": f"FAILED: {err}",
                    "duration": 0.0,
                },
            )

    return all_source_records, crawl_telemetry


def _load_baseline_games_from_db(
    session: Session,
    season: str | None = None,
) -> list[GameModel]:
    """Retrieve existing game models from database.

    Args:
        session: Active database session.
        season: Optional season filter string.

    Returns:
        List of stored GameModel instances.
    """
    stmt = select(GameModel)
    if season:
        stmt = stmt.where(GameModel.season == season)

    return list(session.scalars(stmt).all())


def _get_or_create_team(
    session: Session,
    name: str,
    city: str = "Unknown",
    state: str = "NC",
) -> TeamModel:
    """Find or create team record by normalized name.

    Args:
        session: Active database session.
        name: Normalized team name.
        city: Default city.
        state: Default state.

    Returns:
        Persisted TeamModel record.
    """
    team = session.scalar(select(TeamModel).where(TeamModel.name == name))
    if not team:
        team = TeamModel(name=name, city=city, state=state)
        session.add(team)
        session.flush()

    return team


def _upsert_reconciled_game(
    session: Session,
    rec_game: ReconciledGame,
    ecu_team_id: int,
) -> None:
    """Upsert a single reconciled game model.

    Args:
        session: Active database session.
        rec_game: Reconciled game domain entity.
        ecu_team_id: Foreign key ID of East Carolina University team.
    """
    opp_team = _get_or_create_team(session, rec_game.opponent_name)
    home_id = ecu_team_id if rec_game.is_home else opp_team.id
    away_id = opp_team.id if rec_game.is_home else ecu_team_id

    game = session.scalar(
        select(GameModel).where(GameModel.game_id == rec_game.canonical_game_id),
    )
    res_val = rec_game.result.value if rec_game.result else None
    if not game:
        game = GameModel(
            game_id=rec_game.canonical_game_id,
            home_team_id=home_id,
            away_team_id=away_id,
            start_time=rec_game.start_time,
            venue=rec_game.venue,
            status=rec_game.status.value,
            home_score=rec_game.home_score,
            away_score=rec_game.away_score,
            result=res_val,
        )
        session.add(game)
    else:
        game.home_team_id = home_id
        game.away_team_id = away_id
        game.start_time = rec_game.start_time
        game.venue = rec_game.venue
        game.status = rec_game.status.value
        game.home_score = rec_game.home_score
        game.away_score = rec_game.away_score
        game.result = res_val

    session.flush()


def _ensure_data_source(
    session: Session,
    source_code: str,
    source_name: str,
    source_type: DataSourceType,
    source_url: str = "",
) -> DataSourceModel:
    """Ensure DataSourceModel row exists for tracking.

    Args:
        session: Active database session.
        source_code: Unique alphanumeric code for the data source.
        source_name: Human-readable display name.
        source_type: Domain source type enum.
        source_url: Canonical web URL.

    Returns:
        Updated or newly inserted DataSourceModel.
    """
    source = session.scalar(
        select(DataSourceModel).where(DataSourceModel.source_code == source_code),
    )
    if not source_url:
        source_url = (
            "https://www.ecuhockey.com"
            if source_code == "ecuhockey"
            else "https://www.acchockey.com"
        )

    if not source:
        source = DataSourceModel(
            source_code=source_code,
            name=source_name,
            source_url=source_url,
            source_type=source_type.value,
            priority_order=1,
            is_active=True,
            last_scraped_at=datetime.now(UTC),
        )
        session.add(source)
        session.flush()
    else:
        source.last_scraped_at = datetime.now(UTC)
        session.flush()

    return source


def _update_existing_audit_record(
    session: Session,
    change_result: ChangeDetectionCycleResult,
) -> bool:
    """Update existing RUNNING audit record with final metrics.

    Args:
        session: Active database session.
        change_result: Completed change detection cycle output.

    Returns:
        True if existing audit was found and updated, False otherwise.
    """
    stmt = select(SyncAuditModel).where(
        SyncAuditModel.sync_cycle_id == change_result.cycle_id,
    )
    existing_audit = session.scalar(stmt)
    if existing_audit is None:
        return False

    started_at = (
        existing_audit.started_at
        if existing_audit.started_at.tzinfo is not None
        else existing_audit.started_at.replace(tzinfo=UTC)
    )
    completed_at = (
        change_result.completed_at
        if change_result.completed_at.tzinfo is not None
        else change_result.completed_at.replace(tzinfo=UTC)
    )
    dur_ms = int((completed_at - started_at).total_seconds() * MILLIS_PER_SECOND)
    existing_audit.completed_at = completed_at
    existing_audit.duration_ms = max(0, dur_ms)
    existing_audit.status = SyncStatus.SUCCESS.value
    existing_audit.games_created = len(change_result.created_games)
    existing_audit.games_updated = len(change_result.updated_games)
    existing_audit.games_deleted = len(change_result.deleted_games)
    existing_audit.conflicts_detected = len(change_result.conflict_games)
    existing_audit.details = change_result.to_dict()

    change_entities = _build_game_change_entities(change_result, existing_audit)
    session.add_all(change_entities)
    session.flush()
    return True


def _persist_reconciled_fixtures(
    session: Session,
    reconciled_games: Sequence[ReconciledGame],
    ecu_team_id: int,
) -> None:
    """Upsert all reconciled game records into the database."""
    for rg in reconciled_games:
        _upsert_reconciled_game(session, rg, ecu_team_id)


def _ensure_crawl_data_sources(
    session: Session,
    crawl_telemetry: Sequence[dict[str, Any]],
) -> None:
    """Ensure data source registry records exist for crawled sources."""
    for telemetry in crawl_telemetry:
        st = (
            DataSourceType.PRIMARY_SOT
            if telemetry["source"] == "ecuhockey"
            else DataSourceType.LEAGUE
        )
        _ensure_data_source(session, telemetry["source"], telemetry["name"], st)


def _persist_sync_results(
    session: Session,
    reconciled_games: Sequence[ReconciledGame],
    crawl_telemetry: Sequence[dict[str, Any]],
    change_result: ChangeDetectionCycleResult,
    *,
    initial_audit_exists: bool = False,
) -> None:
    """Persist reconciled fixtures, active data sources, and audit record.

    Args:
        session: Active database session.
        reconciled_games: Sequence of resolved ReconciledGame entities.
        crawl_telemetry: Telemetry records from crawler execution.
        change_result: Output from change detection.
        initial_audit_exists: Whether an initial RUNNING audit record exists.
    """
    ecu_team = _get_or_create_team(
        session,
        "East Carolina University",
        "Greenville",
        "NC",
    )
    _persist_reconciled_fixtures(session, reconciled_games, ecu_team.id)
    _ensure_crawl_data_sources(session, crawl_telemetry)

    if initial_audit_exists and _update_existing_audit_record(session, change_result):
        return

    record_change_cycle(
        session,
        change_result,
        sync_status=SyncStatus.SUCCESS,
    )


async def _execute_crawler_phase(
    crawler_fn: Callable[..., Any] | None,
    source_filter: str,
) -> tuple[list[SourceGameRecord], list[dict[str, Any]]]:
    """Execute crawlers either via custom callable or default crawlers."""
    exec_crawlers = crawler_fn or _execute_crawlers
    crawl_raw = exec_crawlers(source_filter)
    if inspect.isawaitable(crawl_raw):
        return await crawl_raw

    return crawl_raw


def _collect_conflicts(
    reconciled_games: Sequence[ReconciledGame],
) -> list[DetectedConflict]:
    """Flatten all detected conflicts across reconciled game records."""
    conflicts: list[DetectedConflict] = []
    for rg in reconciled_games:
        conflicts.extend(rg.conflicts)

    return conflicts


def _dispatch_sync_notifications(
    change_result: ChangeDetectionCycleResult,
    *,
    notify: bool,
    dry_run: bool,
    notify_individual: bool,
    dispatcher_cls: type[NotificationDispatcher] | None,
) -> None:
    """Dispatch webhook notifications if notification is enabled and not dry run."""
    if not notify or dry_run:
        return

    disp_class = dispatcher_cls or NotificationDispatcher
    dispatcher = disp_class()
    dispatcher.dispatch_cycle(change_result, individual_changes=notify_individual)


async def run_sync_pipeline(  # pylint: disable=too-many-locals,too-many-arguments # noqa: PLR0913
    *,
    engine: Engine,
    source_filter: str = "all",
    dry_run: bool = False,
    notify: bool = False,
    notify_individual: bool = False,
    season: str | None = None,
    cycle_id: str | None = None,
    initial_audit_exists: bool = False,
    crawler_fn: Callable[..., Any] | None = None,
    baseline_loader_fn: Callable[..., Any] | None = None,
    session_factory: Callable[..., Any] | None = None,
    dispatcher_cls: type[NotificationDispatcher] | None = None,
) -> tuple[list[dict[str, Any]], ChangeDetectionCycleResult, list[DetectedConflict]]:
    """Asynchronously execute core crawl, reconciliation, diffing, and storage.

    Args:
        engine: SQLAlchemy Engine instance.
        source_filter: Filter for source execution ('all', 'ecuhockey', 'acchockey').
        dry_run: If True, skip database persistence and notifications.
        notify: If True and not dry_run, dispatch webhook notifications.
        notify_individual: If True, send individual webhook change messages.
        season: Optional season filter string.
        cycle_id: Optional tracking identifier for this cycle.
        initial_audit_exists: If True, update existing RUNNING audit in DB.
        crawler_fn: Optional custom crawler executor callable.
        baseline_loader_fn: Optional custom baseline game loader callable.
        session_factory: Optional custom SQLAlchemy session factory callable.
        dispatcher_cls: Optional custom NotificationDispatcher class.

    Returns:
        Tuple of (crawl_telemetry, change_detection_result, detected_conflicts).
    """
    Base.metadata.create_all(engine)

    # 1. Run crawlers
    all_source_records, crawl_telemetry = await _execute_crawler_phase(
        crawler_fn,
        source_filter,
    )

    # 2. Reconcile records
    rec_engine = ReconciliationEngine()
    reconciled_cycle = rec_engine.reconcile_games(all_source_records, cycle_id=cycle_id)
    all_conflicts = _collect_conflicts(reconciled_cycle.reconciled_games)

    # 3. Detect changes against DB baseline
    sess_factory = session_factory or get_sync_session
    base_loader = baseline_loader_fn or _load_baseline_games_from_db
    with sess_factory(engine) as session:
        baseline_games = base_loader(session, season)
        detector = ChangeDetector()
        change_result = detector.detect_changes(
            baseline_games,
            reconciled_cycle.reconciled_games,
            cycle_id=reconciled_cycle.cycle_id,
        )

        if not dry_run:
            _persist_sync_results(
                session,
                reconciled_cycle.reconciled_games,
                crawl_telemetry,
                change_result,
                initial_audit_exists=initial_audit_exists,
            )
            session.commit()

    # 4. Webhook notifications
    _dispatch_sync_notifications(
        change_result,
        notify=notify,
        dry_run=dry_run,
        notify_individual=notify_individual,
        dispatcher_cls=dispatcher_cls,
    )

    return crawl_telemetry, change_result, all_conflicts


def execute_sync_pipeline(  # pylint: disable=too-many-arguments # noqa: PLR0913
    *,
    engine: Engine,
    source_filter: str = "all",
    dry_run: bool = False,
    notify: bool = False,
    notify_individual: bool = False,
    season: str | None = None,
    cycle_id: str | None = None,
    initial_audit_exists: bool = False,
    crawler_fn: Callable[..., Any] | None = None,
    baseline_loader_fn: Callable[..., Any] | None = None,
    session_factory: Callable[..., Any] | None = None,
    dispatcher_cls: type[NotificationDispatcher] | None = None,
) -> tuple[list[dict[str, Any]], ChangeDetectionCycleResult, list[DetectedConflict]]:
    """Synchronous entrypoint executing core sync pipeline via asyncio.run.

    Args:
        engine: SQLAlchemy Engine instance.
        source_filter: Source filter string.
        dry_run: If True, do not persist to database.
        notify: If True, dispatch webhooks.
        notify_individual: If True, send individual change notifications.
        season: Optional season filter string.
        cycle_id: Optional tracking identifier for this cycle.
        initial_audit_exists: If True, update existing RUNNING audit in DB.
        crawler_fn: Optional custom crawler executor callable.
        baseline_loader_fn: Optional custom baseline game loader callable.
        session_factory: Optional custom SQLAlchemy session factory callable.
        dispatcher_cls: Optional custom NotificationDispatcher class.

    Returns:
        Tuple of (crawl_telemetry, change_detection_result, detected_conflicts).
    """
    return asyncio.run(
        run_sync_pipeline(
            engine=engine,
            source_filter=source_filter,
            dry_run=dry_run,
            notify=notify,
            notify_individual=notify_individual,
            season=season,
            cycle_id=cycle_id,
            initial_audit_exists=initial_audit_exists,
            crawler_fn=crawler_fn,
            baseline_loader_fn=baseline_loader_fn,
            session_factory=session_factory,
            dispatcher_cls=dispatcher_cls,
        ),
    )


def _calc_cooldown_remaining(
    completed_at: datetime,
    cooldown_seconds: int,
    curr_time: datetime,
) -> int:
    """Calculate remaining cooldown given completion timestamp and current time."""
    dt = (
        completed_at
        if completed_at.tzinfo is not None
        else completed_at.replace(tzinfo=UTC)
    )
    elapsed = (curr_time - dt).total_seconds()
    if elapsed < cooldown_seconds:
        return max(1, math.ceil(cooldown_seconds - elapsed))

    return 0


class SyncManager:
    """Manages in-process background synchronization, concurrency, and cooldown."""

    def _resolve_cooldown(self, cooldown_seconds: int) -> int:
        """Resolve cooldown duration considering configured bounds and env vars.

        Args:
            cooldown_seconds: Desired cooldown duration in seconds.

        Returns:
            Resolved integer cooldown in seconds.
        """
        env_val = os.environ.get("SYNC_COOLDOWN_SECONDS")
        raw_val = int(env_val) if env_val and env_val.isdigit() else cooldown_seconds
        if self._allow_custom_cooldown:
            return max(0, raw_val)

        return max(self._min_cooldown_seconds, raw_val)

    def __init__(
        self,
        engine: Engine | None = None,
        *,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
        min_cooldown_seconds: int = MIN_COOLDOWN_SECONDS,
        allow_custom_cooldown: bool = False,
    ) -> None:
        """Initialize synchronization manager with concurrency and cooldown safeguards.

        Args:
            engine: Optional SQLAlchemy Engine. Can be set or updated later.
            cooldown_seconds: Minimum cooldown interval in seconds between sync runs.
            min_cooldown_seconds: Enforced floor for cooldown duration.
            allow_custom_cooldown: If True, bypass minimum cooldown bound (for tests).
        """
        self.engine = engine
        self._allow_custom_cooldown = allow_custom_cooldown
        self._min_cooldown_seconds = min_cooldown_seconds
        self.cooldown_seconds = self._resolve_cooldown(cooldown_seconds)
        self._is_running = False
        self._active_cycle_id: str | None = None
        self._last_completed_at: datetime | None = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        """Whether a synchronization cycle is currently executing."""
        with self._lock:
            return self._is_running

    @property
    def active_cycle_id(self) -> str | None:
        """Tracking identifier of active cycle, or None if idle."""
        with self._lock:
            return self._active_cycle_id

    @property
    def last_completed_at(self) -> datetime | None:
        """Timestamp when the last cycle finished, or None if none completed."""
        return self._last_completed_at

    def try_acquire(self, cycle_id: str) -> bool:
        """Attempt to acquire the synchronization execution lock.

        Args:
            cycle_id: Tracking identifier for the cycle.

        Returns:
            True if acquired; False if a cycle is already in progress.
        """
        with self._lock:
            if self._is_running:
                return False

            self._is_running = True
            self._active_cycle_id = cycle_id
            return True

    def release(self) -> None:
        """Release the synchronization execution lock."""
        with self._lock:
            self._is_running = False
            self._active_cycle_id = None

    def _init_last_completed_from_db(self) -> None:
        """Initialize last completed timestamp from latest successful database audit."""
        if self.engine is None:
            return

        try:
            with get_sync_session(self.engine) as session:
                stmt = (
                    select(SyncAuditModel.completed_at)
                    .where(
                        SyncAuditModel.completed_at.is_not(None),
                        SyncAuditModel.status.in_(
                            [SyncStatus.SUCCESS.value, "COMPLETED"],
                        ),
                    )
                    .order_by(SyncAuditModel.completed_at.desc())
                    .limit(1)
                )
                db_completed = session.scalar(stmt)
                if db_completed is not None:
                    self._last_completed_at = (
                        db_completed
                        if db_completed.tzinfo is not None
                        else db_completed.replace(tzinfo=UTC)
                    )
        except Exception as err:  # noqa: BLE001 # pylint: disable=broad-exception-caught
            logger.warning("Could not read last sync completion from database: %s", err)

    def _resolve_last_completed_at(self) -> datetime | None:
        """Resolve last completion datetime, initializing from database if available."""
        if self._last_completed_at is None and self.engine is not None:
            self._init_last_completed_from_db()

        return self._last_completed_at

    def get_cooldown_remaining(self, now: datetime | None = None) -> int:
        """Calculate remaining cooldown duration in seconds.

        Args:
            now: Optional reference timestamp for testing. Defaults to UTC now.

        Returns:
            Remaining seconds (>= 1 if in cooldown, 0 if cooldown has elapsed).
        """
        completed_at = self._resolve_last_completed_at()
        if completed_at is None:
            return 0

        curr_time = now if now is not None else datetime.now(UTC)
        return _calc_cooldown_remaining(completed_at, self.cooldown_seconds, curr_time)

    def can_trigger(self, now: datetime | None = None) -> bool:
        """Check if an on-demand synchronization cycle can currently be started.

        Args:
            now: Optional reference timestamp.

        Returns:
            True if idle and cooldown elapsed; False otherwise.
        """
        return not self.is_running and self.get_cooldown_remaining(now=now) == 0

    def record_initial_audit(self, cycle_id: str, source_filter: str = "all") -> None:
        """Persist an initial SyncAuditModel record in RUNNING status.

        Args:
            cycle_id: Tracking identifier for the cycle.
            source_filter: Source filter name.
        """
        if self.engine is None:
            return

        Base.metadata.create_all(self.engine)
        with get_sync_session(self.engine) as session:
            audit = SyncAuditModel(
                sync_cycle_id=cycle_id,
                started_at=datetime.now(UTC),
                status=SyncStatus.RUNNING.value,
                games_created=0,
                games_updated=0,
                games_deleted=0,
                conflicts_detected=0,
                details={"target_source": source_filter, "trigger": "api_on_demand"},
            )
            session.add(audit)
            session.commit()

    def finalize_audit_failure(self, cycle_id: str, error_message: str) -> None:
        """Finalize an in-progress SyncAuditModel record upon failure.

        Args:
            cycle_id: Tracking identifier for the cycle.
            error_message: Error description to record in audit.
        """
        if self.engine is None:
            return

        try:
            with get_sync_session(self.engine) as session:
                stmt = select(SyncAuditModel).where(
                    SyncAuditModel.sync_cycle_id == cycle_id,
                )
                audit = session.scalar(stmt)
                if audit is not None:
                    now = datetime.now(UTC)
                    started_at = (
                        audit.started_at
                        if audit.started_at.tzinfo is not None
                        else audit.started_at.replace(tzinfo=UTC)
                    )
                    dur_ms = int(
                        (now - started_at).total_seconds() * MILLIS_PER_SECOND,
                    )
                    audit.completed_at = now
                    audit.duration_ms = max(0, dur_ms)
                    audit.status = SyncStatus.FAILURE.value
                    audit.error_message = error_message
                    session.commit()
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Failed to update sync audit failure record")

    def trigger_handler(self, cycle_id: str, *, source: str | None = None) -> None:
        """Callable hook matching sync_trigger_handler interface.

        Args:
            cycle_id: Unique cycle identifier.
            source: Optional source filter.

        Raises:
            RuntimeError: If a cycle is already executing.
        """
        if not self.try_acquire(cycle_id):
            conflict_msg = "A synchronization cycle is already in progress."
            raise RuntimeError(conflict_msg)

        self.record_initial_audit(cycle_id, source_filter=source or "all")

    async def run_background_sync(
        self,
        cycle_id: str,
        source: str | None = None,
        *,
        season: str | None = None,
        notify: bool = False,
        notify_individual: bool = False,
        crawler_fn: Callable[..., Any] | None = None,
    ) -> (
        tuple[list[dict[str, Any]], ChangeDetectionCycleResult, list[DetectedConflict]]
        | None
    ):
        """Background worker execution invoked by FastAPI BackgroundTasks.

        Args:
            cycle_id: Unique cycle tracking ID.
            source: Optional source filter.
            season: Optional season filter string.
            notify: Whether to dispatch webhook notifications.
            notify_individual: Whether to dispatch individual change alerts.
            crawler_fn: Optional custom crawler execution callable.

        Returns:
            Pipeline result tuple, or None on failure or missing engine.
        """
        try:
            if self.engine is None:
                return None

            return await run_sync_pipeline(
                engine=self.engine,
                source_filter=(source or "all").lower(),
                dry_run=False,
                notify=notify,
                notify_individual=notify_individual,
                season=season,
                cycle_id=cycle_id,
                initial_audit_exists=True,
                crawler_fn=crawler_fn,
            )
        except Exception as err:  # pylint: disable=broad-exception-caught
            logger.exception(
                "Background synchronization cycle %s failed",
                cycle_id,
            )
            self.finalize_audit_failure(cycle_id, str(err))
            return None
        finally:
            self._last_completed_at = datetime.now(UTC)
            self.release()

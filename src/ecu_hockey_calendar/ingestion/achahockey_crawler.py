"""Crawler and ingestion manager for ACHA Hockey league schedule."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from ecu_hockey_calendar.ingestion.achahockey_parser import (
    CLIENT_CODE,
    DEFAULT_ACHA_PORTAL_URL,
    DEFAULT_APP_KEY,
    DEFAULT_BASE_URL,
    ECU_TEAM_ID,
    KNOWN_SEASONS,
    parse_achahockey_schedule_json,
    parse_achahockey_seasons_json,
)
from ecu_hockey_calendar.ingestion.client import (
    ResilientHttpClient,
    compute_content_hash,
)
from ecu_hockey_calendar.ingestion.telemetry import (
    ScrapeEvent,
    ScrapeObserver,
)
from ecu_hockey_calendar.reconciliation.models import SourceGameRecord
from ecu_hockey_calendar.storage.models import (
    DataSourceModel,
    DataSourceType,
    GameModel,
    RawSnapshotModel,
    SyncAuditModel,
    SyncStatus,
    TeamModel,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ecu_hockey_calendar.ingestion.html_parser import ParsedGameRecord

logger = logging.getLogger(__name__)

DEFAULT_ACHA_SEASON = "2026-2027"


def _dedupe_records(
    records: list[ParsedGameRecord],
) -> list[ParsedGameRecord]:
    """Deduplicate records by unique game_id preserving encounter order."""
    seen: set[str] = set()
    deduped: list[ParsedGameRecord] = []
    for rec in records:
        if rec.game_id not in seen:
            seen.add(rec.game_id)
            deduped.append(rec)

    return deduped


def _resolve_page_season(
    record: ParsedGameRecord,
    fallback: str = DEFAULT_ACHA_SEASON,
) -> str:
    """Extract season string from record metadata or fallback."""
    if record.metadata and isinstance(record.metadata.get("season"), str):
        return str(record.metadata["season"])

    return fallback


def _resolve_target_season_id(
    item: str,
    available: dict[str, str],
) -> tuple[str, str] | None:
    """Match a season query string against available season labels and IDs."""
    if item in available:
        return item, available[item]

    for s_code, s_id in available.items():
        if item == s_id:
            return s_code, s_id

    return None


def _resolve_crawl_targets(
    seasons: list[str] | None,
    available: dict[str, str],
) -> dict[str, str]:
    """Filter available seasons down to specified targets."""
    if seasons is None:
        return dict(available)

    targets: dict[str, str] = {}
    for s in seasons:
        pair = _resolve_target_season_id(s, available)
        if pair is not None:
            targets[pair[0]] = pair[1]

    return targets


def _to_source_game_record(
    record: ParsedGameRecord,
    source_type: DataSourceType,
    source_code: str,
) -> SourceGameRecord:
    """Convert a single parsed record to a reconciliation SourceGameRecord."""
    outcome = (
        record.calculate_result()
        if record.home_score is not None and record.away_score is not None
        else None
    )
    meta = dict(record.metadata) if record.metadata else {}
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
        metadata=meta,
    )


class ACHAHockeyCrawler:
    """Crawler for ACHA Hockey league schedules via HockeyTech ModuleKit."""

    def __init__(
        self,
        client: ResilientHttpClient | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        portal_url: str = DEFAULT_ACHA_PORTAL_URL,
        team_id: str = ECU_TEAM_ID,
        app_key: str = DEFAULT_APP_KEY,
        client_code: str = CLIENT_CODE,
        observer: ScrapeObserver | None = None,
    ) -> None:
        """Initialize the crawler with HTTP client and configuration.

        Args:
            client: Optional resilient HTTP client instance.
            base_url: Base feed URL for HockeyTech feeds.
            portal_url: Public ACHA portal URL.
            team_id: Target team identifier (ECU = '589').
            app_key: HockeyTech API key parameter.
            client_code: HockeyTech client identifier ('acha').
            observer: Optional telemetry observer interface.
        """
        self.observer = observer
        if client is not None:
            self.client = client
            if observer is not None and getattr(self.client, "observer", None) is None:
                self.client.observer = observer
        else:
            self.client = ResilientHttpClient(observer=observer)

        self.base_url = base_url
        self.portal_url = portal_url
        self.team_id = team_id
        self.app_key = app_key
        self.client_code = client_code

    def _notify_scrape(
        self,
        url: str,
        *,
        status_code: int = 200,
        records_found: int = 0,
        sublinks_found: int = 0,
        details: str = "",
    ) -> None:
        """Report URL scraping progress and item discovery to observer."""
        if self.observer is not None:
            self.observer.on_scrape(
                ScrapeEvent(
                    url=url,
                    status_code=status_code,
                    records_found=records_found,
                    sublinks_found=sublinks_found,
                    details=details,
                    source_code="achahockey",
                ),
            )

    async def discover_seasons(self) -> dict[str, str]:
        """Query HockeyTech seasons feed to discover published seasons.

        Returns:
            Dictionary mapping canonical season strings ('2026-2027') to season_id.
        """
        url = (
            f"{self.base_url}?feed=modulekit&view=seasons"
            f"&key={self.app_key}&client_code={self.client_code}&fmt=json"
        )
        try:
            payload, _ = await self.client.fetch_text(url)
            discovered = parse_achahockey_seasons_json(payload)
            self._notify_scrape(
                url,
                records_found=len(discovered),
                details="Dynamic season discovery",
            )
            merged = dict(KNOWN_SEASONS)
            merged.update(discovered)
            return merged  # noqa: TRY300
        except Exception as exc:  # pylint: disable=broad-exception-caught # noqa: BLE001
            logger.warning(
                "Dynamic season discovery failed, falling back to known seasons: %s",
                exc,
            )
            self._notify_scrape(
                url,
                status_code=500,
                records_found=0,
                details=f"Season discovery fallback: {exc}",
            )
            return dict(KNOWN_SEASONS)

    async def fetch_schedule_for_season(
        self,
        season_id: str,
        *,
        season_hint: str | None = None,
        season_map: dict[str, str] | None = None,
    ) -> tuple[list[ParsedGameRecord], str, str]:
        """Fetch and parse schedule fixtures for a specific season.

        Args:
            season_id: Numeric HockeyTech season identifier.
            season_hint: Optional season label override.
            season_map: Optional season_id to label mapping.

        Returns:
            Tuple of (parsed_records, raw_json_payload, content_hash).
        """
        url = (
            f"{self.base_url}?feed=modulekit&view=schedule"
            f"&team_id={self.team_id}&season_id={season_id}"
            f"&key={self.app_key}&client_code={self.client_code}&fmt=json"
        )
        payload, content_hash = await self.client.fetch_text(url)
        records = parse_achahockey_schedule_json(
            payload,
            season_hint=season_hint,
            season_map=season_map,
            target_team_id=self.team_id,
        )
        self._notify_scrape(
            url,
            records_found=len(records),
            details=f"Season {season_hint or season_id} schedule",
        )
        return records, payload, content_hash

    async def _execute_target_crawls(
        self,
        targets: dict[str, str],
        season_map: dict[str, str],
    ) -> tuple[list[ParsedGameRecord], list[dict[str, Any]]]:
        """Fetch schedules across all target seasons and collect payloads."""
        all_records: list[ParsedGameRecord] = []
        payloads: list[dict[str, Any]] = []

        for s_name, s_id in targets.items():
            records, raw_text, chash = await self.fetch_schedule_for_season(
                s_id,
                season_hint=s_name,
                season_map=season_map,
            )
            all_records.extend(records)
            payloads.append(
                {
                    "season": s_name,
                    "season_id": s_id,
                    "content_hash": chash,
                    "data": json.loads(raw_text),
                },
            )

        return all_records, payloads

    async def crawl(
        self,
        *,
        seasons: list[str] | None = None,
        discover_future: bool = True,
    ) -> tuple[list[ParsedGameRecord], str, str, str]:
        """Execute schedule crawl across requested or discovered seasons.

        Args:
            seasons: Optional list of season labels or IDs to crawl.
            discover_future: Whether to discover new seasons dynamically.

        Returns:
            Tuple of (records, raw_payload, content_hash, content_type).
        """
        available = (
            await self.discover_seasons() if discover_future else dict(KNOWN_SEASONS)
        )
        targets = _resolve_crawl_targets(seasons, available)
        reverse_map = {s_id: s_name for s_name, s_id in available.items()}

        records, payloads = await self._execute_target_crawls(
            targets,
            reverse_map,
        )
        deduped = _dedupe_records(records)
        raw_payload = json.dumps(payloads, sort_keys=True)
        content_hash = compute_content_hash(raw_payload)
        return deduped, raw_payload, content_hash, "application/json"

    @staticmethod
    def to_source_records(
        records: list[ParsedGameRecord],
        source_type: DataSourceType = DataSourceType.LEAGUE,
        source_code: str = "achahockey",
    ) -> list[SourceGameRecord]:
        """Convert parsed records into reconciliation SourceGameRecords.

        Args:
            records: List of scraped ParsedGameRecord fixtures.
            source_type: Designated DataSourceType (defaults to LEAGUE).
            source_code: Source identifier string (defaults to 'achahockey').

        Returns:
            List of SourceGameRecord objects.
        """
        return [_to_source_game_record(r, source_type, source_code) for r in records]

    @staticmethod
    def _finalize_audit(
        audit: SyncAuditModel,
        started_at: datetime,
        status: SyncStatus,
        error_message: str | None = None,
    ) -> None:
        """Update audit completion timestamps, duration, and status."""
        now = datetime.now(UTC)
        audit.completed_at = now
        audit.duration_ms = int((now - started_at).total_seconds() * 1000)
        audit.status = status.value
        audit.error_message = error_message

    def _get_or_create_source(
        self,
        session: Session,
        source_code: str,
    ) -> DataSourceModel:
        """Find or create data source record for ACHA portal."""
        source = session.scalar(
            select(DataSourceModel).where(
                DataSourceModel.source_code == source_code,
            ),
        )
        if not source:
            source = DataSourceModel(
                source_code=source_code,
                name="ACHA Master League Portal",
                source_url=self.portal_url,
                source_type=DataSourceType.LEAGUE.value,
                priority_order=2,
                is_active=True,
            )
            session.add(source)
            session.flush()

        return source

    @staticmethod
    def _get_or_create_team(
        session: Session,
        name: str,
        city: str = "Unknown",
        state: str = "NC",
    ) -> TeamModel:
        """Find or create team record by canonical normalized name."""
        team = session.scalar(select(TeamModel).where(TeamModel.name == name))
        if not team:
            team = TeamModel(name=name, city=city, state=state)
            session.add(team)
            session.flush()

        return team

    @staticmethod
    def _upsert_game(
        session: Session,
        record: ParsedGameRecord,
        home_id: int,
        away_id: int,
    ) -> bool:
        """Create or update single game model. Returns True if created."""
        game = session.scalar(
            select(GameModel).where(GameModel.game_id == record.game_id),
        )
        created = False
        season = _resolve_page_season(record)

        if not game:
            game = GameModel(
                game_id=record.game_id,
                home_team_id=home_id,
                away_team_id=away_id,
                start_time=record.start_time,
                venue=record.venue,
                status=record.status.value,
                home_score=record.home_score,
                away_score=record.away_score,
                result=record.calculate_result().value,
                season=season,
            )
            session.add(game)
            created = True
        else:
            game.home_team_id = home_id
            game.away_team_id = away_id
            game.start_time = record.start_time
            game.venue = record.venue
            game.status = record.status.value
            game.home_score = record.home_score
            game.away_score = record.away_score
            game.result = record.calculate_result().value
            game.season = season

        session.flush()
        return created

    def _persist_game_record(
        self,
        session: Session,
        record: ParsedGameRecord,
        ecu_id: int,
    ) -> bool:
        """Upsert a single game record, creating opponent team if needed."""
        opp_team = self._get_or_create_team(session, record.opponent_name)
        home_id = ecu_id if record.is_home else opp_team.id
        away_id = opp_team.id if record.is_home else ecu_id
        return self._upsert_game(session, record, home_id, away_id)

    def _persist_records(
        self,
        session: Session,
        records: list[ParsedGameRecord],
        ecu_id: int,
    ) -> tuple[int, int]:
        """Persist parsed game records, returning counts of (created, updated)."""
        created = 0
        updated = 0
        for rec in records:
            if self._persist_game_record(session, rec, ecu_id):
                created += 1
            else:
                updated += 1

        return created, updated

    def _record_snapshot_and_games(
        self,
        session: Session,
        source: DataSourceModel,
        crawl_result: tuple[list[ParsedGameRecord], str, str, str],
    ) -> tuple[int, int]:
        """Record raw snapshot and upsert crawled game records into database."""
        records, raw_payload, content_hash, content_type = crawl_result
        session.add(
            RawSnapshotModel(
                source_id=source.id,
                url=self.portal_url,
                content_hash=content_hash,
                content_type=content_type,
                payload=raw_payload,
                captured_at=datetime.now(UTC),
            ),
        )
        ecu_team = self._get_or_create_team(
            session,
            "East Carolina University",
            city="Greenville",
            state="NC",
        )
        return self._persist_records(session, records, ecu_team.id)

    async def crawl_and_sync(
        self,
        session: Session,
        *,
        source_code: str = "league_achahockey",
        seasons: list[str] | None = None,
        discover_future: bool = True,
    ) -> SyncAuditModel:
        """Execute crawl cycle and persist snapshot and game entities.

        Args:
            session: Active SQLAlchemy database session.
            source_code: Unique code for registered DataSource.
            seasons: Optional list of seasons to crawl.
            discover_future: Whether to dynamically discover seasons.

        Returns:
            Persisted SyncAuditModel tracking synchronization results.
        """
        started_at = datetime.now(UTC)
        source = self._get_or_create_source(session, source_code)
        audit = SyncAuditModel(
            source_id=source.id,
            sync_cycle_id=f"sync-{uuid.uuid4().hex[:16]}",
            started_at=started_at,
            status=SyncStatus.RUNNING.value,
        )
        session.add(audit)
        session.flush()

        try:
            crawl_result = await self.crawl(
                seasons=seasons,
                discover_future=discover_future,
            )
            created, updated = self._record_snapshot_and_games(
                session,
                source,
                crawl_result,
            )
            source.last_scraped_at = datetime.now(UTC)
            self._finalize_audit(audit, started_at, SyncStatus.SUCCESS)
            audit.games_created = created
            audit.games_updated = updated
            session.commit()
        except Exception as exc:
            self._finalize_audit(
                audit,
                started_at,
                SyncStatus.FAILURE,
                error_message=str(exc),
            )
            session.commit()
            raise

        return audit


__all__ = [
    "DEFAULT_ACHA_SEASON",
    "ACHAHockeyCrawler",
]

"""Crawler and ingestion manager for the ACC Hockey league schedule."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from ecu_hockey_calendar.ingestion.acchockey_parser import (
    DEFAULT_ACCHL_SEASON,
    DEFAULT_BASE_URL,
    extract_acchockey_team_logos,
    extract_pagination_urls,
    extract_schedule_urls,
    extract_subseason_urls,
    parse_acchockey_schedule_html,
)
from ecu_hockey_calendar.ingestion.client import (
    ResilientHttpClient,
    compute_content_hash,
)
from ecu_hockey_calendar.ingestion.telemetry import (
    ScrapeEvent,
    ScrapeObserver,
)
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

DEFAULT_ACCHL_SCHEDULE_URL = "https://www.acchockey.com/page/show/9602441-east-carolina"
DEFAULT_PAGINATION_LIMIT = 25


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


def _enrich_record_logo(
    rec: ParsedGameRecord,
    logo_map: dict[str, str],
) -> ParsedGameRecord:
    """Assign discovered logo to record if missing."""
    if rec.opponent_logo_url or rec.opponent_name not in logo_map:
        return rec

    discovered = logo_map[rec.opponent_name]
    new_meta = dict(rec.metadata) if rec.metadata is not None else None
    if new_meta is not None:
        new_meta["opponent_logo_url"] = discovered

    return dataclasses.replace(
        rec,
        opponent_logo_url=discovered,
        metadata=new_meta,
    )


def _enrich_records_with_logos(
    records: list[ParsedGameRecord],
    logo_map: dict[str, str],
) -> list[ParsedGameRecord]:
    """Populate opponent_logo_url for records missing table cell logos."""
    if not logo_map:
        return records

    return [_enrich_record_logo(rec, logo_map) for rec in records]


def _resolve_page_season(
    record: ParsedGameRecord,
    fallback: str = DEFAULT_ACCHL_SEASON,
) -> str:
    """Extract season string from record metadata or fallback."""
    if record.metadata and isinstance(record.metadata.get("season"), str):
        return str(record.metadata["season"])

    return fallback


class ACCHockeyCrawler:
    """Crawler for the ACC Hockey league schedule and subseason fixtures."""

    def __init__(
        self,
        client: ResilientHttpClient | None = None,
        base_url: str = DEFAULT_BASE_URL,
        schedule_url: str = DEFAULT_ACCHL_SCHEDULE_URL,
        observer: ScrapeObserver | None = None,
    ) -> None:
        """Initialize the crawler with HTTP client and target endpoints.

        Args:
            client: Optional resilient HTTP client instance.
            base_url: Base domain URL for relative links.
            schedule_url: Default ECU team landing or schedule URL.
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
        self.schedule_url = schedule_url

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
                    source_code="acchockey",
                ),
            )

    async def _fetch_landing_or_schedule(
        self,
        target_url: str,
    ) -> tuple[str, list[ParsedGameRecord]]:
        """Fetch target page, resolving direct schedule link if necessary."""
        html, _ = await self.client.fetch_text(target_url)
        records = parse_acchockey_schedule_html(html)
        subseason_links = extract_subseason_urls(html, self.base_url)
        if records:
            self._notify_scrape(
                target_url,
                records_found=len(records),
                sublinks_found=len(subseason_links),
            )
            return html, records

        schedule_links = extract_schedule_urls(html, self.base_url)
        if schedule_links:
            self._notify_scrape(
                target_url,
                records_found=0,
                sublinks_found=len(subseason_links),
                details="Landing page",
            )
            sched_html, _ = await self.client.fetch_text(schedule_links[0])
            sched_records = parse_acchockey_schedule_html(sched_html)
            self._notify_scrape(
                schedule_links[0],
                records_found=len(sched_records),
                details="Schedule page",
            )
            return html + "\n" + sched_html, sched_records

        self._notify_scrape(
            target_url,
            records_found=0,
            sublinks_found=len(subseason_links),
        )
        return html, []

    async def _crawl_pagination(
        self,
        html: str,
        visited: set[str],
        max_pages: int,
    ) -> tuple[list[ParsedGameRecord], list[str]]:
        """Traverse pagination links and collect additional game records."""
        records: list[ParsedGameRecord] = []
        html_chunks: list[str] = []
        paginated_links = extract_pagination_urls(html, self.base_url)

        for link in paginated_links:
            if len(visited) >= max_pages:
                break

            if link not in visited:
                visited.add(link)
                page_html, _ = await self.client.fetch_text(link)
                html_chunks.append(page_html)
                page_recs = parse_acchockey_schedule_html(page_html)
                self._notify_scrape(
                    link,
                    records_found=len(page_recs),
                    details="Pagination page",
                )
                records.extend(page_recs)

        return records, html_chunks

    async def _crawl_subseasons(
        self,
        html: str,
        visited: set[str],
        max_pages: int,
    ) -> tuple[list[ParsedGameRecord], list[str]]:
        """Traverse subseason dropdown links and extract additional records."""
        records: list[ParsedGameRecord] = []
        html_chunks: list[str] = []
        subseason_links = extract_subseason_urls(html, self.base_url)

        for link in subseason_links:
            if len(visited) >= max_pages:
                break

            if link not in visited:
                visited.add(link)
                sub_html, sub_recs = await self._fetch_landing_or_schedule(link)
                html_chunks.append(sub_html)
                records.extend(sub_recs)

        return records, html_chunks

    async def fetch_schedule(
        self,
        url: str | None = None,
        *,
        include_subseasons: bool = False,
        max_pages: int = DEFAULT_PAGINATION_LIMIT,
    ) -> tuple[list[ParsedGameRecord], str, str]:
        """Fetch and parse schedule page and related paginated views.

        Args:
            url: Target schedule URL or None for default schedule URL.
            include_subseasons: Whether to discover and crawl other subseasons.
            max_pages: Maximum number of pages to fetch.

        Returns:
            Tuple of (parsed_records, aggregated_html, content_hash).
        """  # pylint: disable=too-many-locals
        target_url = url or self.schedule_url
        visited: set[str] = {target_url}

        base_html, records = await self._fetch_landing_or_schedule(target_url)
        all_html = [base_html]

        page_recs, page_htmls = await self._crawl_pagination(
            base_html,
            visited,
            max_pages,
        )
        records.extend(page_recs)
        all_html.extend(page_htmls)

        if include_subseasons:
            sub_recs, sub_htmls = await self._crawl_subseasons(
                base_html,
                visited,
                max_pages,
            )
            records.extend(sub_recs)
            all_html.extend(sub_htmls)

        deduped = _dedupe_records(records)
        aggregated = "\n".join(all_html)
        logo_map = extract_acchockey_team_logos(aggregated, self.base_url)
        enriched = _enrich_records_with_logos(deduped, logo_map)
        return enriched, aggregated, compute_content_hash(aggregated)

    async def crawl(
        self,
        *,
        url: str | None = None,
        include_subseasons: bool = False,
        max_pages: int = DEFAULT_PAGINATION_LIMIT,
    ) -> tuple[list[ParsedGameRecord], str, str, str]:
        """Execute crawl and return raw payloads with content hash.

        Args:
            url: Optional schedule or subseason URL override.
            include_subseasons: Whether to crawl alternate subseasons.
            max_pages: Maximum number of pages to fetch.

        Returns:
            Tuple of (records, raw_html, content_hash, content_type).
        """
        records, html, content_hash = await self.fetch_schedule(
            url=url,
            include_subseasons=include_subseasons,
            max_pages=max_pages,
        )
        return records, html, content_hash, "text/html"

    async def discover_team_logos(
        self,
        html: str | None = None,
        url: str | None = None,
    ) -> dict[str, str]:
        """Discover team logos from page HTML or target URL.

        Args:
            html: Optional HTML string to parse.
            url: Optional URL to fetch if html not provided.

        Returns:
            Dictionary of team names to logo URLs.
        """
        if html is not None:
            return extract_acchockey_team_logos(html, self.base_url)

        target = url or self.schedule_url
        page_html, _ = await self.client.fetch_text(target)
        return extract_acchockey_team_logos(page_html, self.base_url)

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
        """Find or create data source record for league page."""
        source = session.scalar(
            select(DataSourceModel).where(DataSourceModel.source_code == source_code),
        )
        if not source:
            source = DataSourceModel(
                source_code=source_code,
                name="ACCHL Official Website",
                source_url=self.schedule_url,
                source_type=DataSourceType.LEAGUE.value,
                priority_order=2,
                is_active=True,
            )
            session.add(source)
            session.flush()

        return source

    def _get_or_create_team(
        self,
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

    def _upsert_game(
        self,
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
                url=self.schedule_url,
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
        source_code: str = "league_acchockey",
        include_subseasons: bool = True,
        max_pages: int = DEFAULT_PAGINATION_LIMIT,
    ) -> SyncAuditModel:
        """Execute full crawl cycle and persist snapshot and game entities.

        Args:
            session: Active SQLAlchemy database session.
            source_code: Unique code for registered DataSource.
            include_subseasons: Whether to crawl alternate subseasons.
            max_pages: Maximum number of pages to fetch.

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
                include_subseasons=include_subseasons,
                max_pages=max_pages,
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
    "DEFAULT_ACCHL_SCHEDULE_URL",
    "DEFAULT_PAGINATION_LIMIT",
    "ACCHockeyCrawler",
]

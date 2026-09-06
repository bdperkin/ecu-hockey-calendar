"""Asynchronous crawler for ECU Hockey ticketing listings and promotions."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select

from ecu_hockey_calendar.ingestion.client import (
    ResilientHttpClient,
)
from ecu_hockey_calendar.ingestion.tickets_parser import (
    DEFAULT_ECU_CANONICAL,
    DEFAULT_TICKETS_PAGE_URL,
    ParsedTicketRecord,
    parse_firestore_tickets_response,
    parse_html_ticket_listings,
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

DEFAULT_TEAM_ID = "bH8QZkvU64QPqm88Qx8QdjL0O4c2"
DEFAULT_FIRESTORE_URL = (
    "https://firestore.googleapis.com/v1/projects/optimx-sports/"
    "databases/(default)/documents:runQuery"
)


class TicketsCrawler:
    """Crawler for ECU Hockey ticketing listings and promotional events."""

    def __init__(
        self,
        http_client: ResilientHttpClient | None = None,
        *,
        team_id: str = DEFAULT_TEAM_ID,
        firestore_url: str = DEFAULT_FIRESTORE_URL,
        tickets_url: str = DEFAULT_TICKETS_PAGE_URL,
    ) -> None:
        """Initialize the ticketing crawler.

        Args:
            http_client: Optional preconfigured ResilientHttpClient instance.
            team_id: Target OptimX Sports team identifier.
            firestore_url: Google Firestore runQuery REST endpoint.
            tickets_url: ECU Hockey ticketing page URL.
        """
        self.client = http_client or ResilientHttpClient()
        self.team_id = team_id
        self.firestore_url = firestore_url
        self.tickets_url = tickets_url

    async def fetch_firestore_tickets(
        self,
        team_id: str | None = None,
    ) -> tuple[list[ParsedTicketRecord], str, str]:
        """Fetch and parse ticket offerings from Firestore REST API.

        Args:
            team_id: Optional overriding team ID.

        Returns:
            Tuple of (parsed_records, raw_json_payload, content_hash).
        """
        tid = team_id or self.team_id
        query_payload = {
            "structuredQuery": {
                "from": [{"collectionId": "tickets"}],
                "where": {
                    "fieldFilter": {
                        "field": {"fieldPath": "teamId"},
                        "op": "EQUAL",
                        "value": {"stringValue": tid},
                    },
                },
            },
        }
        data, content_hash = await self.client.post_json(
            self.firestore_url,
            json_data=query_payload,
        )
        records = parse_firestore_tickets_response(data)
        return records, json.dumps(data), content_hash

    async def fetch_html_tickets(
        self,
        url: str | None = None,
        *,
        season: str = "2026-2027",
    ) -> tuple[list[ParsedTicketRecord], str, str]:
        """Fetch and parse ticket offerings from HTML ticket sales page.

        Args:
            url: Target URL (defaults to tickets_url).
            season: Target collegiate hockey season.

        Returns:
            Tuple of (parsed_records, raw_html_string, content_hash).
        """
        target_url = url or self.tickets_url
        html, content_hash = await self.client.fetch_text(target_url)
        records = parse_html_ticket_listings(
            html,
            base_url=target_url,
            season=season,
        )
        return records, html, content_hash

    async def crawl(
        self,
        *,
        try_firestore: bool = True,
        season: str = "2026-2027",
    ) -> tuple[list[ParsedTicketRecord], str, str, str]:
        """Execute ticketing crawl with Firestore primary and HTML fallback.

        Args:
            try_firestore: Whether to attempt Firestore query before HTML.
            season: Target collegiate hockey season.

        Returns:
            Tuple of (records, raw_payload, content_hash, content_type).
        """
        if try_firestore:
            try:
                records, raw_text, content_hash = await self.fetch_firestore_tickets()
                if records:
                    return records, raw_text, content_hash, "application/json"
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                # Fall back to HTML scraping if Firestore fails.
                pass

        records, raw_text, content_hash = await self.fetch_html_tickets(
            season=season,
        )
        return records, raw_text, content_hash, "text/html"

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
        code: str,
    ) -> DataSourceModel:
        """Retrieve or register the ticketing DataSourceModel."""
        source = session.scalar(
            select(DataSourceModel).where(DataSourceModel.source_code == code),
        )
        if source is None:
            source = DataSourceModel(
                source_code=code,
                name="ECU Hockey Tickets",
                source_url=self.tickets_url,
                source_type=DataSourceType.TICKETS.value,
                priority_order=3,
                is_active=True,
            )
            session.add(source)
            session.flush()

        return source

    @staticmethod
    def _get_or_create_team(
        session: Session,
        name: str,
        *,
        city: str = "",
        state: str = "",
    ) -> TeamModel:
        """Find existing TeamModel by name or insert a new record."""
        team = session.scalar(select(TeamModel).where(TeamModel.name == name))
        if team is None:
            team = TeamModel(name=name, city=city, state=state)
            session.add(team)
            session.flush()

        return team

    def _persist_game_from_ticket(
        self,
        session: Session,
        record: ParsedTicketRecord,
        ecu_id: int,
        season: str,
    ) -> bool:
        """Upsert a game model corresponding to a home game ticket listing."""
        game_rec = record.to_parsed_game_record(season=season)
        if game_rec is None:
            return False

        opp_team = self._get_or_create_team(session, game_rec.opponent_name)
        existing = session.scalar(
            select(GameModel).where(
                (GameModel.game_id == game_rec.game_id)
                | (
                    (GameModel.home_team_id == ecu_id)
                    & (GameModel.away_team_id == opp_team.id)
                    & (GameModel.start_time == game_rec.start_time)
                ),
            ),
        )

        if existing is None:
            session.add(
                GameModel(
                    game_id=game_rec.game_id,
                    home_team_id=ecu_id,
                    away_team_id=opp_team.id,
                    start_time=game_rec.start_time,
                    venue=game_rec.venue,
                    status=game_rec.status.value,
                    season=season,
                ),
            )
            return True

        # Enrich existing game venue if currently TBD
        if existing.venue in {"", "TBD"} and game_rec.venue not in {"", "TBD"}:
            existing.venue = game_rec.venue

        return False

    def _persist_records(
        self,
        session: Session,
        records: list[ParsedTicketRecord],
        ecu_id: int,
        season: str,
    ) -> tuple[int, int]:
        """Upsert identifiable home games from ticket records into database."""
        created = 0
        updated = 0

        for rec in records:
            if not rec.is_home_game or not rec.opponent_name:
                continue

            if self._persist_game_from_ticket(session, rec, ecu_id, season):
                created += 1
            else:
                updated += 1

        return created, updated

    def _record_snapshot_and_sync(
        self,
        session: Session,
        source: DataSourceModel,
        crawl_result: tuple[list[ParsedTicketRecord], str, str, str],
        season: str,
    ) -> tuple[int, int]:
        """Record raw snapshot and upsert any home games into database."""
        records, raw_payload, content_hash, content_type = crawl_result
        session.add(
            RawSnapshotModel(
                source_id=source.id,
                url=self.tickets_url,
                content_hash=content_hash,
                content_type=content_type,
                payload=raw_payload,
                captured_at=datetime.now(UTC),
            ),
        )

        ecu_team = self._get_or_create_team(
            session,
            DEFAULT_ECU_CANONICAL,
            city="Greenville",
            state="NC",
        )
        return self._persist_records(session, records, ecu_team.id, season)

    async def crawl_and_sync(
        self,
        session: Session,
        *,
        source_code: str = "tickets_ecuhockey",
        try_firestore: bool = True,
        season: str = "2026-2027",
    ) -> SyncAuditModel:
        """Execute full crawl cycle and persist snapshot and game entities.

        Args:
            session: Active SQLAlchemy database session.
            source_code: Unique identifier code for registered DataSource.
            try_firestore: Whether to attempt Firestore query before HTML.
            season: Target collegiate hockey season.

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
                try_firestore=try_firestore,
                season=season,
            )
            created, updated = self._record_snapshot_and_sync(
                session,
                source,
                crawl_result,
                season,
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
    "DEFAULT_FIRESTORE_URL",
    "DEFAULT_TEAM_ID",
    "DEFAULT_TICKETS_PAGE_URL",
    "TicketsCrawler",
]

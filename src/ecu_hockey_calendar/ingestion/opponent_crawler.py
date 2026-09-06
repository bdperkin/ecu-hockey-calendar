"""Asynchronous crawler for opponent schedule feeds with reverse verification."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import select

from ecu_hockey_calendar.ingestion.client import (
    ResilientHttpClient,
)
from ecu_hockey_calendar.ingestion.instagram_crawler import (
    RateLimiter,
    SessionCache,
)
from ecu_hockey_calendar.ingestion.opponent_parser import (
    OpponentDirectory,
    OpponentEndpointConfig,
    OpponentFeedType,
    OpponentFixture,
    ReverseCheckResult,
    VerificationStatus,
    cross_check_game_against_opponent,
    get_default_opponent_directory,
    is_ecu_match,
    parse_opponent_html_feed,
    parse_opponent_ical_feed,
    parse_opponent_json_feed,
)
from ecu_hockey_calendar.storage.models import (
    DataSourceModel,
    DataSourceType,
    GameModel,
    RawSnapshotModel,
    SyncAuditModel,
    SyncStatus,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from ecu_hockey_calendar.models import Game

DEFAULT_OPPONENT_CACHE_TTL = 3600.0


def _parse_cached_opponent_feed(
    payload: str,
    feed_type: OpponentFeedType,
    canonical_name: str,
) -> list[OpponentFixture]:
    """Parse cached payload text according to configured feed type."""
    if feed_type == OpponentFeedType.ICAL:
        return parse_opponent_ical_feed(payload, canonical_name)

    if feed_type == OpponentFeedType.JSON:
        try:
            data = json.loads(payload)
            return parse_opponent_json_feed(data, canonical_name)
        except (ValueError, TypeError):
            return []

    return parse_opponent_html_feed(payload, canonical_name)


class OpponentCrawler:
    """Crawler for opposing collegiate schedules with reverse cross-checking."""

    def __init__(
        self,
        http_client: ResilientHttpClient | None = None,
        *,
        directory: OpponentDirectory | None = None,
        session_cache: SessionCache | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        """Initialize the opponent crawler.

        Args:
            http_client: Optional preconfigured ResilientHttpClient.
            directory: Optional custom OpponentDirectory instance.
            session_cache: Optional SessionCache instance.
            rate_limiter: Optional RateLimiter instance.
        """
        self.client = http_client or ResilientHttpClient()
        self.directory = directory or get_default_opponent_directory()
        self.cache = session_cache or SessionCache(
            default_ttl=DEFAULT_OPPONENT_CACHE_TTL,
        )
        self.rate_limiter = rate_limiter or RateLimiter()

    async def _fetch_ical_feed(
        self,
        url: str,
        canonical_name: str,
    ) -> tuple[list[OpponentFixture], str, str, str]:
        """Fetch and parse RFC 5545 iCalendar opponent feed."""
        text, content_hash = await self.client.fetch_text(url)
        fixtures = parse_opponent_ical_feed(text, canonical_name)
        return fixtures, text, content_hash, "text/calendar"

    async def _fetch_json_feed(
        self,
        url: str,
        canonical_name: str,
    ) -> tuple[list[OpponentFixture], str, str, str]:
        """Fetch and parse JSON-formatted opponent feed."""
        data, content_hash = await self.client.fetch_json(url)
        fixtures = parse_opponent_json_feed(data, canonical_name)
        payload = json.dumps(data)
        return fixtures, payload, content_hash, "application/json"

    async def _fetch_html_feed(
        self,
        url: str,
        canonical_name: str,
    ) -> tuple[list[OpponentFixture], str, str, str]:
        """Fetch and parse HTML schedule table opponent feed."""
        html, content_hash = await self.client.fetch_text(url)
        fixtures = parse_opponent_html_feed(html, canonical_name)
        return fixtures, html, content_hash, "text/html"

    async def _dispatch_feed_fetch(
        self,
        config: OpponentEndpointConfig,
    ) -> tuple[list[OpponentFixture], str, str, str]:
        """Route network request to appropriate feed handler based on feed type."""
        await self.rate_limiter.acquire()
        if config.feed_type == OpponentFeedType.ICAL:
            return await self._fetch_ical_feed(config.feed_url, config.canonical_name)

        if config.feed_type == OpponentFeedType.JSON:
            return await self._fetch_json_feed(config.feed_url, config.canonical_name)

        return await self._fetch_html_feed(config.feed_url, config.canonical_name)

    def _get_cached_fixtures(
        self,
        config: OpponentEndpointConfig,
        *,
        allow_stale: bool = False,
    ) -> tuple[list[OpponentFixture], str, str, str] | None:
        """Retrieve cached fixtures for an opponent configuration."""
        key = f"opp:{config.canonical_name}"
        cached = self.cache.get(key, allow_stale=allow_stale)
        if not cached:
            return None

        payload, chash, ctype = cached
        fixtures = _parse_cached_opponent_feed(
            payload,
            config.feed_type,
            config.canonical_name,
        )
        return fixtures, payload, chash, ctype

    async def _fetch_with_fallback(
        self,
        config: OpponentEndpointConfig,
    ) -> tuple[list[OpponentFixture], str, str, str]:
        """Fetch remote feed with stale cache fallback on network or parse error."""
        try:
            res = await self._dispatch_feed_fetch(config)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            stale = self._get_cached_fixtures(config, allow_stale=True)
            return stale if stale is not None else ([], "", "", "none")

        _, payload, chash, ctype = res
        self.cache.set(f"opp:{config.canonical_name}", payload, chash, ctype)
        return res

    async def fetch_opponent_schedule(
        self,
        opponent_name: str,
        *,
        use_cache: bool = True,
    ) -> tuple[list[OpponentFixture], str, str, str]:
        """Fetch and parse an opponent's schedule feed.

        Args:
            opponent_name: Raw or canonical name of the opponent institution.
            use_cache: Whether to use valid cached responses if available.

        Returns:
            Tuple of (fixtures, raw_payload, content_hash, content_type).
        """
        config = self.directory.get(opponent_name)
        if not config:
            return [], "", "", "none"

        if use_cache:
            cached = self._get_cached_fixtures(config, allow_stale=False)
            if cached is not None:
                return cached

        return await self._fetch_with_fallback(config)

    @staticmethod
    def _resolve_opponent_name(game: Game | GameModel) -> str:
        """Extract opponent team name from game entity."""
        home_name = game.home_team.name
        away_name = game.away_team.name
        if is_ecu_match(home_name):
            return away_name

        return home_name

    def _build_unavailable_result(
        self,
        game_id: str | int | None,
        opp_name: str,
        notes: str,
    ) -> ReverseCheckResult:
        """Construct an UNAVAILABLE reverse check result."""
        return ReverseCheckResult(
            ecu_game_id=game_id,
            opponent_canonical_name=opp_name,
            verification_status=VerificationStatus.UNAVAILABLE,
            confidence_score=0.0,
            notes=notes,
        )

    async def reverse_check_game(
        self,
        game: Game | GameModel,
        *,
        use_cache: bool = True,
    ) -> ReverseCheckResult:
        """Reverse check a single ECU game against the opponent's schedule feed.

        Args:
            game: Domain Game or relational GameModel to verify.
            use_cache: Whether to leverage cached opponent feeds.

        Returns:
            ReverseCheckResult describing verification and discrepancies.
        """
        opp_name = self._resolve_opponent_name(game)
        config = self.directory.get(opp_name)
        if not config:
            note = f"No opponent directory config registered for '{opp_name}'"
            return self._build_unavailable_result(game.game_id, opp_name, note)

        fixtures, _, _, _ = await self.fetch_opponent_schedule(
            opp_name,
            use_cache=use_cache,
        )
        if not fixtures:
            note = (
                "Opponent schedule feed returned no fixtures for "
                f"'{config.canonical_name}'"
            )
            return self._build_unavailable_result(
                game.game_id,
                config.canonical_name,
                note,
            )

        return cross_check_game_against_opponent(game, fixtures, config.canonical_name)

    async def reverse_check_all_games(
        self,
        games: Sequence[Game | GameModel],
        *,
        use_cache: bool = True,
    ) -> dict[str, ReverseCheckResult]:
        """Perform reverse check across multiple ECU games.

        Args:
            games: Collection of games to verify.
            use_cache: Whether to use cached opponent feeds.

        Returns:
            Dictionary mapping game_id string to ReverseCheckResult.
        """
        results: dict[str, ReverseCheckResult] = {}
        for game in games:
            res = await self.reverse_check_game(game, use_cache=use_cache)
            results[str(game.game_id)] = res

        return results

    def _get_or_create_source(
        self,
        session: Session,
        code: str = "opponent",
    ) -> DataSourceModel:
        """Retrieve or register the opponent DataSourceModel."""
        source = session.scalar(
            select(DataSourceModel).where(DataSourceModel.source_code == code),
        )
        if source is None:
            source = DataSourceModel(
                source_code=code,
                name="Opponent Schedule Cross-Check",
                source_url="https://github.com/bdperkin/ecu-hockey-calendar",
                source_type=DataSourceType.OPPONENT.value,
                priority_order=5,
                is_active=True,
            )
            session.add(source)
            session.flush()

        return source

    def _record_snapshot(
        self,
        session: Session,
        source: DataSourceModel,
        *,
        url: str,
        payload: str,
        content_hash: str,
        content_type: str,
    ) -> RawSnapshotModel | None:
        """Record raw payload snapshot if content is present."""
        if not payload or not content_hash:
            return None

        snapshot = RawSnapshotModel(
            source_id=source.id,
            url=url,
            content_hash=content_hash,
            content_type=content_type,
            payload=payload,
            captured_at=datetime.now(UTC),
        )
        session.add(snapshot)
        session.flush()
        return snapshot

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

    async def _capture_opponent_snapshots(
        self,
        session: Session,
        source: DataSourceModel,
        target_games: Sequence[GameModel],
        *,
        use_cache: bool,
    ) -> None:
        """Fetch opponent feeds and persist immutable snapshots."""
        visited_opponents: set[str] = set()
        for game in target_games:
            opp_name = self._resolve_opponent_name(game)
            config = self.directory.get(opp_name)
            if not config or config.canonical_name in visited_opponents:
                continue

            visited_opponents.add(config.canonical_name)
            _, payload, chash, ctype = await self.fetch_opponent_schedule(
                config.canonical_name,
                use_cache=use_cache,
            )
            self._record_snapshot(
                session,
                source,
                url=config.feed_url,
                payload=payload,
                content_hash=chash,
                content_type=ctype,
            )

    async def _process_game_verifications(
        self,
        target_games: Sequence[GameModel],
        *,
        use_cache: bool,
    ) -> tuple[int, int, dict[str, Any]]:
        """Verify target games against opponent feeds and summarize metrics."""
        verified_count = 0
        discrepancy_count = 0
        results_map: dict[str, Any] = {}

        for game in target_games:
            res = await self.reverse_check_game(game, use_cache=use_cache)
            results_map[str(game.game_id)] = res.to_dict()

            if res.verification_status == VerificationStatus.VERIFIED:
                verified_count += 1
            elif res.verification_status == VerificationStatus.DISCREPANCY:
                discrepancy_count += 1

        return verified_count, discrepancy_count, results_map

    @staticmethod
    def _resolve_target_games(
        session: Session,
        games: Sequence[GameModel] | None,
        season: str,
    ) -> list[GameModel]:
        """Resolve target games from arguments or query database by season."""
        if games is not None:
            return list(games)

        return list(
            session.scalars(select(GameModel).where(GameModel.season == season)),
        )

    def _update_audit_metrics(
        self,
        audit: SyncAuditModel,
        started_at: datetime,
        *,
        total_games: int,
        verified: int,
        discrepancies: int,
        res_map: dict[str, Any],
    ) -> None:
        """Update audit model metrics and completion status."""
        status = SyncStatus.SUCCESS if total_games else SyncStatus.PARTIAL
        err = None if total_games else "No games provided or found for verification"
        self._finalize_audit(audit, started_at, status, error_message=err)
        audit.games_updated = verified
        audit.conflicts_detected = discrepancies
        audit.details = {
            "results": res_map,
            "total_games_checked": total_games,
            "verified": verified,
            "discrepancies": discrepancies,
        }

    async def sync(
        self,
        session: Session,
        *,
        games: Sequence[GameModel] | None = None,
        season: str = "2026-2027",
        use_cache: bool = True,
    ) -> tuple[int, int, SyncAuditModel]:
        """Perform full reverse check ingestion sync against opposing schedules.

        Args:
            session: Active SQLAlchemy database session.
            games: Optional explicit collection of GameModel entities to check.
            season: Target athletic season string.
            use_cache: Whether to use cached opponent feeds.

        Returns:
            Tuple of (verified_count, discrepancy_count, audit_record).
        """
        started_at = datetime.now(UTC)
        sync_id = (
            f"opponent-{started_at.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        )
        source = self._get_or_create_source(session)
        audit = SyncAuditModel(
            sync_cycle_id=sync_id,
            source_id=source.id,
            started_at=started_at,
            status=SyncStatus.RUNNING.value,
        )
        session.add(audit)
        session.flush()

        try:
            target_games = self._resolve_target_games(session, games, season)
            await self._capture_opponent_snapshots(
                session,
                source,
                target_games,
                use_cache=use_cache,
            )
            verified, discrepancies, res_map = await self._process_game_verifications(
                target_games,
                use_cache=use_cache,
            )
            self._update_audit_metrics(
                audit,
                started_at,
                total_games=len(target_games),
                verified=verified,
                discrepancies=discrepancies,
                res_map=res_map,
            )
            session.commit()
        except Exception as exc:
            self._finalize_audit(audit, started_at, SyncStatus.FAILURE, str(exc))
            session.commit()
            raise

        return verified, discrepancies, audit


__all__ = [
    "DEFAULT_OPPONENT_CACHE_TTL",
    "OpponentCrawler",
]

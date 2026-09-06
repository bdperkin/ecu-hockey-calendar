"""Crawler for ECU Hockey Instagram announcements with caching and rate limiting."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select

from ecu_hockey_calendar.ingestion.client import (
    ResilientHttpClient,
)
from ecu_hockey_calendar.ingestion.instagram_parser import (
    DEFAULT_GRAPH_API_URL,
    DEFAULT_INSTAGRAM_URL,
    DEFAULT_INSTAGRAM_USERNAME,
    DEFAULT_WEB_PROFILE_URL,
    IG_APP_ID,
    ParsedInstagramPost,
    cross_reference_announcements_with_games,
    matches_post_to_game,
    parse_graph_api_response,
    parse_html_instagram_feed,
    parse_public_feed_json,
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
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

DEFAULT_RATE_LIMIT_INTERVAL = 1.5
DEFAULT_CACHE_TTL_SECONDS = 3600.0


class RateLimiter:
    """Async token rate limiter enforcing minimum delays between network calls."""

    def __init__(self, min_interval: float = DEFAULT_RATE_LIMIT_INTERVAL) -> None:
        """Initialize the rate limiter.

        Args:
            min_interval: Minimum duration in seconds between requests.
        """
        self.min_interval = min_interval
        self._last_request_time: float = 0.0

    def time_since_last_request(self) -> float:
        """Calculate elapsed seconds since the last registered request."""
        return time.monotonic() - self._last_request_time

    def update_timestamp(self) -> None:
        """Update last request timestamp to current monotonic time."""
        self._last_request_time = time.monotonic()

    async def acquire(self) -> None:
        """Enforce delay if minimum interval has not elapsed."""
        elapsed = self.time_since_last_request()
        if elapsed < self.min_interval:
            await asyncio.sleep(self.min_interval - elapsed)

        self.update_timestamp()


@dataclass
class CacheEntry:
    """Cached response entry with content and expiry timestamp."""

    payload: str
    content_hash: str
    content_type: str
    expires_at: float


class SessionCache:
    """In-memory cache for Instagram feed payloads with TTL management."""

    def __init__(self, default_ttl: float = DEFAULT_CACHE_TTL_SECONDS) -> None:
        """Initialize the session cache.

        Args:
            default_ttl: Default entry time-to-live in seconds.
        """
        self.default_ttl = default_ttl
        self._store: dict[str, CacheEntry] = {}

    def set(
        self,
        key: str,
        payload: str,
        content_hash: str,
        content_type: str,
        ttl: float | None = None,
    ) -> None:
        """Store an entry in the cache.

        Args:
            key: Cache lookup key.
            payload: Raw payload content string.
            content_hash: Content hash string.
            content_type: Payload MIME type.
            ttl: Optional explicit TTL in seconds.
        """
        duration = ttl if ttl is not None else self.default_ttl
        expiry = time.monotonic() + duration
        self._store[key] = CacheEntry(
            payload=payload,
            content_hash=content_hash,
            content_type=content_type,
            expires_at=expiry,
        )

    def get(
        self,
        key: str,
        *,
        allow_stale: bool = False,
    ) -> tuple[str, str, str] | None:
        """Retrieve cached entry if valid or stale when allowed.

        Args:
            key: Cache lookup key.
            allow_stale: Whether to return expired entries during fallback.

        Returns:
            Tuple of (payload, content_hash, content_type) or None.
        """
        entry = self._store.get(key)
        if not entry:
            return None

        if time.monotonic() > entry.expires_at and not allow_stale:
            return None

        return entry.payload, entry.content_hash, entry.content_type

    def has(self, key: str) -> bool:
        """Check if an unexpired entry exists for the key.

        Args:
            key: Cache key to check.

        Returns:
            True if unexpired key exists.
        """
        return self.get(key, allow_stale=False) is not None

    def clear(self) -> None:
        """Purge all entries from the cache."""
        self._store.clear()


class InstagramCrawler:
    """Crawler for ECU Hockey Instagram social media announcements."""

    def __init__(
        self,
        http_client: ResilientHttpClient | None = None,
        *,
        username: str = DEFAULT_INSTAGRAM_USERNAME,
        instagram_url: str = DEFAULT_INSTAGRAM_URL,
        graph_api_url: str = DEFAULT_GRAPH_API_URL,
        web_profile_url: str = DEFAULT_WEB_PROFILE_URL,
        access_token: str | None = None,
        session_cache: SessionCache | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        """Initialize the Instagram crawler.

        Args:
            http_client: Optional preconfigured ResilientHttpClient.
            username: Target Instagram username.
            instagram_url: Public Instagram web profile URL.
            graph_api_url: Instagram Graph API media endpoint.
            web_profile_url: Instagram web profile GraphQL endpoint.
            access_token: Optional Instagram Graph API access token.
            session_cache: Optional SessionCache instance.
            rate_limiter: Optional RateLimiter instance.
        """
        self.client = http_client or ResilientHttpClient()
        self.username = username
        self.instagram_url = instagram_url
        self.graph_api_url = graph_api_url
        self.web_profile_url = web_profile_url
        self.access_token = access_token
        self.cache = session_cache or SessionCache()
        self.rate_limiter = rate_limiter or RateLimiter()

    async def fetch_graph_api_posts(
        self,
        access_token: str | None = None,
    ) -> tuple[list[ParsedInstagramPost], str, str]:
        """Fetch posts using official Instagram Graph API.

        Args:
            access_token: Optional overriding access token.

        Returns:
            Tuple of (posts, payload, content_hash).
        """
        token = access_token or self.access_token
        if not token:
            msg = "Instagram Graph API access token is required"
            raise ValueError(msg)

        await self.rate_limiter.acquire()
        url = (
            f"{self.graph_api_url}?fields=id,caption,media_type,timestamp,permalink"
            f"&access_token={token}"
        )
        data, content_hash = await self.client.fetch_json(url)
        posts = parse_graph_api_response(data)
        return posts, json.dumps(data), content_hash

    async def fetch_web_api_posts(
        self,
    ) -> tuple[list[ParsedInstagramPost], str, str]:
        """Fetch posts using Instagram web profile JSON endpoint.

        Returns:
            Tuple of (posts, payload, content_hash).
        """
        await self.rate_limiter.acquire()
        headers = {
            "x-ig-app-id": IG_APP_ID,
            "Accept": "application/json",
        }
        data, content_hash = await self.client.fetch_json(
            self.web_profile_url,
            headers=headers,
        )
        if isinstance(data, dict) and (
            data.get("status") == "fail" or data.get("require_login")
        ):
            msg = "Instagram web profile requires login or is rate-limited"
            raise ValueError(msg)

        posts = parse_public_feed_json(data)
        return posts, json.dumps(data), content_hash

    async def fetch_html_posts(
        self,
    ) -> tuple[list[ParsedInstagramPost], str, str]:
        """Fetch and parse public HTML Instagram profile page.

        Returns:
            Tuple of (posts, payload, content_hash).
        """
        await self.rate_limiter.acquire()
        html_text, content_hash = await self.client.fetch_text(self.instagram_url)
        posts = parse_html_instagram_feed(html_text)
        return posts, html_text, content_hash

    def _try_parse_cached_payload(
        self,
        payload: str,
        content_type: str,
    ) -> list[ParsedInstagramPost]:
        """Attempt parsing cached payload based on content type."""
        if "application/json" in content_type:
            try:
                data = json.loads(payload)
            except (ValueError, TypeError):
                return []

            posts = parse_public_feed_json(data)
            if not posts:
                posts = parse_graph_api_response(data)

            return posts

        return parse_html_instagram_feed(payload)

    def _get_cached_posts(
        self,
        *,
        allow_stale: bool = False,
    ) -> tuple[list[ParsedInstagramPost], str, str, str] | None:
        """Retrieve and parse posts from session cache."""
        cached = self.cache.get("posts", allow_stale=allow_stale)
        if not cached:
            return None

        payload, chash, ctype = cached
        posts = self._try_parse_cached_payload(payload, ctype)
        return posts, payload, chash, ctype

    async def _try_graph_api(
        self,
    ) -> tuple[list[ParsedInstagramPost], str, str, str] | None:
        """Attempt fetching via Instagram Graph API."""
        if not self.access_token:
            return None

        try:
            posts, payload, chash = await self.fetch_graph_api_posts()
            if posts:
                self.cache.set("posts", payload, chash, "application/json")
                return posts, payload, chash, "application/json"
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            # Fall back to public web endpoints if Graph API fails.
            pass

        return None

    async def _try_web_api(
        self,
    ) -> tuple[list[ParsedInstagramPost], str, str, str] | None:
        """Attempt fetching via public web profile JSON endpoint."""
        try:
            posts, payload, chash = await self.fetch_web_api_posts()
            if posts:
                self.cache.set("posts", payload, chash, "application/json")
                return posts, payload, chash, "application/json"
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            # Fall back to HTML scraping if Web API fails.
            pass

        return None

    async def _try_html_scrape(
        self,
    ) -> tuple[list[ParsedInstagramPost], str, str, str] | None:
        """Attempt fetching via public HTML profile scraping."""
        try:
            posts, payload, chash = await self.fetch_html_posts()
            if posts:
                self.cache.set("posts", payload, chash, "text/html")
                return posts, payload, chash, "text/html"
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            # Return None if HTML scraping fails.
            pass

        return None

    async def _fetch_from_network(
        self,
        *,
        prefer_graph_api: bool,
    ) -> tuple[list[ParsedInstagramPost], str, str, str] | None:
        """Attempt fetching posts across available remote network endpoints."""
        if prefer_graph_api:
            graph_res = await self._try_graph_api()
            if graph_res is not None:
                return graph_res

        web_res = await self._try_web_api()
        if web_res is not None:
            return web_res

        return await self._try_html_scrape()

    async def fetch_posts(
        self,
        *,
        prefer_graph_api: bool = True,
        use_cache: bool = True,
    ) -> tuple[list[ParsedInstagramPost], str, str, str]:
        """Fetch Instagram posts with fallback and session caching.

        Args:
            prefer_graph_api: Whether to try Graph API first if token present.
            use_cache: Whether to return fresh cached response if available.

        Returns:
            Tuple of (posts, payload, content_hash, content_type).
        """
        if use_cache:
            fresh = self._get_cached_posts(allow_stale=False)
            if fresh is not None:
                return fresh

        res = await self._fetch_from_network(prefer_graph_api=prefer_graph_api)
        if res is not None:
            return res

        stale = self._get_cached_posts(allow_stale=True)
        if stale is not None:
            return stale

        return [], "", "", "none"

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
        code: str = "instagram",
    ) -> DataSourceModel:
        """Retrieve or register the social Instagram DataSourceModel."""
        source = session.scalar(
            select(DataSourceModel).where(DataSourceModel.source_code == code),
        )
        if source is None:
            source = DataSourceModel(
                source_code=code,
                name="ECU Hockey Instagram",
                source_url=self.instagram_url,
                source_type=DataSourceType.SOCIAL.value,
                priority_order=4,
                is_active=True,
            )
            session.add(source)
            session.flush()

        return source

    def _record_snapshot(
        self,
        session: Session,
        source: DataSourceModel,
        payload: str,
        content_hash: str,
        content_type: str,
    ) -> RawSnapshotModel | None:
        """Record raw payload snapshot if content is present."""
        if not payload or not content_hash:
            return None

        snapshot = RawSnapshotModel(
            source_id=source.id,
            url=self.instagram_url,
            content_hash=content_hash,
            content_type=content_type,
            payload=payload,
            captured_at=datetime.now(UTC),
        )
        session.add(snapshot)
        session.flush()
        return snapshot

    def _update_existing_games(
        self,
        session: Session,
        posts: Sequence[ParsedInstagramPost],
    ) -> int:
        """Cross-reference announcements against existing games and update DB."""
        games = list(session.scalars(select(GameModel)))
        modified = cross_reference_announcements_with_games(games, posts)
        return len(modified)

    @staticmethod
    def _get_or_create_opponent(
        session: Session,
        opp_name: str,
    ) -> TeamModel:
        """Retrieve or create opponent team record in database."""
        opp_team = session.scalar(
            select(TeamModel).where(TeamModel.name == opp_name),
        )
        if not opp_team:
            opp_team = TeamModel(
                name=opp_name,
                city="Unknown",
                state="NC",
                division="ACHA M2",
                conference="ACCHL",
            )
            session.add(opp_team)
            session.flush()

        return opp_team

    def _resolve_home_away_ids(
        self,
        session: Session,
        *,
        is_home: bool,
        ecu_id: int,
        opp_name: str,
    ) -> tuple[int, int]:
        """Resolve database IDs for home and away teams."""
        opp_team = self._get_or_create_opponent(session, opp_name)
        if is_home:
            return ecu_id, opp_team.id

        return opp_team.id, ecu_id

    @staticmethod
    def _matches_existing_game(
        session: Session,
        post: ParsedInstagramPost,
    ) -> bool:
        """Check if post corresponds to an existing game in database."""
        games = session.scalars(select(GameModel))
        return any(matches_post_to_game(game, post) for game in games)

    def _is_unpersisted_candidate(
        self,
        session: Session,
        post: ParsedInstagramPost,
        game_id: str,
    ) -> bool:
        """Check if post is a candidate for new game persistence."""
        if self._matches_existing_game(session, post):
            return False

        existing = session.scalar(
            select(GameModel).where(GameModel.game_id == game_id),
        )
        return existing is None

    def _persist_new_game_from_post(
        self,
        session: Session,
        post: ParsedInstagramPost,
        ecu_id: int,
        season: str,
    ) -> bool:
        """Synthesize and persist new game record if date and opponent resolved."""
        rec = post.to_parsed_game_record(season=season)
        if rec is None or not post.opponent_name:
            return False

        if not self._is_unpersisted_candidate(session, post, rec.game_id):
            return False

        home_id, away_id = self._resolve_home_away_ids(
            session,
            is_home=rec.is_home,
            ecu_id=ecu_id,
            opp_name=post.opponent_name,
        )
        new_game = GameModel(
            game_id=rec.game_id,
            home_team_id=home_id,
            away_team_id=away_id,
            start_time=rec.start_time,
            venue=rec.venue,
            status=rec.status.value,
            season=season,
        )
        session.add(new_game)
        session.flush()
        return True

    def _get_ecu_team_id(self, session: Session) -> int:
        """Find or create ECU team in database."""
        ecu = session.scalar(
            select(TeamModel).where(TeamModel.name == "East Carolina University"),
        )
        if not ecu:
            ecu = TeamModel(
                name="East Carolina University",
                city="Greenville",
                state="NC",
                division="ACHA M2",
                conference="ACCHL",
            )
            session.add(ecu)
            session.flush()

        return ecu.id

    def _persist_new_games(
        self,
        session: Session,
        posts: Sequence[ParsedInstagramPost],
        season: str,
    ) -> int:
        """Persist new game records from Instagram announcements."""
        ecu_id = self._get_ecu_team_id(session)
        created = 0
        for post in posts:
            if self._persist_new_game_from_post(session, post, ecu_id, season):
                created += 1

        return created

    async def _execute_sync_fetch(
        self,
        session: Session,
        source: DataSourceModel,
        *,
        prefer_graph_api: bool,
        use_cache: bool,
        season: str,
    ) -> tuple[int, int, bool]:
        """Fetch posts, store snapshot, persist games, and return counts."""
        posts, payload, chash, ctype = await self.fetch_posts(
            prefer_graph_api=prefer_graph_api,
            use_cache=use_cache,
        )
        self._record_snapshot(session, source, payload, chash, ctype)
        updated = self._update_existing_games(session, posts)
        created = self._persist_new_games(session, posts, season)
        return created, updated, bool(posts)

    async def sync(
        self,
        session: Session,
        *,
        prefer_graph_api: bool = True,
        use_cache: bool = True,
        season: str = "2026-2027",
    ) -> tuple[int, int, SyncAuditModel]:
        """Perform full ingestion sync for Instagram announcements.

        Args:
            session: Active SQLAlchemy database session.
            prefer_graph_api: Whether to prioritize Graph API if token set.
            use_cache: Whether to use cached data.
            season: Target athletic season string.

        Returns:
            Tuple of (records_created, records_updated, audit_record).
        """
        started_at = datetime.now(UTC)
        sync_id = (
            f"instagram-{started_at.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
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
            created, updated, has_posts = await self._execute_sync_fetch(
                session,
                source,
                prefer_graph_api=prefer_graph_api,
                use_cache=use_cache,
                season=season,
            )
            st = SyncStatus.SUCCESS if has_posts else SyncStatus.PARTIAL
            err = None if has_posts else "No posts retrieved from Instagram endpoints"
            self._finalize_audit(audit, started_at, st, error_message=err)
            audit.games_created = created
            audit.games_updated = updated
            session.commit()
        except Exception as exc:
            self._finalize_audit(audit, started_at, SyncStatus.FAILURE, str(exc))
            session.commit()
            raise

        return created, updated, audit


__all__ = [
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_RATE_LIMIT_INTERVAL",
    "CacheEntry",
    "InstagramCrawler",
    "RateLimiter",
    "SessionCache",
]

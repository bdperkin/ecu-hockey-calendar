"""Team logo asset manager, cache handler, and synchronization service."""

from __future__ import annotations

import email.utils
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from sqlalchemy import select

from ecu_hockey_calendar.ingestion.client import (
    ResilientHttpClient,
    compute_content_hash,
)
from ecu_hockey_calendar.storage.models import TeamModel

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ecu_hockey_calendar.ingestion.opponent_config import (
        OpponentDirectory,
        OpponentEndpointConfig,
    )

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".png", ".svg", ".jpg", ".jpeg", ".webp"}
DEFAULT_PACKAGE_STATIC_DIR = Path(__file__).resolve().parent.parent / "api" / "static"


def team_name_to_slug(name: str) -> str:
    """Convert a team name into a normalized filesystem-safe slug.

    Args:
        name: Collegiate athletic team name.

    Returns:
        Hyphenated lowercase slug.
    """
    cleaned = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s_]+", "-", cleaned).strip("-")
    return slug or "team"


def _extract_logo_extension(url: str, default: str = ".png") -> str:
    """Extract and validate file extension from URL path.

    Args:
        url: Remote logo asset URL.
        default: Fallback extension if missing or unrecognized.

    Returns:
        Validated lowercase file extension including leading dot.
    """
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    return ext if ext in SUPPORTED_EXTENSIONS else default


def _get_http_mtime_header(path: Path) -> dict[str, str]:
    """Generate conditional HTTP request header from file modification time."""
    if not path.is_file():
        return {}

    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return {"If-Modified-Since": email.utils.format_datetime(mtime, usegmt=True)}


def _save_logo_bytes(paths: list[Path], content: bytes) -> None:
    """Save binary content to target filesystem paths ensuring directories exist."""
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


@dataclass(frozen=True, slots=True)
class LogoSyncResult:
    """Result of a team logo asset download or update check."""

    team_name: str
    slug: str
    remote_url: str
    local_path: Path | None
    local_web_url: str | None
    updated: bool
    error: str | None = None


def _find_team_by_name_or_aliases(
    session: Session,
    opponent: OpponentEndpointConfig,
) -> TeamModel | None:
    """Find team model by canonical name or configured aliases."""
    team = session.scalar(
        select(TeamModel).where(TeamModel.name == opponent.canonical_name),
    )
    if team is not None:
        return team

    names = (opponent.canonical_name, *opponent.aliases)
    norm_targets = {team_name_to_slug(n) for n in names}
    for existing in session.scalars(select(TeamModel)):
        if team_name_to_slug(existing.name) in norm_targets:
            return existing

    return None


def _update_team_model_logos(
    session: Session,
    opponent: OpponentEndpointConfig,
    local_web_url: str | None,
) -> None:
    """Update team model with remote and local logo URLs."""
    team = _find_team_by_name_or_aliases(session, opponent)
    if team is None:
        team = TeamModel(
            name=opponent.canonical_name,
            city="Unknown",
            state="NC",
        )
        session.add(team)

    team.remote_logo_url = opponent.logo_url
    if local_web_url is not None:
        team.local_logo_url = local_web_url

    team.logo_url = team.remote_logo_url or team.local_logo_url
    session.flush()


def _resolve_root_logos_dir(
    static_dir: Path | None,
    root_static_dir: Path | None,
) -> Path | None:
    """Resolve secondary static logos directory if applicable."""
    if root_static_dir is not None:
        return root_static_dir / "logos"

    if static_dir is not None:
        return None

    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    candidate = repo_root / "static"
    if candidate.is_dir():
        return candidate / "logos"

    return None


def _is_cache_identical(local_path: Path, content: bytes) -> bool:
    """Check if local file exists and matches new content hash."""
    if not local_path.is_file():
        return False

    return compute_content_hash(local_path.read_bytes()) == compute_content_hash(
        content,
    )


def _build_error_result(
    team_name: str,
    slug: str,
    remote_url: str,
    local_path: Path,
    web_url: str,
    *,
    exc: Exception,
) -> LogoSyncResult:
    """Construct a failed LogoSyncResult."""
    cached = local_path.is_file()
    return LogoSyncResult(
        team_name=team_name,
        slug=slug,
        remote_url=remote_url,
        local_path=local_path if cached else None,
        local_web_url=web_url if cached else None,
        updated=False,
        error=str(exc),
    )


class LogoAssetManager:
    """Manages downloading, local caching, and synchronization of team logos."""

    def __init__(
        self,
        static_dir: Path | None = None,
        http_client: ResilientHttpClient | None = None,
        root_static_dir: Path | None = None,
    ) -> None:
        """Initialize the logo asset manager.

        Args:
            static_dir: Optional root static directory (defaults to package static).
            http_client: Optional ResilientHttpClient instance.
            root_static_dir: Optional second static root (e.g. repo static/ dir).
        """
        self.static_dir = (
            static_dir if static_dir is not None else DEFAULT_PACKAGE_STATIC_DIR
        )
        self.logos_dir = self.static_dir / "logos"
        self.logos_dir.mkdir(parents=True, exist_ok=True)
        self.client = http_client if http_client is not None else ResilientHttpClient()
        self.root_logos_dir = _resolve_root_logos_dir(
            static_dir,
            root_static_dir,
        )
        if self.root_logos_dir is not None:
            self.root_logos_dir.mkdir(parents=True, exist_ok=True)

    def get_local_web_url(self, slug: str, ext: str = ".png") -> str:
        """Return relative web URL for a logo asset.

        Args:
            slug: Team slug.
            ext: File extension including dot.

        Returns:
            Relative path string starting with /static/logos/.
        """
        return f"/static/logos/{slug}{ext}"

    def get_local_file_path(self, slug: str, ext: str = ".png") -> Path:
        """Return primary local filesystem Path for a logo asset.

        Args:
            slug: Team slug.
            ext: File extension including dot.

        Returns:
            Absolute Path to cached logo file.
        """
        return self.logos_dir / f"{slug}{ext}"

    def _resolve_target_paths(self, filename: str) -> list[Path]:
        """Resolve all filesystem target destinations for a logo filename."""
        destinations = [self.logos_dir / filename]
        if self.root_logos_dir is not None:
            destinations.append(self.root_logos_dir / filename)

        return destinations

    async def _fetch_and_cache(
        self,
        local_path: Path,
        remote_url: str,
        filename: str,
    ) -> bool:
        """Fetch remote logo asset and cache locally if modified.

        Returns:
            True if file was newly written or updated, False if unchanged.
        """
        headers = _get_http_mtime_header(local_path)
        content, _, status = await self.client.fetch_bytes(
            remote_url,
            headers=headers,
        )
        if status == HTTPStatus.NOT_MODIFIED.value:
            return False

        if not content:
            return False

        if _is_cache_identical(local_path, content):
            return False

        targets = self._resolve_target_paths(filename)
        _save_logo_bytes(targets, content)
        return True

    async def sync_logo(
        self,
        team_name: str,
        remote_url: str,
    ) -> LogoSyncResult:
        """Synchronize an individual team logo asset with local cache.

        Args:
            team_name: Canonical team name.
            remote_url: Remote logo asset URL.

        Returns:
            LogoSyncResult describing outcome.
        """
        slug = team_name_to_slug(team_name)
        ext = _extract_logo_extension(remote_url)
        filename = f"{slug}{ext}"
        local_path = self.get_local_file_path(slug, ext)
        web_url = self.get_local_web_url(slug, ext)

        try:
            updated = await self._fetch_and_cache(
                local_path,
                remote_url,
                filename,
            )
            return LogoSyncResult(
                team_name=team_name,
                slug=slug,
                remote_url=remote_url,
                local_path=local_path,
                local_web_url=web_url,
                updated=updated,
            )
        except Exception as exc:  # noqa: BLE001 # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to sync logo for %s (%s): %s",
                team_name,
                remote_url,
                exc,
            )
            return _build_error_result(
                team_name=team_name,
                slug=slug,
                remote_url=remote_url,
                local_path=local_path,
                web_url=web_url,
                exc=exc,
            )

    async def sync_directory_logos(
        self,
        directory: OpponentDirectory,
        session: Session,
    ) -> list[LogoSyncResult]:
        """Synchronize logos for all configured opponents in directory.

        Args:
            directory: OpponentDirectory with configured opponent endpoints.
            session: Active database session.

        Returns:
            List of LogoSyncResult instances.
        """
        results: list[LogoSyncResult] = []
        for opponent in directory.opponents:
            if not opponent.logo_url:
                continue

            result = await self.sync_logo(opponent.canonical_name, opponent.logo_url)
            results.append(result)
            _update_team_model_logos(
                session,
                opponent,
                result.local_web_url,
            )

        return results

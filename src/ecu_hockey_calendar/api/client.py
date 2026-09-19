"""HTTP client for interacting with remote ECU Hockey Calendar API instances."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Self

import httpx

from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.storage.models import SyncStatus
from ecu_hockey_calendar.version import __version__

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import TracebackType

DEFAULT_USER_AGENT = (
    f"ECUHockeyCLI/{__version__} (+https://github.com/bdperkin/ecu-hockey-calendar)"
)
DEFAULT_TIMEOUT = 15.0


class RemoteApiError(Exception):
    """Base exception for remote API client operations."""


class RemoteApiAuthError(RemoteApiError):
    """Raised when remote API responds with 401 Unauthorized or 403 Forbidden."""


@dataclass(frozen=True, slots=True)
class RemoteSyncAudit:
    """Lightweight representation of remote sync audit record for CLI rendering."""

    sync_cycle_id: str | int
    status: SyncStatus
    started_at: datetime | None
    duration_ms: int | None
    games_created: int = 0
    games_updated: int = 0
    games_deleted: int = 0
    conflicts_detected: int = 0


def _parse_team(raw: object, *, default_name: str, default_city: str) -> Team:
    """Parse team dictionary or name string into domain Team object."""
    if isinstance(raw, dict):
        return Team(
            name=str(raw.get("name", default_name)),
            city=str(raw.get("city", default_city)),
            state=str(raw.get("state", "NC")),
            division=str(raw.get("division", "ACHA M2")),
            conference=str(raw.get("conference", "ACCHL")),
        )

    return Team(
        name=str(raw or default_name),
        city=default_city,
        state="NC",
    )


def _parse_game_datetime(raw_value: object) -> datetime:
    """Parse ISO datetime string into UTC datetime object."""
    raw_str = str(raw_value or "")
    if not raw_str:
        return datetime.now(UTC)

    if raw_str.endswith("Z"):
        raw_str = raw_str[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(raw_str)
    except ValueError:
        return datetime.now(UTC)


def _parse_game_result(data: Mapping[str, Any]) -> GameResult:
    """Extract and parse GameResult enum from fixture data."""
    raw = str(data.get("result") or data.get("status") or "SCHEDULED").upper()
    try:
        return GameResult(raw)
    except ValueError:
        return GameResult.SCHEDULED


def parse_game_dict(data: Mapping[str, Any]) -> Game:
    """Parse JSON dictionary from schedule endpoint into domain Game dataclass.

    Args:
        data: Dictionary representation of a game fixture.

    Returns:
        Instantiated domain Game object.
    """
    home_team = _parse_team(
        data.get("home_team"),
        default_name="East Carolina University",
        default_city="Greenville",
    )
    away_team = _parse_team(
        data.get("away_team"),
        default_name="Unknown Opponent",
        default_city="Unknown City",
    )
    start_dt = _parse_game_datetime(data.get("start_time"))
    result_enum = _parse_game_result(data)

    home_score = data.get("home_score")
    away_score = data.get("away_score")
    raw_start = str(data.get("start_time", ""))

    return Game(
        game_id=str(data.get("game_id", f"game_{abs(hash(raw_start))}")),
        home_team=home_team,
        away_team=away_team,
        start_time=start_dt,
        venue=str(data.get("venue") or "Unknown Venue"),
        result=result_enum,
        home_score=int(home_score) if home_score is not None else None,
        away_score=int(away_score) if away_score is not None else None,
    )


def _parse_optional_datetime(raw: object) -> datetime | None:
    """Parse optional ISO datetime string or return None."""
    if not raw:
        return None

    raw_str = str(raw)
    if raw_str.endswith("Z"):
        raw_str = raw_str[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(raw_str)
    except ValueError:
        return None


def _parse_audit_status(status_raw: object) -> SyncStatus:
    """Parse SyncStatus enum with fallback to SUCCESS."""
    try:
        return SyncStatus(str(status_raw or "SUCCESS").upper())
    except ValueError:
        return SyncStatus.SUCCESS


def _parse_audit_record(audit_data: Mapping[str, Any] | None) -> RemoteSyncAudit | None:
    """Parse remote audit payload into RemoteSyncAudit."""
    if not audit_data:
        return None

    status_enum = _parse_audit_status(audit_data.get("status"))
    started_dt = _parse_optional_datetime(audit_data.get("started_at"))
    cycle_id = str(
        audit_data.get("audit_id") or audit_data.get("sync_cycle_id", "remote"),
    )

    return RemoteSyncAudit(
        sync_cycle_id=cycle_id,
        status=status_enum,
        started_at=started_dt,
        duration_ms=audit_data.get("duration_ms"),
        games_created=int(audit_data.get("games_created", 0)),
        games_updated=int(audit_data.get("games_updated", 0)),
        games_deleted=int(audit_data.get("games_deleted", 0)),
        conflicts_detected=int(audit_data.get("conflicts_detected", 0)),
    )


def _build_schedule_params(
    *,
    season: str | None,
    home_only: bool,
    opponent: str | None,
    status: str | None,
) -> dict[str, Any]:
    """Construct query parameter dictionary for schedule games endpoint."""
    pairs = [
        ("season", season),
        ("home_only", "true" if home_only else None),
        ("opponent", opponent),
        ("status", status),
    ]
    return {k: v for k, v in pairs if v is not None}


def _parse_status_scraper(scraper: Mapping[str, Any]) -> dict[str, Any]:
    """Parse scraper entry from /health response into status dictionary."""
    last_raw = scraper.get("last_scraped_at")
    return {
        "source_code": scraper.get("source_code", "unknown"),
        "name": scraper.get("name", "Unknown Source"),
        "source_type": scraper.get("source_type", "primary_sot"),
        "is_active": scraper.get("is_active", True),
        "last_scraped_at": _parse_optional_datetime(last_raw) or last_raw,
    }


def _build_conflicts_params(
    *,
    severity: str | None,
    game_id: str | None,
    field_name: str | None,
    review_only: bool,
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """Construct query parameter dictionary for conflicts endpoint."""
    pairs: list[tuple[str, Any]] = [
        ("severity", severity),
        ("game_id", game_id),
        ("field", field_name),
        ("requires_review", "true" if review_only else None),
        ("limit", limit),
        ("offset", offset),
    ]
    return {k: v for k, v in pairs if v is not None}


def _handle_unsupported_sync(resp: httpx.Response) -> dict[str, Any]:
    """Parse 501 Not Implemented response payload for sync trigger."""
    detail = (
        "On-demand synchronization trigger is not implemented in this "
        "deployment. Synchronization runs via scheduled cron."
    )
    try:
        data = resp.json()
        detail = data.get("detail", detail)
    except (ValueError, KeyError):
        # Fall back to standard unconfigured sync message if payload is non-JSON
        # or lacks a custom detail message.
        pass

    return {
        "status": "unsupported",
        "status_code": HTTPStatus.NOT_IMPLEMENTED.value,
        "message": detail,
    }


def _process_sync_response(resp: httpx.Response) -> dict[str, Any]:
    """Validate status and return JSON payload from sync trigger endpoint."""
    if resp.status_code in (401, 403):
        msg = (
            f"Authentication failed ({resp.status_code}): "
            "Valid admin token required to trigger sync."
        )
        raise RemoteApiAuthError(msg)

    if resp.status_code == HTTPStatus.NOT_IMPLEMENTED:
        return _handle_unsupported_sync(resp)

    resp.raise_for_status()
    return resp.json()


def _handle_resolve_response(resp: httpx.Response) -> dict[str, Any]:
    """Validate status and parse JSON response for conflict resolution."""
    if resp.status_code in (401, 403):
        msg = (
            f"Authentication failed ({resp.status_code}): "
            "Valid admin token required to resolve conflicts."
        )
        raise RemoteApiAuthError(msg)

    resp.raise_for_status()
    return resp.json()


def _build_resolve_body(  # pylint: disable=too-many-arguments
    field: str | None,
    value: str | None,
    accept_source: str | None,
    notes: str | None,
    resolved_by: str,
) -> dict[str, Any]:
    """Construct filtered JSON payload for conflict resolution."""
    payload = {
        "field": field,
        "value": value,
        "accept_source": accept_source,
        "notes": notes,
        "resolved_by": resolved_by,
    }
    return {k: v for k, v in payload.items() if v is not None}


def _resolve_export_endpoint(
    format_type: str,
    *,
    embed: bool,
) -> tuple[str, str, bool, str]:
    """Resolve endpoint path, MIME accept header, and binary flag for format."""
    endpoint_map: dict[str, tuple[str, str, bool]] = {
        "ics": ("/schedule.ics", "text/calendar", False),
        "json": ("/schedule.json", "application/json", False),
        "csv": ("/schedule.csv", "text/csv", False),
        "pdf": ("/schedule.pdf", "application/pdf", True),
        "html": ("/schedule/embed" if embed else "/schedule", "text/html", False),
        "rss": ("/schedule.rss", "application/rss+xml", False),
        "atom": ("/schedule.atom", "application/atom+xml", False),
    }

    norm_fmt = format_type.lower().strip(".")
    if norm_fmt not in endpoint_map:
        msg = f"Unsupported export format '{format_type}'."
        raise RemoteApiError(msg)

    path, accept, is_binary = endpoint_map[norm_fmt]
    return path, accept, is_binary, norm_fmt


def _format_bool_param(*, value: bool | None) -> str | None:
    """Format boolean query parameter as string or None."""
    if value is True:
        return "true"

    if value is False:
        return "false"

    return None


def _build_export_params(
    *,
    season: str | None,
    opponent: str | None,
    home_only: bool,
    future_only: bool,
    include_past: bool | None = None,
    status: str | None,
) -> dict[str, Any]:
    """Construct query parameter dictionary for export endpoint."""
    pairs = [
        ("season", season),
        ("opponent", opponent),
        ("home_only", "true" if home_only else None),
        ("future_only", "true" if future_only else None),
        ("include_past", _format_bool_param(value=include_past)),
        ("status", status),
    ]
    return {k: v for k, v in pairs if v is not None}


class RemoteApiClient:
    """Synchronous HTTP client for interacting with remote ECU Hockey Calendar API."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        """Initialize remote API client.

        Args:
            base_url: Base URL of remote ECU Hockey API (e.g., 'https://ecu-hockey-api.onrender.com').
            token: Optional administrative authentication Bearer token.
            timeout: HTTP request timeout in seconds.
            transport: Optional custom httpx BaseTransport (useful for testing).
            user_agent: User-Agent header value.
        """
        self.base_url = base_url.rstrip("/")
        self.token = token.strip() if token else None
        self.timeout = timeout
        self.transport = transport
        self.user_agent = user_agent

    def close(self) -> None:
        """Release underlying HTTP client resources."""

    def _get_headers(self, *, accept: str = "application/json") -> dict[str, str]:
        """Construct standard HTTP request headers.

        Args:
            accept: Accepted media type string.

        Returns:
            Dictionary of request headers.
        """
        headers = {
            "User-Agent": self.user_agent,
            "Accept": accept,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            headers["X-API-Key"] = self.token

        return headers

    def _create_client(self) -> httpx.Client:
        """Construct configured httpx.Client context."""
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self.transport,
            follow_redirects=True,
        )

    def get_health(self) -> dict[str, Any]:
        """Fetch health diagnostics from /health.

        Returns:
            Structured health dictionary from the remote API.

        Raises:
            RemoteApiError: On network or protocol errors.
        """
        with self._create_client() as client:
            try:
                resp = client.get(
                    "/health",
                    params={"format": "json"},
                    headers=self._get_headers(),
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                msg = f"HTTP error fetching health ({exc.response.status_code}): {exc}"
                raise RemoteApiError(msg) from exc
            except httpx.RequestError as exc:
                msg = f"Network error connecting to {self.base_url}: {exc}"
                raise RemoteApiError(msg) from exc

    def get_sync_status(self) -> dict[str, Any]:
        """Fetch sync status and telemetry from /api/v1/sync/status.

        Returns:
            Structured sync telemetry dictionary from the remote API.

        Raises:
            RemoteApiError: On network or protocol errors.
        """
        with self._create_client() as client:
            try:
                resp = client.get(
                    "/api/v1/sync/status",
                    params={"format": "json"},
                    headers=self._get_headers(),
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                msg = (
                    f"HTTP error fetching sync status "
                    f"({exc.response.status_code}): {exc}"
                )
                raise RemoteApiError(msg) from exc
            except httpx.RequestError as exc:
                msg = f"Network error connecting to {self.base_url}: {exc}"
                raise RemoteApiError(msg) from exc

    def get_games(
        self,
        *,
        season: str | None = None,
        home_only: bool = False,
        opponent: str | None = None,
        status: str | None = None,
    ) -> list[Game]:
        """Fetch schedule games collection from /api/schedule.json.

        Parses JSON response into domain models.

        Args:
            season: Optional season filter string.
            home_only: If True, only home matches.
            opponent: Optional opponent substring.
            status: Optional match status filter.

        Returns:
            List of domain Game objects.

        Raises:
            RemoteApiError: On network or protocol errors.
        """
        params = _build_schedule_params(
            season=season,
            home_only=home_only,
            opponent=opponent,
            status=status,
        )

        with self._create_client() as client:
            try:
                resp = client.get(
                    "/api/schedule.json",
                    params=params,
                    headers=self._get_headers(),
                )
                resp.raise_for_status()
                payload = resp.json()
            except httpx.HTTPStatusError as exc:
                msg = (
                    f"HTTP error fetching schedule games "
                    f"({exc.response.status_code}): {exc}"
                )
                raise RemoteApiError(msg) from exc
            except httpx.RequestError as exc:
                msg = f"Network error connecting to {self.base_url}: {exc}"
                raise RemoteApiError(msg) from exc

        if isinstance(payload, list):
            return [parse_game_dict(g) for g in payload]

        return []

    def get_status_data(
        self,
        *,
        season: str | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[Game]]:
        """Fetch consolidated status dataset from remote API.

        Queries health, sync status, and schedule games.

        Args:
            season: Optional season filter string.

        Returns:
            Tuple of (telemetry_dict, sources_list, games_list).
        """
        health = self.get_health()
        sync_payload = self.get_sync_status()
        games = self.get_games(season=season)

        telemetry: dict[str, Any] = {
            "total_cycles": sync_payload.get("total_syncs", 0),
            "last_success_at": _parse_optional_datetime(
                sync_payload.get("last_successful_sync"),
            ),
            "latest_audit": _parse_audit_record(sync_payload.get("last_sync")),
            "status": sync_payload.get("status", "idle"),
        }
        sources = [_parse_status_scraper(s) for s in health.get("scrapers", [])]
        return telemetry, sources, games

    def get_conflicts(
        self,
        *,
        severity: str | None = None,
        game_id: str | None = None,
        field_name: str | None = None,
        review_only: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        """Fetch detected schedule conflicts from /api/v1/conflicts.

        Args:
            severity: Optional conflict severity ('warning', 'critical').
            game_id: Optional game ID filter string.
            field_name: Optional mismatched attribute name filter string.
            review_only: If True, returns only items requiring manual review.
            limit: Optional maximum number of conflict records to return.
            offset: Optional number of conflict records to skip for pagination.

        Returns:
            Structured dictionary containing list of conflict objects.

        Raises:
            RemoteApiAuthError: If authentication fails.
            RemoteApiError: On network or protocol errors.
        """
        params = _build_conflicts_params(
            severity=severity,
            game_id=game_id,
            field_name=field_name,
            review_only=review_only,
            limit=limit,
            offset=offset,
        )

        with self._create_client() as client:
            try:
                resp = client.get(
                    "/api/v1/conflicts",
                    params=params,
                    headers=self._get_headers(),
                )
                if resp.status_code in (401, 403):
                    msg = (
                        f"Authentication failed ({resp.status_code}): "
                        "Valid admin token required to access conflicts."
                    )
                    raise RemoteApiAuthError(msg)

                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                msg = (
                    f"HTTP error fetching conflicts ({exc.response.status_code}): {exc}"
                )
                raise RemoteApiError(msg) from exc
            except httpx.RequestError as exc:
                msg = f"Network error connecting to {self.base_url}: {exc}"
                raise RemoteApiError(msg) from exc

    def resolve_conflict(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        conflict_id: str,
        *,
        field_name: str | None = None,
        field: str | None = None,
        value: str | None = None,
        accept_source: str | None = None,
        notes: str | None = None,
        resolved_by: str = "admin",
    ) -> dict[str, Any]:
        """Resolve a conflict via POST /api/v1/conflicts/{conflict_id}/resolve.

        Args:
            conflict_id: Identifier of conflict or canonical game ID.
            field_name: Optional target field to override.
            field: Optional alias for field_name.
            value: Optional override value.
            accept_source: Optional source whose data is accepted.
            notes: Optional resolution documentation.
            resolved_by: Identity of admin user.

        Returns:
            Dictionary response from the API.

        Raises:
            RemoteApiAuthError: If authentication fails.
            RemoteApiError: On network or HTTP errors.
        """
        target_field = field or field_name
        body = _build_resolve_body(
            target_field,
            value,
            accept_source,
            notes,
            resolved_by,
        )
        url = f"/api/v1/conflicts/{conflict_id}/resolve"
        with self._create_client() as client:
            try:
                resp = client.post(url, json=body, headers=self._get_headers())
                return _handle_resolve_response(resp)
            except httpx.HTTPStatusError as exc:
                msg = (
                    f"HTTP error resolving conflict ({exc.response.status_code}): {exc}"
                )
                raise RemoteApiError(msg) from exc
            except httpx.RequestError as exc:
                msg = f"Network error connecting to {self.base_url}: {exc}"
                raise RemoteApiError(msg) from exc

    def trigger_sync(self, *, source: str | None = None) -> dict[str, Any]:
        """Dispatch on-demand sync request to POST /api/v1/sync/trigger.

        Args:
            source: Optional specific source code to synchronize.

        Returns:
            Dictionary containing trigger status and execution message.

        Raises:
            RemoteApiAuthError: If authentication fails.
            RemoteApiError: On network or protocol errors.
        """
        params = {"source": source} if source else {}

        with self._create_client() as client:
            try:
                resp = client.post(
                    "/api/v1/sync/trigger",
                    params=params,
                    headers=self._get_headers(),
                )
                return _process_sync_response(resp)
            except httpx.HTTPStatusError as exc:
                msg = f"HTTP error triggering sync ({exc.response.status_code}): {exc}"
                raise RemoteApiError(msg) from exc
            except httpx.RequestError as exc:
                msg = f"Network error connecting to {self.base_url}: {exc}"
                raise RemoteApiError(msg) from exc

    def fetch_export(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        format_type: str,
        *,
        season: str | None = None,
        opponent: str | None = None,
        home_only: bool = False,
        future_only: bool = False,
        include_past: bool | None = None,
        status: str | None = None,
        embed: bool = False,
    ) -> str | bytes:
        """Fetch pre-rendered export artifact from remote API.

        Args:
            format_type: Serialization format ('ics', 'json', 'csv', 'html',
                'pdf', 'rss', 'atom').
            season: Optional season filter string.
            opponent: Optional opponent substring.
            home_only: If True, home matches only.
            future_only: If True, future matches only.
            include_past: If False, future matches only (negation of future_only).
            status: Optional status filter.
            embed: If True and format is html, fetch embed widget.

        Returns:
            String content for text formats or bytes for PDF format.

        Raises:
            RemoteApiError: On network or unsupported format errors.
        """
        path, accept, is_binary, norm_fmt = _resolve_export_endpoint(
            format_type,
            embed=embed,
        )
        resolved_future_only = (
            not include_past if include_past is not None else future_only
        )
        params = _build_export_params(
            season=season,
            opponent=opponent,
            home_only=home_only,
            future_only=resolved_future_only,
            include_past=include_past,
            status=status,
        )

        with self._create_client() as client:
            try:
                resp = client.get(
                    path,
                    params=params,
                    headers=self._get_headers(accept=accept),
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                msg = (
                    f"HTTP error fetching {norm_fmt} export "
                    f"({exc.response.status_code}): {exc}"
                )
                raise RemoteApiError(msg) from exc
            except httpx.RequestError as exc:
                msg = f"Network error connecting to {self.base_url}: {exc}"
                raise RemoteApiError(msg) from exc

            return resp.content if is_binary else resp.text

    def __enter__(self) -> Self:
        """Enter client context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit client context manager."""
        self.close()


__all__ = [
    "DEFAULT_TIMEOUT",
    "DEFAULT_USER_AGENT",
    "RemoteApiAuthError",
    "RemoteApiClient",
    "RemoteApiError",
    "RemoteSyncAudit",
    "_parse_audit_record",
    "_parse_optional_datetime",
    "parse_game_dict",
]

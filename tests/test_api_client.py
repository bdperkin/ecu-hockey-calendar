"""Unit tests for RemoteApiClient and remote API communication models."""

from __future__ import annotations

# pylint: disable=protected-access,unused-argument,too-many-public-methods
import json
from datetime import datetime
from typing import Any

import httpx
import pytest

from ecu_hockey_calendar.api.client import (
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    RemoteApiAuthError,
    RemoteApiClient,
    RemoteApiError,
    RemoteSyncAudit,
    _parse_audit_record,
    parse_game_dict,
)
from ecu_hockey_calendar.models import GameResult
from ecu_hockey_calendar.storage.models import SyncStatus


class TestGameParsing:
    """Tests for parse_game_dict helper function."""

    def test_parse_game_dict_full_nested_teams(self) -> None:
        """Verify parsing game with fully specified nested team objects."""
        raw = {
            "game_id": "game_123",
            "home_team": {
                "name": "East Carolina University",
                "city": "Greenville",
                "state": "NC",
                "division": "ACHA M2",
                "conference": "ACCHL",
            },
            "away_team": {
                "name": "NC State Icepack",
                "city": "Raleigh",
                "state": "NC",
                "division": "ACHA M2",
                "conference": "ACCHL",
                "logo_url": "https://example.com/ncstate.png",
            },
            "start_time": "2026-10-15T20:00:00Z",
            "venue": "The Factory Ice House",
            "result": "W",
            "home_score": 5,
            "away_score": 3,
        }
        game = parse_game_dict(raw)
        assert game.game_id == "game_123"
        assert game.home_team.name == "East Carolina University"
        assert game.home_team.logo_url is None
        assert game.away_team.name == "NC State Icepack"
        assert game.away_team.city == "Raleigh"
        assert game.away_team.logo_url == "https://example.com/ncstate.png"
        assert game.start_time.tzinfo is not None
        assert game.result == GameResult.WIN
        assert game.home_score == 5
        assert game.away_score == 3
        assert game.venue == "The Factory Ice House"

    def test_parse_game_dict_string_teams_and_defaults(self) -> None:
        """Verify parsing game with string team names and missing fields."""
        raw = {
            "home_team": "East Carolina University",
            "away_team": "Wake Forest",
            "start_time": "2026-11-01T15:00:00+00:00",
            "venue": "Wake Forest Rink",
            "status": "SCHEDULED",
        }
        game = parse_game_dict(raw)
        assert game.home_team.name == "East Carolina University"
        assert game.away_team.name == "Wake Forest"
        assert game.result == GameResult.SCHEDULED
        assert game.home_score is None
        assert game.away_score is None
        assert game.game_id.startswith("game_")

    def test_parse_game_dict_fallback_empty_payload(self) -> None:
        """Verify fallback defaults for completely empty payload."""
        game = parse_game_dict({})
        assert game.home_team.name == "East Carolina University"
        assert game.away_team.name == "Unknown Opponent"
        assert game.venue == "Unknown Venue"
        assert game.result == GameResult.SCHEDULED
        assert game.start_time.tzinfo is not None

    def test_parse_game_dict_invalid_datetime_and_status(self) -> None:
        """Verify handling of unparsable datetime and unknown status."""
        raw = {
            "start_time": "not-a-datetime",
            "result": "NON_EXISTENT_STATUS",
        }
        game = parse_game_dict(raw)
        assert game.result == GameResult.SCHEDULED
        assert isinstance(game.start_time, datetime)


class TestAuditParsing:
    """Tests for _parse_audit_record helper function."""

    def test_parse_audit_record_none(self) -> None:
        """Verify None returned when input is None or empty."""
        assert _parse_audit_record(None) is None
        assert _parse_audit_record({}) is None

    def test_parse_audit_record_valid(self) -> None:
        """Verify structured audit payload parsing."""
        raw = {
            "sync_cycle_id": "sync-12345",
            "status": "SUCCESS",
            "started_at": "2026-09-14T10:00:00Z",
            "duration_ms": 1250,
            "games_created": 3,
            "games_updated": 1,
            "games_deleted": 0,
            "conflicts_detected": 2,
        }
        audit = _parse_audit_record(raw)
        assert audit is not None
        assert isinstance(audit, RemoteSyncAudit)
        assert audit.sync_cycle_id == "sync-12345"
        assert audit.status == SyncStatus.SUCCESS
        assert audit.started_at is not None
        assert audit.duration_ms == 1250
        assert audit.games_created == 3
        assert audit.conflicts_detected == 2

    def test_parse_audit_record_fallbacks(self) -> None:
        """Verify fallback handling for unknown status and invalid timestamp."""
        raw = {
            "audit_id": "audit-999",
            "status": "WEIRD_STATUS",
            "started_at": "bad-date",
        }
        audit = _parse_audit_record(raw)
        assert audit is not None
        assert audit.sync_cycle_id == "audit-999"
        assert audit.status == SyncStatus.SUCCESS
        assert audit.started_at is None
        assert audit.games_created == 0

    def test_parse_audit_record_missing_started_at(self) -> None:
        """Verify audit parsing when started_at is omitted or None."""
        raw = {"status": "SUCCESS", "sync_cycle_id": "c1"}
        audit = _parse_audit_record(raw)
        assert audit is not None
        assert audit.started_at is None


class TestRemoteApiClientInitAndHeaders:
    """Tests for RemoteApiClient initialization and header generation."""

    def test_init_defaults(self) -> None:
        """Verify default attributes upon client initialization."""
        client = RemoteApiClient("https://ecu-hockey-api.onrender.com/")
        assert client.base_url == "https://ecu-hockey-api.onrender.com"
        assert client.token is None
        assert client.timeout == DEFAULT_TIMEOUT
        assert client.user_agent == DEFAULT_USER_AGENT

    def test_init_custom_token_and_timeout(self) -> None:
        """Verify client respects custom token, timeout, and whitespace stripping."""
        client = RemoteApiClient(
            "https://test.domain.com",
            token="  my-token-123  ",
            timeout=30.0,
            user_agent="CustomAgent/1.0",
        )
        assert client.token == "my-token-123"
        assert client.timeout == 30.0
        assert client.user_agent == "CustomAgent/1.0"

    def test_context_manager(self) -> None:
        """Verify context manager protocol (__enter__, __exit__, close)."""
        client = RemoteApiClient("https://test.domain.com")
        with client as c:
            assert c is client

        client.close()

    def test_headers_without_token(self) -> None:
        """Verify request headers when no token is configured."""
        client = RemoteApiClient("https://test.domain.com")
        headers = client._get_headers(accept="text/calendar")
        assert headers["Accept"] == "text/calendar"
        assert headers["User-Agent"] == DEFAULT_USER_AGENT
        assert "Authorization" not in headers
        assert "X-API-Key" not in headers

    def test_headers_with_token(self) -> None:
        """Verify request headers include Bearer and X-API-Key when token is present."""
        client = RemoteApiClient("https://test.domain.com", token="secret-token")
        headers = client._get_headers()
        assert headers["Authorization"] == "Bearer secret-token"
        assert headers["X-API-Key"] == "secret-token"


class TestRemoteApiClientMethods:
    """Tests for HTTP operations on RemoteApiClient using MockTransport."""

    def test_get_health_success(self) -> None:
        """Verify successful health payload retrieval."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/health"
            assert request.url.params.get("format") == "json"
            return httpx.Response(
                200,
                json={"status": "healthy", "database": "connected", "scrapers": []},
            )

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        health = client.get_health()
        assert health["status"] == "healthy"
        assert health["database"] == "connected"

    def test_get_health_http_error(self) -> None:
        """Verify RemoteApiError raised on HTTP error."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(RemoteApiError, match="HTTP error fetching health"):
            client.get_health()

    def test_get_health_network_error(self) -> None:
        """Verify RemoteApiError raised on network failure."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(RemoteApiError, match="Network error connecting"):
            client.get_health()

    def test_get_sync_status_success(self) -> None:
        """Verify successful sync status payload retrieval."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/sync/status"
            return httpx.Response(
                200,
                json={
                    "status": "idle",
                    "total_syncs": 42,
                    "last_sync": {"status": "SUCCESS", "sync_cycle_id": "c1"},
                    "last_successful_sync": "2026-09-14T08:00:00Z",
                },
            )

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        data = client.get_sync_status()
        assert data["total_syncs"] == 42
        assert data["status"] == "idle"

    def test_get_sync_status_http_error(self) -> None:
        """Verify RemoteApiError raised on sync status HTTP failure."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, text="Bad Gateway")

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(RemoteApiError, match="HTTP error fetching sync status"):
            client.get_sync_status()

    def test_get_sync_status_network_error(self) -> None:
        """Verify RemoteApiError raised on sync status network failure."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("Timed out")

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(RemoteApiError, match="Network error connecting"):
            client.get_sync_status()

    def test_get_games_success_and_filtering(self) -> None:
        """Verify retrieving games with query parameter filtering."""
        captured_params: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/schedule.json"
            captured_params.update(dict(request.url.params))
            return httpx.Response(
                200,
                json=[
                    {
                        "game_id": "g1",
                        "home_team": "East Carolina University",
                        "away_team": "UNC Wilmington",
                        "start_time": "2026-10-10T19:00:00Z",
                        "venue": "The Factory",
                        "result": "SCHEDULED",
                    },
                ],
            )

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        games = client.get_games(
            season="2026-2027",
            home_only=True,
            opponent="UNC",
            status="SCHEDULED",
        )
        assert len(games) == 1
        assert games[0].game_id == "g1"
        assert captured_params.get("season") == "2026-2027"
        assert captured_params.get("home_only") == "true"
        assert captured_params.get("opponent") == "UNC"
        assert captured_params.get("status") == "SCHEDULED"

    def test_get_games_empty_or_non_list(self) -> None:
        """Verify get_games returns empty list when payload is not a list."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": "none"})

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        assert client.get_games() == []

    def test_get_games_http_error(self) -> None:
        """Verify RemoteApiError raised on games query HTTP failure."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Database error")

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(RemoteApiError, match="HTTP error fetching schedule games"):
            client.get_games()

    def test_get_games_network_error(self) -> None:
        """Verify RemoteApiError raised on games query network failure."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadError("Socket reset")

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(RemoteApiError, match="Network error connecting"):
            client.get_games()

    def test_get_status_data_consolidated(self) -> None:
        """Verify get_status_data bundles health, sync status, and games."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(
                    200,
                    json={
                        "status": "healthy",
                        "scrapers": [
                            {
                                "source_code": "ecuhockey",
                                "name": "ECU Hockey",
                                "source_type": "primary_sot",
                                "is_active": True,
                                "last_scraped_at": "2026-09-14T09:00:00Z",
                            },
                            {
                                "source_code": "acchockey",
                                "name": "ACCHL",
                                "source_type": "league_acchl",
                                "is_active": True,
                                "last_scraped_at": "not-valid-date",
                            },
                        ],
                    },
                )

            if request.url.path == "/api/v1/sync/status":
                return httpx.Response(
                    200,
                    json={
                        "total_syncs": 10,
                        "status": "idle",
                        "last_sync": {
                            "audit_id": "audit-1",
                            "status": "SUCCESS",
                            "started_at": "2026-09-14T09:00:00Z",
                            "duration_ms": 500,
                        },
                        "last_successful_sync": "2026-09-14T09:00:00Z",
                    },
                )

            if request.url.path == "/api/schedule.json":
                return httpx.Response(200, json=[])

            return httpx.Response(404)

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        telemetry, sources, games = client.get_status_data(season="2026-2027")
        assert telemetry["total_cycles"] == 10
        assert telemetry["status"] == "idle"
        assert telemetry["last_success_at"] is not None
        assert len(sources) == 2
        assert sources[0]["source_code"] == "ecuhockey"
        assert sources[1]["source_code"] == "acchockey"
        assert len(games) == 0

    def test_get_status_data_invalid_last_success(self) -> None:
        """Verify get_status_data handles invalid last_successful_sync timestamp."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "healthy", "scrapers": []})

            if request.url.path == "/api/v1/sync/status":
                return httpx.Response(
                    200,
                    json={
                        "total_syncs": 0,
                        "status": "idle",
                        "last_sync": None,
                        "last_successful_sync": "invalid-timestamp",
                    },
                )

            if request.url.path == "/api/schedule.json":
                return httpx.Response(200, json=[])

            return httpx.Response(404)

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        telemetry, _sources, _games = client.get_status_data()
        assert telemetry["last_success_at"] is None

    def test_get_status_data_none_timestamps(self) -> None:
        """Verify get_status_data handles missing/None scraper and sync timestamps."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(
                    200,
                    json={
                        "status": "healthy",
                        "scrapers": [
                            {
                                "source_code": "ecuhockey",
                                "name": "ECU Hockey",
                                "last_scraped_at": None,
                            },
                        ],
                    },
                )

            if request.url.path == "/api/v1/sync/status":
                return httpx.Response(
                    200,
                    json={
                        "total_syncs": 0,
                        "status": "idle",
                        "last_sync": None,
                        "last_successful_sync": None,
                    },
                )

            if request.url.path == "/api/schedule.json":
                return httpx.Response(200, json=[])

            return httpx.Response(404)

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        telemetry, sources, _games = client.get_status_data()
        assert telemetry["last_success_at"] is None
        assert sources[0]["last_scraped_at"] is None

    def test_get_conflicts_success(self) -> None:
        """Verify successful conflict retrieval with filter parameters."""
        captured_params: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/conflicts"
            captured_params.update(dict(request.url.params))
            return httpx.Response(200, json={"total_conflicts": 0, "conflicts": []})

        client = RemoteApiClient(
            "https://remote.api",
            token="admin-token",
            transport=httpx.MockTransport(handler),
        )
        payload = client.get_conflicts(
            severity="CRITICAL",
            game_id="game_1",
            field_name="venue",
            review_only=True,
        )
        assert payload["total_conflicts"] == 0
        assert captured_params.get("severity") == "CRITICAL"
        assert captured_params.get("game_id") == "game_1"
        assert captured_params.get("field") == "venue"
        assert captured_params.get("requires_review") == "true"

    def test_get_conflicts_auth_error(self) -> None:
        """Verify RemoteApiAuthError raised when conflicts endpoint returns 401/403."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "Unauthorized"})

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(RemoteApiAuthError, match="Valid admin token required"):
            client.get_conflicts()

    def test_get_conflicts_http_and_network_error(self) -> None:
        """Verify RemoteApiError raised on other HTTP and network errors."""

        def http_err_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Error")

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(http_err_handler),
        )
        with pytest.raises(RemoteApiError, match="HTTP error fetching conflicts"):
            client.get_conflicts()

        def net_err_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Failed")

        client2 = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(net_err_handler),
        )
        with pytest.raises(RemoteApiError, match="Network error connecting"):
            client2.get_conflicts()

    def test_resolve_conflict_success(self) -> None:
        """Verify successful conflict resolution API call with explicit value."""
        captured_payloads: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/api/v1/conflicts/conf-123/resolve"
            data = json.loads(request.content.decode("utf-8"))
            captured_payloads.append(data)
            return httpx.Response(
                200,
                json={
                    "status": "resolved",
                    "conflict_id": "conf-123",
                    "field": data.get("field", "venue"),
                    "value": data.get("value", "Resolved Rink"),
                },
            )

        client = RemoteApiClient(
            "https://remote.api",
            token="admin-secret",
            transport=httpx.MockTransport(handler),
        )

        # 1. Resolve with explicit field/value
        res1 = client.resolve_conflict(
            "conf-123",
            field="venue",
            value="Target Arena",
            notes="Manual fix",
            resolved_by="lead-admin",
        )
        assert res1["status"] == "resolved"
        assert res1["value"] == "Target Arena"
        assert captured_payloads[0]["field"] == "venue"
        assert captured_payloads[0]["value"] == "Target Arena"
        assert captured_payloads[0]["notes"] == "Manual fix"
        assert captured_payloads[0]["resolved_by"] == "lead-admin"

        # 2. Resolve with accept_source and field_name alias
        res2 = client.resolve_conflict(
            "conf-123",
            field_name="venue",
            accept_source="achahockey",
        )
        assert res2["status"] == "resolved"
        assert captured_payloads[1]["field"] == "venue"
        assert captured_payloads[1]["accept_source"] == "achahockey"

    def test_resolve_conflict_auth_error(self) -> None:
        """Verify RemoteApiAuthError raised when resolve returns 401 or 403."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "Unauthorized"})

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(RemoteApiAuthError, match="Valid admin token required"):
            client.resolve_conflict("conf-123", value="Some Val")

    def test_resolve_conflict_http_and_network_error(self) -> None:
        """Verify RemoteApiError raised on resolve HTTP errors and network failures."""

        def http_err_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Error")

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(http_err_handler),
        )
        with pytest.raises(RemoteApiError, match="HTTP error resolving conflict"):
            client.resolve_conflict("conf-123", value="Some Val")

        def net_err_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection failed")

        client2 = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(net_err_handler),
        )
        with pytest.raises(RemoteApiError, match="Network error connecting"):
            client2.resolve_conflict("conf-123", value="Some Val")

    def test_trigger_sync_success(self) -> None:
        """Verify successful sync trigger execution."""
        captured_params: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/api/v1/sync/trigger"
            captured_params.update(dict(request.url.params))
            return httpx.Response(
                202,
                json={
                    "status": "accepted",
                    "sync_cycle_id": "sync-100",
                    "message": "Dispatched",
                },
            )

        client = RemoteApiClient(
            "https://remote.api",
            token="admin-token",
            transport=httpx.MockTransport(handler),
        )
        res = client.trigger_sync(source="ecuhockey")
        assert res["status"] == "accepted"
        assert captured_params.get("source") == "ecuhockey"

    def test_trigger_sync_auth_error(self) -> None:
        """Verify RemoteApiAuthError on trigger sync 403."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"detail": "Forbidden"})

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(
            RemoteApiAuthError,
            match="Valid admin token required to trigger sync",
        ):
            client.trigger_sync()

    def test_trigger_sync_unsupported_501(self) -> None:
        """Verify graceful return dict on 501 Not Implemented response."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(501, json={"detail": "On-demand trigger disabled."})

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        res = client.trigger_sync()
        assert res["status"] == "unsupported"
        assert res["status_code"] == 501
        assert "On-demand trigger disabled." in res["message"]

    def test_trigger_sync_unsupported_501_text_body(self) -> None:
        """Verify fallback detail when 501 response is not valid JSON."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(501, text="Not Implemented Plain")

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        res = client.trigger_sync()
        assert res["status"] == "unsupported"
        assert "On-demand synchronization trigger is not implemented" in res["message"]

    def test_trigger_sync_http_and_network_error(self) -> None:
        """Verify RemoteApiError on trigger sync HTTP and network failures."""

        def http_err_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Server Error")

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(http_err_handler),
        )
        with pytest.raises(RemoteApiError, match="HTTP error triggering sync"):
            client.trigger_sync()

        def net_err_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Failed")

        client2 = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(net_err_handler),
        )
        with pytest.raises(RemoteApiError, match="Network error connecting"):
            client2.trigger_sync()

    def test_fetch_export_unsupported_format(self) -> None:
        """Verify RemoteApiError raised on invalid export format."""
        client = RemoteApiClient("https://remote.api")
        with pytest.raises(RemoteApiError, match="Unsupported export format 'docx'"):
            client.fetch_export("docx")

    def test_fetch_export_text_formats(self) -> None:
        """Verify fetching text formats (ics, json, csv, html, rss, atom)."""
        captured: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request.url.path)
            return httpx.Response(200, text=f"content-for-{request.url.path}")

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        formats = [
            ("ics", "/schedule.ics"),
            ("json", "/schedule.json"),
            ("csv", "/schedule.csv"),
            ("html", "/schedule"),
            ("rss", "/schedule.rss"),
            ("atom", "/schedule.atom"),
        ]
        for fmt, path in formats:
            result = client.fetch_export(fmt)
            assert isinstance(result, str)
            assert f"content-for-{path}" in result

    def test_fetch_export_include_past_param(self) -> None:
        """Verify fetch_export correctly passes include_past query parameter."""
        captured_params: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_params.append(dict(request.url.params))
            return httpx.Response(200, text="content")

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        client.fetch_export("json", include_past=False)
        assert captured_params[-1]["future_only"] == "true"
        assert captured_params[-1]["include_past"] == "false"

        client.fetch_export("json", include_past=True)
        assert "future_only" not in captured_params[-1]
        assert captured_params[-1]["include_past"] == "true"

    def test_fetch_export_embed_widget(self) -> None:
        """Verify html embed format targets /schedule/embed."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/schedule/embed"
            return httpx.Response(200, text="<iframe widget>")

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        res = client.fetch_export("html", embed=True)
        assert res == "<iframe widget>"

    def test_fetch_export_pdf_binary(self) -> None:
        """Verify PDF export returns bytes."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/schedule.pdf"
            return httpx.Response(200, content=b"%PDF-1.4 binary data")

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(handler),
        )
        res = client.fetch_export(
            "pdf",
            season="2026-2027",
            opponent="UNC",
            home_only=True,
            future_only=True,
            status="SCHEDULED",
        )
        assert isinstance(res, bytes)
        assert res.startswith(b"%PDF")

    def test_fetch_export_http_and_network_error(self) -> None:
        """Verify RemoteApiError raised on export HTTP and network errors."""

        def http_err_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Not Found")

        client = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(http_err_handler),
        )
        with pytest.raises(RemoteApiError, match="HTTP error fetching ics export"):
            client.fetch_export("ics")

        def net_err_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Timeout")

        client2 = RemoteApiClient(
            "https://remote.api",
            transport=httpx.MockTransport(net_err_handler),
        )
        with pytest.raises(RemoteApiError, match="Network error connecting"):
            client2.fetch_export("ics")

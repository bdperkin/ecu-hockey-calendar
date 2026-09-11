"""Tests for service health, sync diagnostics, and conflict review endpoints.

Covers liveness, readiness, diagnostics, and conflict review.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import select

from ecu_hockey_calendar.api.app import create_app
from ecu_hockey_calendar.api.auth import (
    _extract_provided_token,
    resolve_admin_token,
    verify_admin_token,
)
from ecu_hockey_calendar.api.routes.conflicts import (
    _change_model_to_conflict,
    _convert_conflict_item,
)
from ecu_hockey_calendar.api.routes.health import (
    _calculate_uptime,
    _probe_scrapers,
)
from ecu_hockey_calendar.reconciliation.models import (
    ConflictField,
    ConflictSeverity,
    DetectedConflict,
    DiscrepancyRecord,
)
from ecu_hockey_calendar.storage.engine import (
    get_sync_session,
    init_db,
)
from ecu_hockey_calendar.storage.models import (
    DataSourceModel,
    GameChangeModel,
    SyncAuditModel,
    SyncStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

TEST_SECRET = "super-secret-admin-token-12345"  # pragma: allowlist secret


@pytest.fixture
def admin_app() -> TestClient:
    """Fixture providing TestClient with configured admin token."""
    app = create_app(admin_token=TEST_SECRET)
    return TestClient(app)


def test_root_endpoint_includes_new_routes() -> None:
    """Test root endpoint advertises health, sync status, and conflict endpoints."""
    app = create_app()
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    endpoints = response.json()["endpoints"]
    assert endpoints["health"] == "/health"
    assert endpoints["sync_status"] == "/api/v1/sync/status"
    assert endpoints["conflicts"] == "/api/v1/conflicts"


def test_health_probe_in_memory() -> None:
    """Test GET /health probe when running without persistent database."""
    app = create_app()
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "ecu-hockey-calendar-api"
    assert data["components"]["database"]["status"] == "not_configured"
    assert data["components"]["database"]["connected"] is False
    assert data["components"]["scrapers"]["status"] == "operational"
    assert len(data["components"]["scrapers"]["sources"]) == 4
    assert data["uptime_seconds"] >= 0.0


def test_health_probe_head() -> None:
    """Test HEAD /health returns empty body and 200 OK status code."""
    app = create_app()
    client = TestClient(app)
    response = client.head("/health")

    assert response.status_code == 200
    assert response.content == b""


def test_health_probe_with_database(tmp_path: Path) -> None:
    """Test GET /health with connected SQLite database and seeded data sources."""
    db_file = tmp_path / "test_health.db"
    db_url = f"sqlite:///{db_file}"

    app = create_app(database_url=db_url)
    init_db(app.state.db_engine)

    with get_sync_session(app.state.db_engine) as session:
        src = DataSourceModel(
            source_code="ecuhockey",
            name="ECU Official Site",
            source_url="https://example.com/schedule",
            source_type="primary_sot",
            priority_order=1,
            is_active=True,
            last_scraped_at=datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
        )
        session.add(src)
        session.commit()

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["components"]["database"]["status"] == "connected"
    assert data["components"]["database"]["connected"] is True
    assert data["components"]["scrapers"]["status"] == "operational"
    assert data["components"]["scrapers"]["sources"][0]["source_code"] == "ecuhockey"
    assert data["components"]["scrapers"]["sources"][0]["last_scraped_at"] is not None


def test_health_probe_database_failure(caplog: pytest.LogCaptureFixture) -> None:
    """Test GET /health reports 503 when DB probe raises exception."""
    app = create_app()
    mock_engine = MagicMock()
    mock_engine.connect.side_effect = RuntimeError("Database unreachable")
    app.state.db_engine = mock_engine

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unhealthy"
    db_comp = data["components"]["database"]
    assert db_comp["status"] == "unhealthy"
    assert db_comp["error"] == "Database connectivity probe failed"
    assert "Database connectivity probe failed: Database unreachable" in caplog.text

    head_resp = client.head("/health")
    assert head_resp.status_code == 503


def test_health_probe_scraper_override_and_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test scraper health override and database query failure fallback."""
    app = create_app()
    app.state.scraper_health_override = {
        "status": "degraded",
        "sources": [{"source_code": "ecuhockey", "is_active": False}],
    }
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["components"]["scrapers"]["status"] == "degraded"

    # Test error fallback in _probe_scrapers
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value.execute.return_value = None
    mock_engine.dialect.name = "sqlite"

    dummy_request = cast(
        Request,
        type(
            "Req",
            (),
            {
                "app": type(
                    "App",
                    (),
                    {"state": type("State", (), {"db_engine": mock_engine})()},
                )(),
            },
        )(),
    )
    with patch(
        "ecu_hockey_calendar.api.routes.health.get_sync_session",
        side_effect=RuntimeError("Scraper DB lookup failed"),
    ):
        result = _probe_scrapers(dummy_request)
        assert result["status"] == "degraded"
        assert result["error"] == "Data source probe failed"
        expected_log = "Scraper health check probe failed: Scraper DB lookup failed"
        assert expected_log in caplog.text


def test_calculate_uptime_none() -> None:
    """Test _calculate_uptime with None start_time."""
    assert _calculate_uptime(None) == 0.0


def test_sync_status_in_memory() -> None:
    """Test GET /api/v1/sync/status when no sync cycles have run."""
    app = create_app()
    client = TestClient(app)
    response = client.get("/api/v1/sync/status")

    assert response.status_code == 200
    data = response.json()
    assert data["current_status"] == "idle"
    assert data["total_sync_cycles"] == 0
    assert data["last_sync"]["status"] == "never_run"
    assert data["last_sync"]["games_created"] == 0
    assert data["last_success_at"] is None
    assert len(data["sources"]) == 4


def test_sync_status_with_database(tmp_path: Path) -> None:
    """Test GET /api/v1/sync/status loaded from seeded database audits."""
    db_file = tmp_path / "test_sync.db"
    db_url = f"sqlite:///{db_file}"

    app = create_app(database_url=db_url)
    init_db(app.state.db_engine)

    with get_sync_session(app.state.db_engine) as session:
        src = DataSourceModel(
            source_code="ecuhockey",
            name="ECU Official",
            source_url="https://example.com",
            source_type="primary_sot",
        )
        session.add(src)
        session.flush()

        audit1 = SyncAuditModel(
            source_id=src.id,
            sync_cycle_id="cycle-001",
            started_at=datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
            completed_at=datetime(2026, 9, 8, 10, 0, 5, tzinfo=UTC),
            duration_ms=5000,
            status=SyncStatus.SUCCESS.value,
            games_created=10,
            games_updated=2,
            games_deleted=0,
            conflicts_detected=1,
        )
        audit2 = SyncAuditModel(
            source_id=src.id,
            sync_cycle_id="cycle-002",
            started_at=datetime(2026, 9, 8, 11, 0, tzinfo=UTC),
            completed_at=None,
            duration_ms=None,
            status=SyncStatus.RUNNING.value,
            games_created=0,
            games_updated=0,
            games_deleted=0,
            conflicts_detected=0,
        )
        session.add_all([audit1, audit2])
        session.commit()

    client = TestClient(app)
    response = client.get("/api/v1/sync/status")

    assert response.status_code == 200
    data = response.json()
    assert data["current_status"] == "syncing"
    assert data["total_sync_cycles"] == 2
    assert data["last_sync"]["sync_cycle_id"] == "cycle-002"
    assert data["last_sync"]["status"] == "RUNNING"
    assert data["last_success_at"] is not None
    assert len(data["sources"]) == 1

    with get_sync_session(app.state.db_engine) as session:
        stmt = select(SyncAuditModel).where(
            SyncAuditModel.sync_cycle_id == "cycle-002",
        )
        audit_rec = session.scalar(stmt)
        assert audit_rec is not None
        audit_rec.status = SyncStatus.SUCCESS.value
        session.commit()

    resp_idle = client.get("/api/v1/sync/status")
    assert resp_idle.status_code == 200
    assert resp_idle.json()["current_status"] == "idle"


def test_sync_status_override() -> None:
    """Test GET /api/v1/sync/status returns override when present on app state."""
    app = create_app()
    app.state.sync_status_override = {
        "current_status": "syncing",
        "last_sync": {"sync_cycle_id": "test-override", "status": "RUNNING"},
    }
    client = TestClient(app)
    resp = client.get("/api/v1/sync/status")
    assert resp.status_code == 200
    assert resp.json()["last_sync"]["sync_cycle_id"] == "test-override"


def test_trigger_sync_auth_failures(admin_app: TestClient) -> None:
    """Test POST /api/v1/sync/trigger authentication rejections."""
    # 1. Missing credentials
    r_missing = admin_app.post("/api/v1/sync/trigger")
    assert r_missing.status_code == 401
    assert "WWW-Authenticate" in r_missing.headers

    # 2. Invalid Bearer token
    r_bad_bearer = admin_app.post(
        "/api/v1/sync/trigger",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert r_bad_bearer.status_code == 401

    # 3. Invalid X-API-Key
    r_bad_api_key = admin_app.post(
        "/api/v1/sync/trigger",
        headers={"X-API-Key": "wrong-key"},
    )
    assert r_bad_api_key.status_code == 401


def test_trigger_sync_success(admin_app: TestClient) -> None:
    """Test POST /api/v1/sync/trigger accepts valid requests and invokes handler."""
    triggered_cycles: list[str] = []

    def mock_trigger(cycle_id: str, *, source: str | None = None) -> None:
        """Record triggered sync cycle for assertion."""
        triggered_cycles.append(f"{cycle_id}:{source}")

    admin_app.app.state.sync_trigger_handler = mock_trigger  # type: ignore[attr-defined]

    # 1. Trigger via Bearer auth
    resp = admin_app.post(
        "/api/v1/sync/trigger?source=ecuhockey",
        headers={"Authorization": f"Bearer {TEST_SECRET}"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["target_source"] == "ecuhockey"
    assert len(triggered_cycles) == 1
    assert ":ecuhockey" in triggered_cycles[0]

    # 2. Trigger via X-API-Key
    resp2 = admin_app.post(
        "/api/v1/sync/trigger",
        headers={"X-API-Key": TEST_SECRET},
    )
    assert resp2.status_code == 202
    assert len(triggered_cycles) == 2


def test_conflicts_auth_failures(admin_app: TestClient) -> None:
    """Test GET /api/v1/conflicts authentication requirement and errors."""
    # 1. No token configured on server
    app_no_token = create_app()
    client_no_token = TestClient(app_no_token)
    r_unconfigured = client_no_token.get("/api/v1/conflicts")
    assert r_unconfigured.status_code == 401
    assert "not configured" in r_unconfigured.json()["detail"]

    # 2. Missing credentials on configured server
    r_missing = admin_app.get("/api/v1/conflicts")
    assert r_missing.status_code == 401

    # 3. Invalid token
    r_bad = admin_app.get(
        "/api/v1/conflicts",
        headers={"Authorization": "Bearer invalid"},
    )
    assert r_bad.status_code == 401


def test_conflicts_empty(admin_app: TestClient) -> None:
    """Test GET /api/v1/conflicts returns empty list when no conflicts exist."""
    resp = admin_app.get(
        "/api/v1/conflicts",
        headers={"Authorization": f"Bearer {TEST_SECRET}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_conflicts"] == 0
    assert data["conflicts"] == []


def test_conflicts_override_and_filtering(admin_app: TestClient) -> None:
    """Test GET /api/v1/conflicts with DetectedConflict objects and filters."""
    conflict1 = DetectedConflict(
        conflict_id="conf-001",
        game_key="ECU-2026-01",
        field=ConflictField.VENUE,
        severity=ConflictSeverity.HIGH,
        requires_review=True,
        discrepancies=[
            DiscrepancyRecord(
                field=ConflictField.VENUE,
                source_a="ecuhockey",
                source_b="acchockey",
                value_a="The Factory Ice House",
                value_b="Polar Ice House",
                severity=ConflictSeverity.HIGH,
                notes="Venue discrepancy",
            ),
        ],
    )
    conflict2 = DetectedConflict(
        conflict_id="conf-002",
        game_key="ECU-2026-02",
        field=ConflictField.START_TIME,
        severity=ConflictSeverity.LOW,
        requires_review=False,
    )
    raw_conflict = {
        "conflict_id": "conf-003",
        "game_id": "ECU-2026-03",
        "field": "date",
        "severity": "medium",
        "requires_review": True,
    }

    admin_app.app.state.conflicts_override = [conflict1, conflict2, raw_conflict]  # type: ignore[attr-defined]

    headers = {"Authorization": f"Bearer {TEST_SECRET}"}

    # 1. Retrieve all
    resp = admin_app.get("/api/v1/conflicts", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_conflicts"] == 3
    assert data["filtered_count"] == 3

    # 2. Filter by severity
    resp_high = admin_app.get("/api/v1/conflicts?severity=high", headers=headers)
    assert resp_high.status_code == 200
    assert resp_high.json()["total_conflicts"] == 1
    assert resp_high.json()["conflicts"][0]["conflict_id"] == "conf-001"

    # 3. Filter by game_id
    resp_game = admin_app.get("/api/v1/conflicts?game_id=ECU-2026-02", headers=headers)
    assert resp_game.status_code == 200
    assert resp_game.json()["total_conflicts"] == 1
    assert resp_game.json()["conflicts"][0]["conflict_id"] == "conf-002"

    # 4. Filter by field
    resp_field = admin_app.get("/api/v1/conflicts?field=date", headers=headers)
    assert resp_field.status_code == 200
    assert resp_field.json()["total_conflicts"] == 1

    # 5. Filter by requires_review
    resp_rev = admin_app.get("/api/v1/conflicts?requires_review=false", headers=headers)
    assert resp_rev.status_code == 200
    assert resp_rev.json()["total_conflicts"] == 1
    assert resp_rev.json()["conflicts"][0]["conflict_id"] == "conf-002"

    # 6. Pagination (limit, offset)
    resp_page = admin_app.get("/api/v1/conflicts?limit=1&offset=1", headers=headers)
    assert resp_page.status_code == 200
    page_data = resp_page.json()
    assert page_data["total_conflicts"] == 3
    assert page_data["filtered_count"] == 1
    assert page_data["conflicts"][0]["conflict_id"] == "conf-002"


def test_conflicts_database_integration(tmp_path: Path) -> None:
    """Test GET /api/v1/conflicts querying GameChangeModel records."""
    db_file = tmp_path / "test_conflicts.db"
    db_url = f"sqlite:///{db_file}"

    app = create_app(database_url=db_url, admin_token=TEST_SECRET)
    init_db(app.state.db_engine)

    with get_sync_session(app.state.db_engine) as session:
        change = GameChangeModel(
            sync_cycle_id="cycle-c1",
            canonical_game_id="DB-GAME-01",
            change_type="CONFLICT",
            summary="Conflicting puck drop time detected between ECU and ACCHL",
            field_diffs=[
                {
                    "field": "start_time",
                    "source_a": "ecuhockey",
                    "source_b": "acchockey",
                    "value_a": "2026-10-16T23:30:00Z",
                    "value_b": "2026-10-17T00:00:00Z",
                    "severity": "high",
                },
            ],
            snapshot_before={"time": "23:30"},
            snapshot_after={"time": "00:00"},
            recorded_at=datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
        )
        session.add(change)
        session.commit()

    client = TestClient(app)
    resp = client.get(
        "/api/v1/conflicts",
        headers={"Authorization": f"Bearer {TEST_SECRET}"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_conflicts"] == 1
    conf = data["conflicts"][0]
    assert conf["game_id"] == "DB-GAME-01"
    assert conf["field"] == "start_time"
    assert conf["severity"] == "high"
    assert len(conf["field_diffs"]) == 1


def test_auth_helper_functions() -> None:
    """Test auth utility functions and environment variable fallbacks."""
    # 1. Environment variable fallback
    dummy_req = cast(
        Request,
        type(
            "Req",
            (),
            {
                "app": type(
                    "App",
                    (),
                    {"state": type("State", (), {"admin_token": None})()},
                )(),
            },
        )(),
    )

    with patch.dict(os.environ, {"ECU_HOCKEY_ADMIN_TOKEN": "token-from-env"}):
        assert resolve_admin_token(dummy_req) == "token-from-env"

    with patch.dict(
        os.environ,
        {"ECU_HOCKEY_ADMIN_TOKEN": "", "ADMIN_TOKEN": "token-from-second-env"},
    ):
        assert resolve_admin_token(dummy_req) == "token-from-second-env"

    # 2. _extract_provided_token
    assert _extract_provided_token(None, None) is None
    assert _extract_provided_token(None, "my-key") == "my-key"

    # 3. verify_admin_token direct exception check
    req_no_auth = cast(
        Request,
        type(
            "Req",
            (),
            {
                "app": type(
                    "App",
                    (),
                    {"state": type("State", (), {"admin_token": "valid"})()},
                )(),
            },
        )(),
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_admin_token(req_no_auth, None, None)

    assert exc_info.value.status_code == 401


def test_health_and_sync_empty_database(tmp_path: Path) -> None:
    """Test health and sync endpoints fallback to default scrapers with empty DB."""
    db_file = tmp_path / "test_empty.db"
    db_url = f"sqlite:///{db_file}"

    app = create_app(database_url=db_url)
    init_db(app.state.db_engine)
    client = TestClient(app)

    # Probe /health with empty DB
    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    assert len(health_resp.json()["components"]["scrapers"]["sources"]) == 4

    # Probe /api/v1/sync/status with empty DB
    sync_resp = client.get("/api/v1/sync/status")
    assert sync_resp.status_code == 200
    assert len(sync_resp.json()["sources"]) == 4


def test_trigger_sync_without_handler(admin_app: TestClient) -> None:
    """Test POST /api/v1/sync/trigger returns 501 when no handler is registered."""
    # 1. Unset handler (None)
    admin_app.app.state.sync_trigger_handler = None  # type: ignore[attr-defined]
    resp = admin_app.post(
        "/api/v1/sync/trigger",
        headers={"Authorization": f"Bearer {TEST_SECRET}"},
    )
    assert resp.status_code == 501
    data = resp.json()
    assert "not implemented or configured" in data["detail"]
    assert "external cron" in data["detail"]

    # 2. Non-callable handler object
    admin_app.app.state.sync_trigger_handler = "non_callable_string"  # type: ignore[attr-defined]
    resp_non_callable = admin_app.post(
        "/api/v1/sync/trigger",
        headers={"Authorization": f"Bearer {TEST_SECRET}"},
    )
    assert resp_non_callable.status_code == 501
    assert "not implemented or configured" in resp_non_callable.json()["detail"]


def test_conflict_conversion_edge_cases() -> None:
    """Test conflict conversion helpers across edge cases."""
    # 1. Object whose to_dict has both game_key and game_id
    obj_both = type(
        "Both",
        (),
        {"to_dict": lambda self: {"game_key": "K1", "game_id": "ID1"}},
    )()
    assert _convert_conflict_item(obj_both)["game_id"] == "ID1"

    # 2. Object whose to_dict has neither
    obj_none = type(
        "NoneObj",
        (),
        {"to_dict": lambda self: {"notes": "none"}},
    )()
    assert "game_id" not in _convert_conflict_item(obj_none)

    # 3. Non-dictionary, non-to_dict object
    assert _convert_conflict_item(12345) == {}

    # 4. _change_model_to_conflict with empty/None field_diffs
    chg_empty = GameChangeModel(
        id=99,
        sync_cycle_id="c-99",
        canonical_game_id="G-99",
        change_type="CONFLICT",
        summary="Summary without diffs",
        field_diffs=None,
    )
    conf = _change_model_to_conflict(chg_empty)
    assert conf["field"] == "schedule"
    assert conf["severity"] == "medium"
    assert conf["field_diffs"] == []


def test_create_app_environment_fallbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test create_app falls back to environment variables for db and token."""
    db_file = tmp_path / "env_app.db"
    db_url = f"sqlite:///{db_file}"

    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("ADMIN_API_TOKEN", "env-secret-token")

    app = create_app()
    assert app.state.admin_token == "env-secret-token"
    assert app.state.db_engine is not None
    app.state.db_engine.dispose()

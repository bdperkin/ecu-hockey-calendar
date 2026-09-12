"""Tests for synchronization trigger and telemetry API endpoints.

Covers concurrency protection, cooldown safeguards, BackgroundTasks execution,
and dashboard status hooks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ecu_hockey_calendar.api.app import create_app
from ecu_hockey_calendar.api.routes.sync import (
    _build_sync_template_context,
    _determine_sync_status,
    _format_duration_ms,
    _is_empty_sync,
    _is_failed_audit,
)
from ecu_hockey_calendar.storage.engine import (
    get_sync_session,
    init_db,
)
from ecu_hockey_calendar.storage.models import (
    DataSourceModel,
    SyncAuditModel,
    SyncStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

TEST_SECRET = "super-secret-admin-token-12345"  # pragma: allowlist secret

# pylint: disable=protected-access


def test_sync_trigger_in_process_background_tasks(tmp_path: Path) -> None:
    """Test POST /api/v1/sync/trigger executes in background."""
    db_file = tmp_path / "sync_bg.db"
    db_url = f"sqlite:///{db_file}"

    app = create_app(
        database_url=db_url,
        admin_token=TEST_SECRET,
        enable_sync_trigger=True,
        sync_cooldown_seconds=300,
    )
    init_db(app.state.db_engine)
    client = TestClient(app)

    # Mock crawler execution in background
    with patch(
        "ecu_hockey_calendar.sync_service._execute_crawlers",
        return_value=([], []),
    ):
        resp = client.post(
            "/api/v1/sync/trigger?source=ecuhockey",
            headers={"Authorization": f"Bearer {TEST_SECRET}"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["target_source"] == "ecuhockey"
        cycle_id = data["sync_cycle_id"]

        with get_sync_session(app.state.db_engine) as session:
            stmt = select(SyncAuditModel).where(
                SyncAuditModel.sync_cycle_id == cycle_id,
            )
            audit = session.scalar(stmt)
            assert audit is not None
            assert audit.status == SyncStatus.SUCCESS.value


def test_sync_trigger_concurrency_conflict(tmp_path: Path) -> None:
    """Test POST /api/v1/sync/trigger returns 409 Conflict when a sync is running."""
    db_file = tmp_path / "sync_conflict.db"
    db_url = f"sqlite:///{db_file}"

    app = create_app(
        database_url=db_url,
        admin_token=TEST_SECRET,
        enable_sync_trigger=True,
    )
    client = TestClient(app)

    sync_mgr = app.state.sync_manager
    assert sync_mgr is not None
    assert sync_mgr.try_acquire("active-cycle") is True

    try:
        resp = client.post(
            "/api/v1/sync/trigger",
            headers={"Authorization": f"Bearer {TEST_SECRET}"},
        )
        assert resp.status_code == 409
        assert "already in progress" in resp.json()["detail"]
    finally:
        sync_mgr.release()


def test_sync_trigger_cooldown_rate_limit(tmp_path: Path) -> None:
    """Test POST /api/v1/sync/trigger returns 429 when cooldown is active."""
    db_file = tmp_path / "sync_cooldown.db"
    db_url = f"sqlite:///{db_file}"

    app = create_app(
        database_url=db_url,
        admin_token=TEST_SECRET,
        enable_sync_trigger=True,
        sync_cooldown_seconds=300,
    )
    client = TestClient(app)

    sync_mgr = app.state.sync_manager
    assert sync_mgr is not None
    sync_mgr._last_completed_at = datetime.now(UTC)

    resp = client.post(
        "/api/v1/sync/trigger",
        headers={"Authorization": f"Bearer {TEST_SECRET}"},
    )
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    retry_after = int(resp.headers["Retry-After"])
    assert 280 <= retry_after <= 300
    assert "cooldown" in resp.json()["detail"]


def test_sync_trigger_custom_handler_runtime_error() -> None:
    """Test /api/v1/sync/trigger converts RuntimeError from handler to 409."""
    app = create_app(admin_token=TEST_SECRET)
    client = TestClient(app)

    def broken_handler(cycle_id: str, *, source: str | None = None) -> None:
        """Simulate a custom orchestrator raising RuntimeError."""
        raise RuntimeError("Cycle conflict from custom orchestrator")

    app.state.sync_trigger_handler = broken_handler

    resp = client.post(
        "/api/v1/sync/trigger",
        headers={"Authorization": f"Bearer {TEST_SECRET}"},
    )
    assert resp.status_code == 409
    assert "Cycle conflict from custom orchestrator" in resp.json()["detail"]


def test_sync_status_telemetry_hooks(tmp_path: Path) -> None:
    """Test /api/v1/sync/status returns trigger and cooldown telemetry fields."""
    # 1. Disabled (default)
    app_disabled = create_app()
    client_disabled = TestClient(app_disabled)
    res_dis = client_disabled.get("/api/v1/sync/status").json()
    assert res_dis["sync_trigger_enabled"] is False
    assert res_dis["can_trigger"] is False
    assert res_dis["cooldown_remaining_seconds"] == 0
    assert res_dis["cooldown_total_seconds"] == 900

    # 2. Enabled with database
    db_file = tmp_path / "telemetry_test.db"
    db_url = f"sqlite:///{db_file}"
    app_enabled = create_app(
        database_url=db_url,
        enable_sync_trigger=True,
        sync_cooldown_seconds=300,
    )
    init_db(app_enabled.state.db_engine)
    client_enabled = TestClient(app_enabled)
    res_en = client_enabled.get("/api/v1/sync/status").json()
    assert res_en["sync_trigger_enabled"] is True
    assert res_en["can_trigger"] is True
    assert res_en["cooldown_remaining_seconds"] == 0
    assert res_en["cooldown_total_seconds"] == 300

    # When actively running
    sm = app_enabled.state.sync_manager
    assert sm.try_acquire("c-active") is True
    try:
        res_running = client_enabled.get("/api/v1/sync/status").json()
        assert res_running["current_status"] == "syncing"
        assert res_running["can_trigger"] is False
    finally:
        sm.release()


def test_create_app_env_vars_sync_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test create_app resolves sync trigger and cooldown config from env."""
    monkeypatch.setenv("ENABLE_API_SYNC_TRIGGER", "true")
    monkeypatch.setenv("SYNC_COOLDOWN_SECONDS", "400")

    app = create_app()
    assert app.state.sync_manager is not None
    assert app.state.sync_manager.cooldown_seconds == 400
    assert app.state.sync_trigger_handler is not None


def test_determine_sync_status_running_flag() -> None:
    """Test _determine_sync_status with is_running parameter."""
    assert _determine_sync_status(None, is_running=True) == "syncing"
    assert _determine_sync_status(None, is_running=False) == "idle"


def test_sync_trigger_assigns_missing_engine(tmp_path: Path) -> None:
    """Test POST /api/v1/sync/trigger assigns engine to sync_manager if missing."""
    db_file = tmp_path / "sync_engine.db"
    db_url = f"sqlite:///{db_file}"

    app = create_app(
        database_url=db_url,
        admin_token=TEST_SECRET,
        enable_sync_trigger=True,
    )
    init_db(app.state.db_engine)
    assert app.state.sync_manager is not None
    app.state.sync_manager.engine = None
    client = TestClient(app)

    with patch(
        "ecu_hockey_calendar.sync_service._execute_crawlers",
        return_value=([], []),
    ):
        resp = client.post(
            "/api/v1/sync/trigger",
            headers={"Authorization": f"Bearer {TEST_SECRET}"},
        )
        assert resp.status_code == 202
        assert app.state.sync_manager.engine is not None


def test_sync_trigger_acquire_race_condition(tmp_path: Path) -> None:
    """Test POST /api/v1/sync/trigger handles try_acquire returning False."""
    db_file = tmp_path / "sync_race.db"
    db_url = f"sqlite:///{db_file}"

    app = create_app(
        database_url=db_url,
        admin_token=TEST_SECRET,
        enable_sync_trigger=True,
    )
    client = TestClient(app)

    with patch.object(app.state.sync_manager, "try_acquire", return_value=False):
        resp = client.post(
            "/api/v1/sync/trigger",
            headers={"Authorization": f"Bearer {TEST_SECRET}"},
        )
        assert resp.status_code == 409
        assert "already in progress" in resp.json()["detail"]


def test_create_app_env_vars_non_digit_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test create_app handles non-digit SYNC_COOLDOWN_SECONDS gracefully."""
    monkeypatch.setenv("ENABLE_API_SYNC_TRIGGER", "true")
    monkeypatch.setenv("SYNC_COOLDOWN_SECONDS", "invalid_number")

    app = create_app()
    assert app.state.sync_manager is not None
    assert app.state.sync_manager.cooldown_seconds == 900


def test_sync_status_content_negotiation_html() -> None:
    """Test GET /api/v1/sync/status negotiates HTML when requested."""
    app = create_app()
    client = TestClient(app)

    # HTML browser Accept header
    resp = client.get(
        "/api/v1/sync/status",
        headers={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"},
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Accept" in resp.headers.get("Vary", "")
    html_text = resp.text
    assert "Synchronization Status &amp; Telemetry" in html_text
    assert "Scheduled Cadence" in html_text
    assert "0 */6 * * *" in html_text
    assert "render.yaml" in html_text
    assert "No Synchronization Cycles Recorded Yet" in html_text
    assert "View as JSON" in html_text


def test_sync_status_content_negotiation_json_defaults() -> None:
    """Test GET /api/v1/sync/status defaults to JSON for curl and API clients."""
    app = create_app()
    client = TestClient(app)

    # Accept header with application/json
    resp_json = client.get(
        "/api/v1/sync/status",
        headers={"Accept": "application/json"},
    )
    assert resp_json.status_code == 200
    assert resp_json.headers["content-type"] == "application/json"
    assert "Accept" in resp_json.headers.get("Vary", "")
    data = resp_json.json()
    assert data["current_status"] == "idle"
    assert data["total_sync_cycles"] == 0

    # Accept wildcard header
    resp_wildcard = client.get(
        "/api/v1/sync/status",
        headers={"Accept": "*/*"},
    )
    assert resp_wildcard.status_code == 200
    assert resp_wildcard.headers["content-type"] == "application/json"

    # Query param ?format=html override
    resp_fmt_html = client.get("/api/v1/sync/status?format=html")
    assert resp_fmt_html.status_code == 200
    assert "text/html" in resp_fmt_html.headers["content-type"]

    # Query param ?format=json override
    resp_fmt_json = client.get(
        "/api/v1/sync/status?format=json",
        headers={"Accept": "text/html"},
    )
    assert resp_fmt_json.status_code == 200
    assert resp_fmt_json.headers["content-type"] == "application/json"


def test_sync_status_html_with_populated_audit_and_conflicts(tmp_path: Path) -> None:
    """Test GET /api/v1/sync/status HTML rendering with populated data and conflicts."""
    db_file = tmp_path / "sync_dashboard.db"
    db_url = f"sqlite:///{db_file}"

    app = create_app(database_url=db_url)
    init_db(app.state.db_engine)

    with get_sync_session(app.state.db_engine) as session:
        src = DataSourceModel(
            source_code="ecuhockey",
            name="ECU Official",
            source_url="https://example.com",
            source_type="primary_sot",
            is_active=True,
            last_scraped_at=datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
        )
        session.add(src)
        session.flush()

        audit = SyncAuditModel(
            source_id=src.id,
            sync_cycle_id="cycle-485",
            started_at=datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC),
            completed_at=datetime(2026, 9, 8, 12, 0, 0, 485000, tzinfo=UTC),
            duration_ms=485,
            status=SyncStatus.SUCCESS.value,
            games_created=4,
            games_updated=2,
            games_deleted=1,
            conflicts_detected=28,
            error_message=None,
        )
        session.add(audit)
        session.commit()

    client = TestClient(app)
    resp = client.get(
        "/api/v1/sync/status",
        headers={"Accept": "text/html"},
    )
    assert resp.status_code == 200
    html_text = resp.text
    assert "Games Created" in html_text
    assert "4" in html_text
    assert "Games Updated" in html_text
    assert "2" in html_text
    assert "Games Deleted" in html_text
    assert "1" in html_text
    assert "Conflicts Detected" in html_text
    assert "28" in html_text
    assert 'href="/api/v1/conflicts"' in html_text
    assert "485 ms" in html_text
    assert "cycle-485" in html_text
    assert "ECU Official" in html_text


def test_sync_status_html_error_panel() -> None:
    """Test GET /api/v1/sync/status renders error panel when error exists."""
    app = create_app()
    app.state.sync_status_override = {
        "current_status": "failed",
        "last_sync": {
            "sync_cycle_id": "failed-cycle-1",
            "status": "FAILURE",
            "started_at": "2026-09-08T12:00:00+00:00",
            "completed_at": "2026-09-08T12:00:05+00:00",
            "duration_ms": 5000,
            "games_created": 0,
            "games_updated": 0,
            "games_deleted": 0,
            "conflicts_detected": 0,
            "error_message": "Network timeout connecting to scraper upstream service",
        },
        "last_success_at": None,
        "total_sync_cycles": 1,
        "sources": [],
        "sync_trigger_enabled": False,
        "can_trigger": False,
        "cooldown_remaining_seconds": 0,
        "cooldown_total_seconds": 300,
    }
    client = TestClient(app)
    resp = client.get("/api/v1/sync/status?format=html")
    assert resp.status_code == 200
    html_text = resp.text
    assert "Synchronization Failure Detected" in html_text
    assert "Network timeout connecting to scraper upstream service" in html_text
    assert "failed" in html_text


def test_sync_status_html_running_state() -> None:
    """Test GET /api/v1/sync/status renders in-progress state when sync is active."""
    app = create_app()
    app.state.sync_status_override = {
        "current_status": "syncing",
        "last_sync": {
            "sync_cycle_id": "active-cycle-1",
            "status": "RUNNING",
            "started_at": "2026-09-08T12:00:00+00:00",
            "completed_at": None,
            "duration_ms": None,
            "games_created": 0,
            "games_updated": 0,
            "games_deleted": 0,
            "conflicts_detected": 0,
            "error_message": None,
        },
        "last_success_at": None,
        "total_sync_cycles": 1,
        "sources": [],
        "sync_trigger_enabled": True,
        "can_trigger": False,
        "cooldown_remaining_seconds": 120,
        "cooldown_total_seconds": 300,
    }
    client = TestClient(app)
    resp = client.get("/api/v1/sync/status?format=html")
    assert resp.status_code == 200
    assert "Synchronization In Progress" in resp.text
    assert "120s remaining" in resp.text


def test_format_duration_ms_unit() -> None:
    """Test _format_duration_ms formatting across ranges."""
    assert _format_duration_ms(None) == "N/A"
    assert _format_duration_ms(0) == "0 ms"
    assert _format_duration_ms(485) == "485 ms"
    assert _format_duration_ms(1200) == "1.2 s"
    assert _format_duration_ms(65000) == "1m 5s"


def test_sync_status_helpers_unit() -> None:
    """Test helper functions for sync empty state, audit failure, and context."""
    assert _is_empty_sync(None) is True
    assert _is_empty_sync({}) is True
    assert _is_empty_sync({"status": "never_run"}) is True
    assert _is_empty_sync({"status": "SUCCESS", "sync_cycle_id": "c-1"}) is False

    assert _is_failed_audit(None) is False
    audit_fail = SyncAuditModel(status=SyncStatus.FAILURE.value, error_message=None)
    assert _is_failed_audit(audit_fail) is True
    audit_err = SyncAuditModel(status="UNKNOWN", error_message="some error")
    assert _is_failed_audit(audit_err) is True
    audit_ok = SyncAuditModel(status=SyncStatus.SUCCESS.value, error_message=None)
    assert _is_failed_audit(audit_ok) is False

    assert _determine_sync_status(audit_fail) == "failed"
    assert _determine_sync_status(audit_ok) == "idle"

    # Non-dict last_sync and non-list sources
    ctx = _build_sync_template_context({"last_sync": None, "sources": None})
    assert ctx["last_sync_meta"]["has_run"] is False
    assert not ctx["sources"]

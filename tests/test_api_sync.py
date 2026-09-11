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
from ecu_hockey_calendar.api.routes.sync import _determine_sync_status
from ecu_hockey_calendar.storage.engine import (
    get_sync_session,
    init_db,
)
from ecu_hockey_calendar.storage.models import (
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

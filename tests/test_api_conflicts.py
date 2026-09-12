"""Tests for content-negotiated /api/v1/conflicts endpoint.

Covers dual-format HTML and JSON responses, administrative authentication,
side-by-side discrepancy comparisons, severity badges, filter parameters,
and pagination controls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from ecu_hockey_calendar.api.app import create_app
from ecu_hockey_calendar.api.routes.conflicts import (
    _build_conflicts_context,
    _build_pagination_context,
    _change_model_to_conflict,
    _convert_conflict_item,
    _convert_diff_to_pair,
    _convert_discrepancy_to_pair,
    _count_conflict_metrics,
    _enrich_conflict_items,
    _enrich_single_conflict,
    _extract_comparison_pairs,
    _extract_conflicts,
    _extract_diff_comparisons,
    _extract_diff_text,
    _extract_diff_value,
    _extract_discrepancy_comparisons,
    _extract_snapshot_comparison,
    _extract_snapshot_or_fallback_comparisons,
    _extract_summary_fallback,
    _format_active_filters,
    _format_raw_value,
    _format_recorded_time,
    _format_severity_meta,
    _is_any_filter_active,
    _matches_conflict_filter,
    _matches_id,
    _matches_review,
    _matches_text,
    _tally_single_conflict,
)
from ecu_hockey_calendar.reconciliation.models import (
    ConflictField,
    ConflictSeverity,
    DetectedConflict,
    DiscrepancyRecord,
)
from ecu_hockey_calendar.storage.engine import get_sync_session, init_db
from ecu_hockey_calendar.storage.models import GameChangeModel

if TYPE_CHECKING:
    from pathlib import Path

TEST_ADMIN_TOKEN = "conflicts-test-admin-secret-token"  # pragma: allowlist secret
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"}


def _build_sample_detected_conflict(
    conflict_id: str = "conf-101",
    game_key: str = "ecu-unc-20241011",
    field: ConflictField = ConflictField.START_TIME,
    severity: ConflictSeverity = ConflictSeverity.HIGH,
    *,
    requires_review: bool = True,
) -> DetectedConflict:
    """Create a sample DetectedConflict instance for tests."""
    return DetectedConflict(
        conflict_id=conflict_id,
        game_key=game_key,
        field=field,
        discrepancies=[
            DiscrepancyRecord(
                field=field,
                source_a="ecuhockey",
                source_b="acchockey",
                value_a="2024-10-11T19:00:00",
                value_b="2024-10-11T20:00:00",
                severity=severity,
                notes="One hour start time discrepancy between team and league sites",
            ),
        ],
        severity=severity,
        requires_review=requires_review,
        notes="Automatic reconciliation flagged start time collision.",
    )


# ---------------------------------------------------------------------------
# 1. Content Negotiation Tests: HTML vs JSON
# ---------------------------------------------------------------------------


def test_conflicts_content_negotiation_html() -> None:
    """Test GET /api/v1/conflicts negotiates HTML for browser clients."""
    app = create_app(admin_token=TEST_ADMIN_TOKEN)
    conflict = _build_sample_detected_conflict()
    app.state.conflicts_override = [conflict]
    client = TestClient(app)

    resp = client.get(
        "/api/v1/conflicts",
        headers={
            **AUTH_HEADERS,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        },
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Accept" in resp.headers.get("Vary", "")

    html = resp.text
    assert "Administrative Conflict Triage" in html
    assert "ecu-unc-20241011" in html
    assert "start_time" in html
    assert "High" in html
    assert "Action Required" in html
    assert "ecuhockey" in html
    assert "acchockey" in html
    assert "2024-10-11T19:00:00" in html
    assert "2024-10-11T20:00:00" in html
    assert "View as JSON" in html
    assert "/api/v1/sync/status" in html


def test_conflicts_content_negotiation_json_defaults() -> None:
    """Test GET /api/v1/conflicts defaults to JSON for API consumers."""
    app = create_app(admin_token=TEST_ADMIN_TOKEN)
    conflict = _build_sample_detected_conflict()
    app.state.conflicts_override = [conflict]
    client = TestClient(app)

    # 1. Accept: application/json
    resp_json = client.get(
        "/api/v1/conflicts",
        headers={**AUTH_HEADERS, "Accept": "application/json"},
    )
    assert resp_json.status_code == 200
    assert resp_json.headers["content-type"] == "application/json"
    assert "Accept" in resp_json.headers.get("Vary", "")
    data = resp_json.json()
    assert data["total_conflicts"] == 1
    assert data["filtered_count"] == 1
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert len(data["conflicts"]) == 1
    assert data["conflicts"][0]["game_id"] == "ecu-unc-20241011"

    # 2. Accept: */*
    resp_wildcard = client.get(
        "/api/v1/conflicts",
        headers={**AUTH_HEADERS, "Accept": "*/*"},
    )
    assert resp_wildcard.status_code == 200
    assert resp_wildcard.headers["content-type"] == "application/json"

    # 3. Absent Accept header
    resp_none = client.get("/api/v1/conflicts", headers=AUTH_HEADERS)
    assert resp_none.status_code == 200
    assert resp_none.headers["content-type"] == "application/json"


def test_conflicts_format_query_override() -> None:
    """Test format query parameter overrides Accept header."""
    app = create_app(admin_token=TEST_ADMIN_TOKEN)
    app.state.conflicts_override = [_build_sample_detected_conflict()]
    client = TestClient(app)

    # ?format=html overrides Accept: application/json
    resp_html = client.get(
        "/api/v1/conflicts?format=html",
        headers={**AUTH_HEADERS, "Accept": "application/json"},
    )
    assert resp_html.status_code == 200
    assert "text/html" in resp_html.headers["content-type"]
    assert "Administrative Conflict Triage" in resp_html.text

    # ?format=json overrides Accept: text/html
    resp_json = client.get(
        "/api/v1/conflicts?format=json",
        headers={**AUTH_HEADERS, "Accept": "text/html"},
    )
    assert resp_json.status_code == 200
    assert resp_json.headers["content-type"] == "application/json"
    assert resp_json.json()["total_conflicts"] == 1


# ---------------------------------------------------------------------------
# 2. Authentication & Authorization Enforcement
# ---------------------------------------------------------------------------


def test_conflicts_unauthenticated_html_returns_401() -> None:
    """Test unauthenticated HTML request returns styled 401 error page."""
    app = create_app(admin_token=TEST_ADMIN_TOKEN)
    client = TestClient(app)

    resp = client.get("/api/v1/conflicts", headers={"Accept": "text/html"})
    assert resp.status_code == 401
    assert "text/html" in resp.headers["content-type"]
    assert resp.headers.get("www-authenticate") == "Bearer"
    assert "Administrative Authentication Required" in resp.text


def test_conflicts_unauthenticated_json_returns_401() -> None:
    """Test unauthenticated JSON request returns 401 detail payload."""
    app = create_app(admin_token=TEST_ADMIN_TOKEN)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/conflicts",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 401
    assert resp.headers["content-type"] == "application/json"
    assert resp.headers.get("www-authenticate") == "Bearer"
    assert "detail" in resp.json()


def test_conflicts_api_key_header_authentication() -> None:
    """Test administrative access via X-API-Key header."""
    app = create_app(admin_token=TEST_ADMIN_TOKEN)
    app.state.conflicts_override = [_build_sample_detected_conflict()]
    client = TestClient(app)

    resp = client.get(
        "/api/v1/conflicts",
        headers={"X-API-Key": TEST_ADMIN_TOKEN, "Accept": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["total_conflicts"] == 1


def test_conflicts_invalid_token_returns_401() -> None:
    """Test invalid token returns 401 Unauthorized."""
    app = create_app(admin_token=TEST_ADMIN_TOKEN)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/conflicts",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 3. Filtering & Query Parameters
# ---------------------------------------------------------------------------


def test_conflicts_filter_by_severity() -> None:
    """Test filtering conflicts by severity level."""
    app = create_app(admin_token=TEST_ADMIN_TOKEN)
    c1 = _build_sample_detected_conflict("c-1", severity=ConflictSeverity.CRITICAL)
    c2 = _build_sample_detected_conflict("c-2", severity=ConflictSeverity.LOW)
    app.state.conflicts_override = [c1, c2]
    client = TestClient(app)

    # Filter critical
    resp_crit = client.get(
        "/api/v1/conflicts?severity=critical",
        headers=AUTH_HEADERS,
    )
    data_crit = resp_crit.json()
    assert data_crit["total_conflicts"] == 1
    assert data_crit["conflicts"][0]["conflict_id"] == "c-1"

    # Filter low
    resp_low = client.get(
        "/api/v1/conflicts?severity=low",
        headers=AUTH_HEADERS,
    )
    data_low = resp_low.json()
    assert data_low["total_conflicts"] == 1
    assert data_low["conflicts"][0]["conflict_id"] == "c-2"


def test_conflicts_filter_by_game_id_and_field() -> None:
    """Test filtering by game identifier and conflict field name."""
    app = create_app(admin_token=TEST_ADMIN_TOKEN)
    c1 = _build_sample_detected_conflict(
        "c-1",
        game_key="ecu-unc-20241011",
        field=ConflictField.START_TIME,
    )
    c2 = _build_sample_detected_conflict(
        "c-2",
        game_key="ecu-ncsu-20241018",
        field=ConflictField.VENUE,
    )
    app.state.conflicts_override = [c1, c2]
    client = TestClient(app)

    # Match game_id
    resp_game = client.get(
        "/api/v1/conflicts?game_id=ecu-ncsu-20241018",
        headers=AUTH_HEADERS,
    )
    assert resp_game.json()["total_conflicts"] == 1
    assert resp_game.json()["conflicts"][0]["conflict_id"] == "c-2"

    # Match field
    resp_field = client.get(
        "/api/v1/conflicts?field=venue",
        headers=AUTH_HEADERS,
    )
    assert resp_field.json()["total_conflicts"] == 1
    assert resp_field.json()["conflicts"][0]["conflict_id"] == "c-2"


def test_conflicts_filter_by_requires_review() -> None:
    """Test filtering by requires_review boolean flag."""
    app = create_app(admin_token=TEST_ADMIN_TOKEN)
    c1 = _build_sample_detected_conflict("c-1", requires_review=True)
    c2 = _build_sample_detected_conflict("c-2", requires_review=False)
    app.state.conflicts_override = [c1, c2]
    client = TestClient(app)

    resp_review = client.get(
        "/api/v1/conflicts?requires_review=true",
        headers=AUTH_HEADERS,
    )
    assert resp_review.json()["total_conflicts"] == 1
    assert resp_review.json()["conflicts"][0]["conflict_id"] == "c-1"

    resp_no_review = client.get(
        "/api/v1/conflicts?requires_review=false",
        headers=AUTH_HEADERS,
    )
    assert resp_no_review.json()["total_conflicts"] == 1
    assert resp_no_review.json()["conflicts"][0]["conflict_id"] == "c-2"


def test_conflicts_html_filter_form_and_active_tags() -> None:
    """Test HTML rendering shows active filter badges and pre-filled inputs."""
    app = create_app(admin_token=TEST_ADMIN_TOKEN)
    c1 = _build_sample_detected_conflict(
        "c-1",
        game_key="ecu-unc-20241011",
        severity=ConflictSeverity.CRITICAL,
        field=ConflictField.START_TIME,
        requires_review=True,
    )
    app.state.conflicts_override = [c1]
    client = TestClient(app)

    resp = client.get(
        "/api/v1/conflicts?format=html&severity=critical&game_id=ecu-unc-20241011&field=start_time&requires_review=true",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    html = resp.text
    assert "Active Filters:" in html
    assert "Severity: critical" in html
    assert "Game ID: ecu-unc-20241011" in html
    assert "Field: start_time" in html
    assert "Review: True" in html
    assert "Reset All" in html
    assert "<strong>1</strong> matching record" in html


# ---------------------------------------------------------------------------
# 4. Pagination Controls & Preserved Query Params
# ---------------------------------------------------------------------------


def test_conflicts_pagination_controls_in_html() -> None:
    """Test pagination range summary and Prev/Next link preservation."""
    app = create_app(admin_token=TEST_ADMIN_TOKEN)
    conflicts = [
        _build_sample_detected_conflict(
            f"conf-{idx}",
            game_key=f"game-{idx}",
            severity=ConflictSeverity.MEDIUM,
        )
        for idx in range(1, 6)
    ]
    app.state.conflicts_override = conflicts
    client = TestClient(app)

    # 1. Page 1: limit=2, offset=0
    resp_p1 = client.get(
        "/api/v1/conflicts?format=html&limit=2&offset=0&severity=medium",
        headers=AUTH_HEADERS,
    )
    html_p1 = resp_p1.text
    assert "Showing <strong>1-2</strong> of <strong>5</strong> conflicts" in html_p1
    assert "btn-pagination-prev-disabled" in html_p1
    assert "btn-pagination-next" in html_p1
    assert "offset=2" in html_p1
    assert "severity=medium" in html_p1

    # 2. Page 2: limit=2, offset=2
    resp_p2 = client.get(
        "/api/v1/conflicts?format=html&limit=2&offset=2&severity=medium",
        headers=AUTH_HEADERS,
    )
    html_p2 = resp_p2.text
    assert "Showing <strong>3-4</strong> of <strong>5</strong> conflicts" in html_p2
    assert "offset=0" in html_p2
    assert "offset=4" in html_p2

    # 3. Page 3: limit=2, offset=4 (last page)
    resp_p3 = client.get(
        "/api/v1/conflicts?format=html&limit=2&offset=4&severity=medium",
        headers=AUTH_HEADERS,
    )
    html_p3 = resp_p3.text
    assert "Showing <strong>5-5</strong> of <strong>5</strong> conflicts" in html_p3
    assert "offset=2" in html_p3
    assert "btn-pagination-next-disabled" in html_p3


# ---------------------------------------------------------------------------
# 5. Empty States
# ---------------------------------------------------------------------------


def test_conflicts_empty_state_zero_conflicts() -> None:
    """Test friendly empty state when no conflicts exist in system."""
    app = create_app(admin_token=TEST_ADMIN_TOKEN)
    app.state.conflicts_override = []
    client = TestClient(app)

    resp = client.get("/api/v1/conflicts?format=html", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    html = resp.text
    assert "No Conflicts Detected" in html
    assert "All schedule data sources are currently aligned" in html
    assert "/schedule" in html
    assert "/api/v1/sync/status" in html


def test_conflicts_empty_state_filtered_no_matches() -> None:
    """Test empty state when filters eliminate all conflict records."""
    app = create_app(admin_token=TEST_ADMIN_TOKEN)
    app.state.conflicts_override = [_build_sample_detected_conflict("c-1")]
    client = TestClient(app)

    resp = client.get(
        "/api/v1/conflicts?format=html&severity=critical",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    html = resp.text
    assert "No Conflicts Match Filters" in html
    assert "Clear Active Filters" in html


# ---------------------------------------------------------------------------
# 6. Database Backed Conflict Retrieval
# ---------------------------------------------------------------------------


def test_conflicts_retrieved_from_database(tmp_path: Path) -> None:
    """Test reading conflicts from SQLite storage GameChangeModel entities."""
    db_file = tmp_path / "conflicts_db.db"
    db_url = f"sqlite:///{db_file}"

    app = create_app(database_url=db_url, admin_token=TEST_ADMIN_TOKEN)
    init_db(app.state.db_engine)

    with get_sync_session(app.state.db_engine) as session:
        change = GameChangeModel(
            sync_cycle_id="cycle-test-1",
            canonical_game_id="ecu-vt-20241101",
            change_type="CONFLICT",
            summary="Venue disagreement between team site and opponent schedule",
            field_diffs=[
                {
                    "field_name": "venue",
                    "old_value": "Carolina Ice Palace",
                    "new_value": "Innsbrook After Hours",
                    "human_description": (
                        "Venue changed from home rink to neutral arena"
                    ),
                    "severity": "high",
                },
            ],
            snapshot_before={"venue": "Carolina Ice Palace"},
            snapshot_after={"venue": "Innsbrook After Hours"},
            recorded_at=datetime(2026, 9, 10, 15, 30, tzinfo=UTC),
        )
        session.add(change)

    client = TestClient(app)

    # 1. Test JSON response
    resp_json = client.get("/api/v1/conflicts", headers=AUTH_HEADERS)
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert data["total_conflicts"] == 1
    assert data["conflicts"][0]["game_id"] == "ecu-vt-20241101"
    assert data["conflicts"][0]["field"] == "venue"

    # 2. Test HTML response with side-by-side values from diff
    resp_html = client.get(
        "/api/v1/conflicts?format=html",
        headers=AUTH_HEADERS,
    )
    assert resp_html.status_code == 200
    html = resp_html.text
    assert "ecu-vt-20241101" in html
    assert "Carolina Ice Palace" in html
    assert "Innsbrook After Hours" in html
    assert "Venue changed from home rink to neutral arena" in html


# ---------------------------------------------------------------------------
# 7. Unit Tests for Helper Functions & Edge Cases
# ---------------------------------------------------------------------------


def test_format_severity_meta_all_cases() -> None:
    """Test _format_severity_meta with all severities and fallbacks."""
    assert _format_severity_meta("critical") == ("critical", "Critical", "⛔")
    assert _format_severity_meta("HIGH") == ("high", "High", "⚠️")
    assert _format_severity_meta("low") == ("low", "Low", "✓")
    assert _format_severity_meta("medium") == ("medium", "Medium", "⚡")
    assert _format_severity_meta(None) == ("medium", "Medium", "⚡")
    assert _format_severity_meta("unknown") == ("medium", "Medium", "⚡")


def test_format_raw_value() -> None:
    """Test _format_raw_value handling of None and objects."""
    assert _format_raw_value(None) == "N/A"
    assert _format_raw_value(42) == "42"
    assert _format_raw_value("value") == "value"


def test_convert_discrepancy_to_pair_fallbacks() -> None:
    """Test _convert_discrepancy_to_pair fallback defaults."""
    pair = _convert_discrepancy_to_pair({})
    assert pair["source_a"] == "Source A"
    assert pair["source_b"] == "Source B"
    assert pair["value_a"] == "N/A"
    assert pair["value_b"] == "N/A"


def test_extract_diff_value_and_text() -> None:
    """Test _extract_diff_value and _extract_diff_text helper functions."""
    diff = {"value_a": "10", "old_value": "5", "field_name": "start_time"}
    assert _extract_diff_value(diff, "value_a", "old_value") == "10"
    assert _extract_diff_value(diff, "missing", "old_value") == "5"
    assert _extract_diff_value(diff, "missing", "absent") == "None"

    assert _extract_diff_text(diff, "field_name", "field") == "start_time"
    assert _extract_diff_text(diff, "nonexistent", "field_name") == "start_time"
    assert _extract_diff_text(diff, "nonexistent", "absent") == ""


def test_convert_diff_to_pair_fallbacks() -> None:
    """Test _convert_diff_to_pair fallback defaults."""
    pair = _convert_diff_to_pair({})
    assert pair["source_a"] == "Previous State"
    assert pair["source_b"] == "Current State"
    assert pair["value_a"] == "None"
    assert pair["value_b"] == "None"


def test_extract_snapshot_and_summary_fallback_comparisons() -> None:
    """Test _extract_snapshot_comparison and summary fallback."""
    # 1. Snapshot comparison
    item_snap = {"field": "venue", "summary": "diff sum"}
    before = {"venue": "Rink A"}
    after = {"venue": "Rink B"}
    snap_res = _extract_snapshot_comparison(item_snap, before, after)
    assert len(snap_res) == 1
    assert snap_res[0]["value_a"] == "Rink A"
    assert snap_res[0]["value_b"] == "Rink B"

    # 2. Summary fallback with resolved_value
    item_sum = {
        "summary": "Time mismatch",
        "resolved_value": "20:00",
        "notes": "Reviewed",
    }
    sum_res = _extract_summary_fallback(item_sum)
    assert len(sum_res) == 1
    assert sum_res[0]["value_a"] == "Time mismatch"
    assert sum_res[0]["value_b"] == "20:00"

    # 3. Default empty fallback
    empty_res = _extract_summary_fallback({})
    assert len(empty_res) == 1
    assert empty_res[0]["source_a"] == "Source A"
    assert empty_res[0]["value_a"] == "Unspecified"


def test_extract_comparison_pairs_branches() -> None:
    """Test _extract_comparison_pairs covering all dispatch branches."""
    # Branch 1: discrepancies
    item_d = {"discrepancies": [{"source_a": "s1", "source_b": "s2", "value_a": "a"}]}
    assert _extract_comparison_pairs(item_d)[0]["source_a"] == "s1"

    # Branch 2: field_diffs
    item_f = {"field_diffs": [{"source_a": "f1", "value_a": "v1"}]}
    assert _extract_comparison_pairs(item_f)[0]["source_a"] == "f1"

    # Branch 3: snapshot fallback
    item_s = {"snapshot_before": {"value": "b"}, "snapshot_after": {"value": "a"}}
    assert _extract_comparison_pairs(item_s)[0]["source_a"] == "Previous Snapshot"

    # Branch 4: summary fallback
    item_sum = {"summary": "Discrepancy summary"}
    assert _extract_comparison_pairs(item_sum)[0]["source_a"] == "Discrepancy"


def test_format_recorded_time() -> None:
    """Test _format_recorded_time with various inputs."""
    assert _format_recorded_time(None) == "Unknown"
    assert _format_recorded_time("") == "Unknown"
    assert (
        _format_recorded_time("2026-09-12T14:30:00+00:00") == "2026-09-12 14:30:00 UTC"
    )
    assert _format_recorded_time("2026-09-12T14:30:00") == "2026-09-12 14:30:00 UTC"


def test_tally_single_conflict_and_metrics() -> None:
    """Test _tally_single_conflict and _count_conflict_metrics."""
    tally = [0, 0, 0]
    _tally_single_conflict({"severity": "critical", "requires_review": True}, tally)
    assert tally == [1, 1, 0]

    items = [
        {"severity": "critical", "requires_review": True},
        {"severity": "high", "requires_review": False},
        {"severity": "medium", "requires_review": True},
        {"severity": "low", "requires_review": False},
    ]
    metrics = _count_conflict_metrics(items)
    assert metrics["total"] == 4
    assert metrics["review_needed"] == 2
    assert metrics["critical_count"] == 1
    assert metrics["high_count"] == 1


def test_is_any_filter_active() -> None:
    """Test _is_any_filter_active detection."""
    assert not _is_any_filter_active({})
    assert _is_any_filter_active({"severity": "critical"})
    assert _is_any_filter_active({"game_id": "game-1"})
    assert _is_any_filter_active({"field": "venue"})
    assert _is_any_filter_active({"requires_review": True})
    assert _is_any_filter_active({"requires_review": False})


def test_convert_conflict_item_variants() -> None:
    """Test _convert_conflict_item with domain model, dict, and non-dict."""
    # 1. DetectedConflict domain model
    dc = _build_sample_detected_conflict()
    item_dc = _convert_conflict_item(dc)
    assert item_dc["game_id"] == "ecu-unc-20241011"

    # 2. Raw dict
    raw = {"game_id": "raw-1", "severity": "low"}
    assert _convert_conflict_item(raw) == raw

    # 3. Arbitrary object without to_dict
    assert _convert_conflict_item(12345) == {}


def test_change_model_to_conflict_without_diffs() -> None:
    """Test _change_model_to_conflict when field_diffs is None or empty."""
    change = GameChangeModel(
        id=99,
        canonical_game_id="game-empty-diff",
        change_type="CONFLICT",
        summary="Summary without diffs",
        field_diffs=None,
        recorded_at=None,
    )
    result = _change_model_to_conflict(change)
    assert result["conflict_id"] == "change-99"
    assert result["field"] == "schedule"
    assert result["severity"] == "medium"
    assert result["recorded_at"] is None


def test_extract_conflicts_no_engine() -> None:
    """Test _extract_conflicts when db_engine is not set."""
    req = MagicMock()
    req.app.state = MagicMock()
    req.app.state.conflicts_override = None
    req.app.state.db_engine = None

    assert _extract_conflicts(req) == []


def test_matches_filter_helpers() -> None:
    """Test text, id, and review match helpers."""
    assert _matches_text(None, None)
    assert _matches_text("High", "high")
    assert not _matches_text("High", "low")

    assert _matches_id(None, None)
    assert _matches_id("game-1", "game-1")
    assert not _matches_id("game-1", "game-2")

    flag_val = True
    assert _matches_review(flag_val, expected=None)
    assert _matches_review(flag_val, expected=True)
    assert not _matches_review(flag_val, expected=False)


def test_matches_conflict_filter() -> None:
    """Test _matches_conflict_filter with various criteria."""
    item = {
        "severity": "high",
        "game_id": "game-1",
        "field": "venue",
        "requires_review": True,
    }
    assert _matches_conflict_filter(
        item,
        severity="high",
        game_id="game-1",
        field_name="venue",
        requires_review=True,
    )
    assert not _matches_conflict_filter(
        item,
        severity="low",
        game_id="game-1",
        field_name="venue",
        requires_review=True,
    )
    assert not _matches_conflict_filter(
        item,
        severity="high",
        game_id="game-2",
        field_name="venue",
        requires_review=True,
    )
    assert not _matches_conflict_filter(
        item,
        severity="high",
        game_id="game-1",
        field_name="start_time",
        requires_review=True,
    )
    assert not _matches_conflict_filter(
        item,
        severity="high",
        game_id="game-1",
        field_name="venue",
        requires_review=False,
    )


def test_build_pagination_context_unit() -> None:
    """Test _build_pagination_context boundaries."""
    req = MagicMock()
    req.url.include_query_params = lambda **params: f"/api/v1/conflicts?{params}"

    ctx_0 = _build_pagination_context(req, total=0, limit=20, offset=0)
    assert ctx_0["showing_start"] == 0
    assert ctx_0["showing_end"] == 0
    assert not ctx_0["has_prev"]
    assert not ctx_0["has_next"]

    ctx_mid = _build_pagination_context(req, total=100, limit=20, offset=20)
    assert ctx_mid["showing_start"] == 21
    assert ctx_mid["showing_end"] == 40
    assert ctx_mid["has_prev"]
    assert ctx_mid["has_next"]


def test_format_active_filters_and_context_builder() -> None:
    """Test _format_active_filters and _build_conflicts_context."""
    filters = _format_active_filters(
        severity="critical",
        game_id="ecu-1",
        field_name="start_time",
        requires_review=True,
    )
    assert filters["severity"] == "critical"
    assert filters["game_id"] == "ecu-1"
    assert filters["field"] == "start_time"
    assert filters["requires_review"] is True

    items = [{"severity": "critical", "requires_review": True}]
    pag = {"total_count": 1}
    ctx = _build_conflicts_context(items, items, pagination=pag, filters=filters)
    assert ctx["active_tab"] == "conflicts"
    assert ctx["has_active_filters"] is True
    assert len(ctx["conflicts"]) == 1


def test_enrich_conflict_items_and_single() -> None:
    """Test _enrich_conflict_items and _enrich_single_conflict."""
    item = {
        "severity": "high",
        "discrepancies": [{"source_a": "a", "value_a": "1"}],
        "recorded_at": "2026-09-12T10:00:00Z",
    }
    single = _enrich_single_conflict(item)
    assert single["severity_label"] == "High"
    assert len(single["comparisons"]) == 1

    plural = _enrich_conflict_items([item])
    assert len(plural) == 1
    assert plural[0]["severity_label"] == "High"


def test_extract_diff_and_discrepancy_comparisons() -> None:
    """Test _extract_diff_comparisons and _extract_discrepancy_comparisons."""
    diffs = [{"field_name": "venue", "old_value": "V1", "new_value": "V2"}]
    res_diffs = _extract_diff_comparisons(diffs)
    assert len(res_diffs) == 1
    assert res_diffs[0]["field"] == "venue"

    discs = [{"field": "status", "source_a": "s1", "value_a": "SCHEDULED"}]
    res_discs = _extract_discrepancy_comparisons(discs)
    assert len(res_discs) == 1
    assert res_discs[0]["field"] == "status"


def test_extract_snapshot_or_fallback_direct() -> None:
    """Test _extract_snapshot_or_fallback_comparisons direct fallback."""
    item_empty: dict[str, Any] = {}
    res = _extract_snapshot_or_fallback_comparisons(item_empty)
    assert len(res) == 1
    assert res[0]["source_a"] == "Source A"

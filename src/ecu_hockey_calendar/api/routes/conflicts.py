"""Administrative conflict inspection and discrepancy review route handlers."""

# pylint: disable=too-many-lines

from __future__ import annotations

import json
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Protocol,
    cast,
    runtime_checkable,
)
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import Select, func, select

from ecu_hockey_calendar.api.auth import verify_admin_token
from ecu_hockey_calendar.api.negotiation import negotiate_response
from ecu_hockey_calendar.storage.engine import get_sync_session
from ecu_hockey_calendar.storage.models import GameChangeModel
from ecu_hockey_calendar.storage.overrides import (
    CONFLICT_RESOLVED_CHANGE_TYPE,
)
from ecu_hockey_calendar.storage.overrides import (
    resolve_conflict as storage_resolve_conflict,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

conflicts_router = APIRouter(
    tags=["Administration", "Conflicts"],
    dependencies=[Depends(verify_admin_token)],
)

CONFLICT_CHANGE_TYPES: tuple[str, ...] = (
    "CONFLICT_DETECTED",
    "CONFLICT",
    "DISCREPANCY",
)
ALL_CONFLICT_CHANGE_TYPES: tuple[str, ...] = (
    *CONFLICT_CHANGE_TYPES,
    CONFLICT_RESOLVED_CHANGE_TYPE,
)


@runtime_checkable
class ConflictDictConvertible(Protocol):
    """Protocol for objects convertible to dictionary representation."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize object attributes to dictionary."""


@runtime_checkable
class ResolvableConflictItem(Protocol):
    """Protocol for in-memory conflict objects with resolution fields."""

    resolved: bool
    resolved_value: str | None
    resolved_by_source: str | None
    requires_review: bool


def _convert_conflict_item(item: object) -> dict[str, Any]:
    """Normalize domain conflict object or model into an API dictionary."""
    if isinstance(item, ConflictDictConvertible):
        raw_dict = item.to_dict()
        if "game_key" in raw_dict and "game_id" not in raw_dict:
            raw_dict["game_id"] = raw_dict["game_key"]

        return raw_dict

    if isinstance(item, dict):
        return dict(item)

    return {}


def _extract_first_field(diffs: list[dict[str, Any]]) -> str:
    """Extract primary conflicting field name from diffs."""
    if not diffs:
        return "schedule"

    return str(
        diffs[0].get("field") or diffs[0].get("field_name") or "schedule",
    )


def _extract_first_severity(diffs: list[dict[str, Any]]) -> str:
    """Extract primary severity level from diffs."""
    if not diffs:
        return "medium"

    return str(diffs[0].get("severity") or "medium")


def _resolved_value(*, is_resolved: bool, diffs: list[dict[str, Any]]) -> object:
    """Extract resolved value from diffs if resolved."""
    if is_resolved and diffs:
        return diffs[0].get("new_value")

    return None


def _recorded_at_iso(dt: datetime | None) -> str | None:
    """Return ISO string for datetime or None."""
    return dt.isoformat() if dt else None


def _conflict_severity(*, is_resolved: bool, diffs: list[dict[str, Any]]) -> str:
    """Determine conflict severity considering resolution status."""
    return "low" if is_resolved else _extract_first_severity(diffs)


def _change_model_to_conflict(change: GameChangeModel) -> dict[str, Any]:
    """Convert a GameChangeModel entity into an API conflict representation."""
    diffs = change.field_diffs or []
    is_resolved = change.change_type == CONFLICT_RESOLVED_CHANGE_TYPE

    return {
        "conflict_id": f"change-{change.id}",
        "game_id": change.canonical_game_id,
        "field": _extract_first_field(diffs),
        "severity": _conflict_severity(is_resolved=is_resolved, diffs=diffs),
        "requires_review": not is_resolved,
        "resolved": is_resolved,
        "resolved_value": _resolved_value(is_resolved=is_resolved, diffs=diffs),
        "summary": change.summary,
        "field_diffs": diffs,
        "snapshot_before": change.snapshot_before,
        "snapshot_after": change.snapshot_after,
        "recorded_at": _recorded_at_iso(change.recorded_at),
    }


def _active_conflicts_query(
    change_types: tuple[str, ...] = CONFLICT_CHANGE_TYPES,
) -> Select[tuple[GameChangeModel]]:
    """Construct SQL statement selecting the latest change for active conflicts."""
    subq = (
        select(
            GameChangeModel.canonical_game_id,
            func.max(GameChangeModel.id).label("max_id"),
        )
        .group_by(GameChangeModel.canonical_game_id)
        .subquery()
    )
    return (
        select(GameChangeModel)
        .join(subq, GameChangeModel.id == subq.c.max_id)
        .where(GameChangeModel.change_type.in_(change_types))
        .order_by(GameChangeModel.recorded_at.desc())
    )


def _resolve_query_change_types(
    status_filter: str | None,
    *,
    include_resolved: bool,
) -> tuple[str, ...]:
    """Determine GameChangeModel types to query based on status filter."""
    norm_status = str(status_filter or "").strip().lower()
    if norm_status == "resolved":
        return (CONFLICT_RESOLVED_CHANGE_TYPE,)

    if include_resolved or norm_status == "all":
        return ALL_CONFLICT_CHANGE_TYPES

    return CONFLICT_CHANGE_TYPES


def _matches_status(item: dict[str, Any], norm_status: str) -> bool:
    """Check if item matches the status filter."""
    if norm_status == "resolved":
        return item.get("resolved") is True

    return not item.get("resolved")


def _should_include_all(norm_status: str, *, include_resolved: bool) -> bool:
    """Check if all conflicts should be included without status filtering."""
    return include_resolved or norm_status == "all"


def _filter_override_by_status(
    items: list[dict[str, Any]],
    status_filter: str | None,
    *,
    include_resolved: bool,
) -> list[dict[str, Any]]:
    """Filter in-memory override conflicts by status."""
    norm_status = str(status_filter or "").strip().lower()
    if _should_include_all(norm_status, include_resolved=include_resolved):
        return items

    return [c for c in items if _matches_status(c, norm_status)]


def _extract_conflicts(
    request: Request,
    *,
    status_filter: str | None = None,
    include_resolved: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve raw conflicts from application state or relational database."""
    override = getattr(request.app.state, "conflicts_override", None)
    if override is not None:
        raw_items = [_convert_conflict_item(c) for c in override]
        return _filter_override_by_status(
            raw_items,
            status_filter,
            include_resolved=include_resolved,
        )

    engine: Engine | None = getattr(request.app.state, "db_engine", None)
    if engine is None:
        return []

    change_types = _resolve_query_change_types(
        status_filter,
        include_resolved=include_resolved,
    )
    with get_sync_session(engine) as session:
        stmt = _active_conflicts_query(change_types)
        changes = session.scalars(stmt).all()
        return [_change_model_to_conflict(chg) for chg in changes]


def _matches_text(actual: object, expected: str | None) -> bool:
    """Check whether actual string value matches expected string case-insensitively."""
    if not expected:
        return True

    return str(actual or "").strip().lower() == expected.strip().lower()


def _matches_id(actual: object, expected: str | None) -> bool:
    """Check whether actual identifier matches expected identifier."""
    if not expected:
        return True

    return str(actual or "").strip() == expected.strip()


def _matches_review(actual: object, *, expected: bool | None) -> bool:
    """Check whether review requirement flag matches expected value."""
    if expected is None:
        return True

    return actual == expected


def _matches_conflict_filter(
    item: dict[str, Any],
    *,
    severity: str | None,
    game_id: str | None,
    field_name: str | None,
    requires_review: bool | None,
) -> bool:
    """Verify if a conflict item satisfies all applied filter conditions."""
    if not _matches_text(item.get("severity"), severity):
        return False

    if not _matches_id(item.get("game_id"), game_id):
        return False

    if not _matches_text(item.get("field"), field_name):
        return False

    return _matches_review(item.get("requires_review"), expected=requires_review)


def _format_severity_meta(severity: str | None) -> tuple[str, str, str]:
    """Return normalized severity slug, display text label, and visual symbol."""
    sev = str(severity or "").strip().lower()
    if sev == "critical":
        return ("critical", "Critical", "⛔")

    if sev == "high":
        return ("high", "High", "⚠️")

    if sev == "low":
        return ("low", "Low", "✓")

    return ("medium", "Medium", "⚡")


def _format_raw_value(val: object) -> str:
    """Format an arbitrary value into a display string."""
    if val is None:
        return "N/A"

    return str(val)


def _convert_discrepancy_to_pair(d: dict[str, Any]) -> dict[str, Any]:
    """Convert a single discrepancy dictionary to a comparison pair."""
    src_a = str(d.get("source_a") or "Source A")
    src_b = str(d.get("source_b") or "Source B")
    return {
        "source_a": src_a,
        "value_a": _format_raw_value(d.get("value_a")),
        "source_b": src_b,
        "value_b": _format_raw_value(d.get("value_b")),
        "field": str(d.get("field", "")),
        "notes": str(d.get("notes", "")),
    }


def _extract_discrepancy_comparisons(
    discrepancies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract side-by-side comparison items from domain discrepancy list."""
    return [_convert_discrepancy_to_pair(d) for d in discrepancies]


def _extract_diff_value(
    diff: dict[str, Any],
    explicit_key: str,
    fallback_key: str,
) -> str:
    """Extract a diff value checking explicit key before fallback key."""
    if explicit_key in diff:
        return str(diff[explicit_key])

    return str(diff.get(fallback_key, "None"))


def _extract_diff_text(diff: dict[str, Any], key1: str, key2: str) -> str:
    """Extract string value from first available key in diff."""
    val = diff.get(key1)
    if val:
        return str(val)

    return str(diff.get(key2, ""))


def _convert_diff_to_pair(diff: dict[str, Any]) -> dict[str, Any]:
    """Convert a single field diff dictionary to a comparison pair."""
    src_a = str(diff.get("source_a") or "Previous State")
    src_b = str(diff.get("source_b") or "Current State")
    return {
        "source_a": src_a,
        "value_a": _extract_diff_value(diff, "value_a", "old_value"),
        "source_b": src_b,
        "value_b": _extract_diff_value(diff, "value_b", "new_value"),
        "field": _extract_diff_text(diff, "field_name", "field"),
        "notes": _extract_diff_text(diff, "human_description", "notes"),
    }


def _extract_diff_comparisons(
    diffs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract side-by-side comparison items from field diff records."""
    return [_convert_diff_to_pair(diff) for diff in diffs]


def _extract_snapshot_comparison(
    item: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
) -> list[dict[str, Any]]:
    """Generate comparison pair from before and after snapshot dicts."""
    field = str(item.get("field") or "value")
    return [
        {
            "source_a": "Previous Snapshot",
            "value_a": str(before.get(field, "N/A")),
            "source_b": "Current Snapshot",
            "value_b": str(after.get(field, "N/A")),
            "field": field,
            "notes": str(item.get("summary") or ""),
        },
    ]


def _extract_summary_fallback(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate comparison pair from summary or default fallback."""
    field = str(item.get("field") or "value")
    summary = item.get("summary")
    if summary:
        return [
            {
                "source_a": "Discrepancy",
                "value_a": str(summary),
                "source_b": "Resolution",
                "value_b": str(item.get("resolved_value") or "Pending Review"),
                "field": field,
                "notes": str(item.get("notes") or ""),
            },
        ]

    return [
        {
            "source_a": "Source A",
            "value_a": "Unspecified",
            "source_b": "Source B",
            "value_b": "Unspecified",
            "field": field,
            "notes": "",
        },
    ]


def _extract_snapshot_or_fallback_comparisons(
    item: dict[str, Any],
) -> list[dict[str, Any]]:
    """Generate fallback comparison blocks from snapshots or summaries."""
    before = item.get("snapshot_before")
    after = item.get("snapshot_after")
    if isinstance(before, dict) and isinstance(after, dict):
        return _extract_snapshot_comparison(item, before, after)

    return _extract_summary_fallback(item)


def _extract_comparison_pairs(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalized side-by-side comparison records for conflict item."""
    discrepancies = item.get("discrepancies")
    if isinstance(discrepancies, list) and discrepancies:
        return _extract_discrepancy_comparisons(discrepancies)

    diffs = item.get("field_diffs")
    if isinstance(diffs, list) and diffs:
        return _extract_diff_comparisons(diffs)

    return _extract_snapshot_or_fallback_comparisons(item)


def _format_recorded_time(recorded_at: str | None) -> str:
    """Format an ISO timestamp string into human-readable representation."""
    if not recorded_at:
        return "Unknown"

    cleaned = recorded_at.replace("T", " ")
    if "+" in cleaned:
        cleaned = cleaned.split("+")[0]

    return f"{cleaned[:19]} UTC"


def _enrich_single_conflict(item: dict[str, Any]) -> dict[str, Any]:
    """Enrich conflict dictionary with comparison items and badge metadata."""
    sev_lower, sev_label, sev_icon = _format_severity_meta(item.get("severity"))
    return {
        **item,
        "severity_lower": sev_lower,
        "severity_label": sev_label,
        "severity_icon": sev_icon,
        "comparisons": _extract_comparison_pairs(item),
        "recorded_at_formatted": _format_recorded_time(item.get("recorded_at")),
    }


def _enrich_conflict_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich list of conflict records for template rendering."""
    return [_enrich_single_conflict(item) for item in items]


def _build_pagination_context(
    request: Request,
    total: int,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Construct pagination details and navigation URLs."""
    start_pos = (offset + 1) if total > 0 else 0
    end_pos = min(total, offset + limit) if total > 0 else 0

    prev_url: str | None = None
    if offset > 0:
        prev_offset = max(0, offset - limit)
        prev_url = str(
            request.url.include_query_params(offset=prev_offset, limit=limit),
        )

    next_url: str | None = None
    if offset + limit < total:
        next_offset = offset + limit
        next_url = str(
            request.url.include_query_params(offset=next_offset, limit=limit),
        )

    return {
        "total_count": total,
        "limit": limit,
        "offset": offset,
        "showing_start": start_pos,
        "showing_end": end_pos,
        "has_prev": prev_url is not None,
        "has_next": next_url is not None,
        "prev_url": prev_url,
        "next_url": next_url,
    }


def _tally_single_conflict(
    item: dict[str, Any],
    counts: list[int],
) -> None:
    """Update tally counts: [review_needed, critical, high]."""
    if item.get("requires_review"):
        counts[0] += 1

    sev = str(item.get("severity") or "").strip().lower()
    if sev == "critical":
        counts[1] += 1
    elif sev == "high":
        counts[2] += 1


def _count_conflict_metrics(conflicts: list[dict[str, Any]]) -> dict[str, int]:
    """Compute summary counts for top banner metrics."""
    counts = [0, 0, 0]
    for c in conflicts:
        _tally_single_conflict(c, counts)

    return {
        "total": len(conflicts),
        "review_needed": counts[0],
        "critical_count": counts[1],
        "high_count": counts[2],
    }


def _is_any_filter_active(filters: dict[str, Any]) -> bool:
    """Check whether any filter parameter is actively constraining results."""
    if filters.get("severity") or filters.get("game_id") or filters.get("field"):
        return True

    return filters.get("requires_review") is not None


def _format_active_filters(
    *,
    severity: str | None,
    game_id: str | None,
    field_name: str | None,
    requires_review: bool | None,
) -> dict[str, Any]:
    """Normalize filter dictionary values for template form pre-population."""
    return {
        "severity": severity or "",
        "game_id": game_id or "",
        "field": field_name or "",
        "requires_review": requires_review,
    }


def _build_conflicts_context(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    all_conflicts: list[dict[str, Any]],
    paginated_conflicts: list[dict[str, Any]],
    *,
    pagination: dict[str, Any],
    filters: dict[str, Any],
    resolved_success: bool = False,
    resolved_conflict_id: str = "",
    token: str = "",
) -> dict[str, Any]:
    """Assemble complete Jinja2 template context for conflicts.html."""
    return {
        "active_tab": "conflicts",
        "conflicts": _enrich_conflict_items(paginated_conflicts),
        "pagination": pagination,
        "metrics": _count_conflict_metrics(all_conflicts),
        "filters": filters,
        "has_active_filters": _is_any_filter_active(filters),
        "resolved_success": resolved_success,
        "resolved_conflict_id": resolved_conflict_id,
        "token": token,
    }


CONFLICTS_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Filtered and paginated schedule conflict records.",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "total_conflicts": {"type": "integer"},
                        "filtered_count": {"type": "integer"},
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                        "conflicts": {"type": "array"},
                    },
                },
            },
            "text/html": {
                "schema": {"type": "string"},
            },
        },
    },
}


@conflicts_router.get(
    "/conflicts",
    summary="List Schedule Conflicts and Discrepancies",
    description=(
        "Administrative endpoint listing multi-source schedule discrepancies with "
        "full field diff payloads. Requires administrator Bearer or API-key token."
    ),
    response_model=None,
    responses=CONFLICTS_RESPONSES,
)
@conflicts_router.get(
    "/api/v1/conflicts",
    summary="List Schedule Conflicts and Discrepancies (REST API)",
    description=(
        "Administrative endpoint listing multi-source schedule discrepancies with "
        "full field diff payloads. Requires administrator Bearer or API-key token."
    ),
    response_model=None,
    responses=CONFLICTS_RESPONSES,
)
def list_schedule_conflicts(  # noqa: PLR0913 # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    request: Request,
    *,
    severity: Annotated[
        str | None,
        Query(
            description=(
                "Filter conflicts by severity level "
                "(e.g. 'low', 'medium', 'high', 'critical')."
            ),
        ),
    ] = None,
    game_id: Annotated[
        str | None,
        Query(
            description="Filter conflicts by canonical game identifier.",
        ),
    ] = None,
    field_name: Annotated[
        str | None,
        Query(
            alias="field",
            description=(
                "Filter conflicts by conflicting attribute field "
                "(e.g. 'venue', 'start_time')."
            ),
        ),
    ] = None,
    requires_review: Annotated[
        bool | None,
        Query(
            description=(
                "If True, only return conflicts flagged as requiring human review."
            ),
        ),
    ] = None,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            description=(
                "Filter conflicts by operational status "
                "('active', 'resolved', or 'all')."
            ),
        ),
    ] = None,
    include_resolved: Annotated[
        bool,
        Query(
            description="If True, include resolved conflict records.",
        ),
    ] = False,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Maximum number of conflict records to return.",
        ),
    ] = 50,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Number of conflict records to skip for pagination.",
        ),
    ] = 0,
) -> Response:
    """Retrieve filtered and paginated schedule conflict records with diffs.

    Args:
        request: Incoming FastAPI HTTP request.
        severity: Optional severity filter.
        game_id: Optional game ID filter.
        field_name: Optional conflict field filter.
        requires_review: Optional review flag filter.
        status_filter: Optional status filter ('active', 'resolved', 'all').
        include_resolved: Optional flag to include resolved conflicts.
        limit: Max pagination count.
        offset: Pagination offset.

    Returns:
        Content-negotiated HTML triage dashboard or JSON response.
    """
    all_conflicts = _extract_conflicts(
        request,
        status_filter=status_filter,
        include_resolved=include_resolved,
    )
    filtered = [
        c
        for c in all_conflicts
        if _matches_conflict_filter(
            c,
            severity=severity,
            game_id=game_id,
            field_name=field_name,
            requires_review=requires_review,
        )
    ]

    total_count = len(filtered)
    paginated = filtered[offset : offset + limit]

    payload = {
        "total_conflicts": total_count,
        "filtered_count": len(paginated),
        "limit": limit,
        "offset": offset,
        "conflicts": paginated,
    }

    pagination = _build_pagination_context(request, total_count, limit, offset)
    filters = _format_active_filters(
        severity=severity,
        game_id=game_id,
        field_name=field_name,
        requires_review=requires_review,
    )
    context = _build_conflicts_context(
        all_conflicts,
        paginated,
        pagination=pagination,
        filters=filters,
        resolved_success=(request.query_params.get("resolved") == "1"),
        resolved_conflict_id=str(request.query_params.get("conflict_id", "")),
        token=str(request.query_params.get("token", "")),
    )

    return negotiate_response(
        request,
        payload,
        "conflicts.html",
        context=context,
    )


def _parse_form_body(body_bytes: bytes) -> dict[str, str]:
    """Parse url-encoded form body without external dependencies."""
    parsed = parse_qs(
        body_bytes.decode("utf-8", errors="replace"),
        keep_blank_values=True,
    )
    return {k: v[0] if v else "" for k, v in parsed.items()}


async def _extract_resolve_params(request: Request) -> dict[str, Any]:
    """Extract resolution parameters from JSON, Form, or query parameters."""
    ctype = request.headers.get("content-type", "").lower()
    if "application/json" in ctype:
        try:
            data = await request.json()
            if isinstance(data, dict):
                return data
        except (ValueError, json.JSONDecodeError):
            # Fall back to form or query parameters if JSON payload parsing fails
            pass
    elif "form" in ctype:
        body = await request.body()
        return _parse_form_body(body)

    return dict(request.query_params)


def _match_conflict_ident(c: object, conflict_id: str) -> bool:
    """Check if conflict matches identifier or game key."""
    if isinstance(c, dict):
        return conflict_id in (c.get("conflict_id"), c.get("game_id"))

    cid = getattr(c, "conflict_id", None)
    gkey = getattr(c, "game_key", None) or getattr(c, "game_id", None)
    return conflict_id in (cid, gkey)


def _find_override_conflict(items: list[object], conflict_id: str) -> object | None:
    """Find matching conflict object in override list by id or game key."""
    for c in items:
        if _match_conflict_ident(c, conflict_id):
            return c

    return None


def _determine_resolved_value(value: str | None, accept_source: str | None) -> str:
    """Compute resolution value string or raise ValueError."""
    if value:
        return value

    if accept_source:
        return f"Accepted {accept_source}"

    msg = "Either 'value' or 'accept_source' must be provided."
    raise ValueError(msg)


def _mutate_in_memory_dict(
    c: dict[str, Any],
    final_val: str,
    accept_source: str | None,
    field: str | None,
) -> None:
    """Mutate in-memory dictionary conflict item."""
    c["resolved"] = True
    c["resolved_value"] = final_val
    c["resolved_by_source"] = accept_source or "manual"
    c["requires_review"] = False
    if field:
        c["field"] = field


def _mutate_in_memory_object(
    c: ResolvableConflictItem,
    final_val: str,
    accept_source: str | None,
) -> None:
    """Mutate in-memory object conflict item."""
    c.resolved = True
    c.resolved_value = final_val
    c.resolved_by_source = accept_source or "manual"
    c.requires_review = False


def _apply_in_memory_resolution(
    c: dict[str, Any] | ResolvableConflictItem,
    field: str | None,
    value: str | None,
    accept_source: str | None,
) -> str:
    """Apply resolution to an in-memory conflict item."""
    final_val = _determine_resolved_value(value, accept_source)
    if isinstance(c, dict):
        _mutate_in_memory_dict(c, final_val, accept_source, field)
    else:
        _mutate_in_memory_object(c, final_val, accept_source)

    return final_val


def _extract_field_and_value(
    params: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Extract field name and override value aliases from parameters."""
    raw_field = params.get("field") or params.get("field_name")
    raw_val = params.get("value") or params.get("override_value")
    field = str(raw_field) if raw_field is not None else None
    val = str(raw_val) if raw_val is not None else None
    return field, val


def _build_in_memory_result(
    conflict_id: str,
    field: str | None,
    final_val: str,
    accept_src: str | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Build response dictionary for in-memory resolution."""
    return {
        "status": "resolved",
        "conflict_id": conflict_id,
        "game_id": conflict_id,
        "field": field or "schedule",
        "value": final_val,
        "accepted_source": accept_src,
        "resolved_by": str(params.get("resolved_by") or "admin"),
        "notes": params.get("notes"),
        "message": "Conflict resolved successfully.",
    }


def _resolve_in_memory_state(
    request: Request,
    conflict_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Handle resolution when in-memory conflicts_override is active."""
    items = getattr(request.app.state, "conflicts_override", None) or []
    item = _find_override_conflict(items, conflict_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conflict '{conflict_id}' not found.",
        )

    field, val = _extract_field_and_value(params)
    accept_src = params.get("accept_source")
    target = cast("dict[str, Any] | ResolvableConflictItem", item)
    try:
        final_val = _apply_in_memory_resolution(target, field, val, accept_src)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err

    return _build_in_memory_result(conflict_id, field, final_val, accept_src, params)


def _build_resolve_http_error(exc: ValueError) -> HTTPException:
    """Build appropriate HTTPException from storage resolution ValueError."""
    err_msg = str(exc)
    if "not found" in err_msg.lower():
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=err_msg,
        )

    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=err_msg,
    )


def _execute_db_resolution(
    session: Session,
    conflict_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Execute storage conflict resolution within a session."""
    field, val = _extract_field_and_value(params)
    res = storage_resolve_conflict(
        session,
        conflict_id,
        field_name=field,
        override_value=val,
        accept_source=params.get("accept_source"),
        resolved_by=str(params.get("resolved_by") or "admin"),
        notes=params.get("notes"),
    )
    session.commit()
    res["message"] = "Conflict resolved successfully."
    return res


def _resolve_in_database(
    engine: Engine,
    conflict_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Resolve conflict via database storage service."""
    try:
        with get_sync_session(engine) as session:
            return _execute_db_resolution(session, conflict_id, params)
    except ValueError as exc:
        raise _build_resolve_http_error(exc) from exc


def _dispatch_conflict_resolution(
    request: Request,
    conflict_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Route conflict resolution to in-memory state or relational database."""
    override = getattr(request.app.state, "conflicts_override", None)
    if override is not None:
        return _resolve_in_memory_state(request, conflict_id, params)

    engine: Engine | None = getattr(request.app.state, "db_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conflict '{conflict_id}' not found (no database configured).",
        )

    return _resolve_in_database(engine, conflict_id, params)


def _wants_html_response(request: Request) -> bool:
    """Check whether request prefers HTML redirect/response."""
    accept = request.headers.get("accept", "").lower()
    ctype = request.headers.get("content-type", "").lower()
    return "text/html" in accept or "form" in ctype


def _build_resolve_redirect(request: Request, conflict_id: str) -> Response:
    """Construct 303 redirect to /conflicts dashboard with success parameters."""
    token = request.query_params.get("token")
    redirect_url = f"/conflicts?resolved=1&conflict_id={conflict_id}"
    if token:
        redirect_url += f"&token={token}"

    return Response(
        status_code=303,
        headers={"Location": redirect_url},
    )


RESOLVE_CONFLICT_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Conflict successfully resolved and override recorded.",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "conflict_id": {"type": "string"},
                        "game_id": {"type": "string"},
                        "field": {"type": "string"},
                        "value": {"type": "string"},
                        "accepted_source": {"type": "string"},
                        "resolved_by": {"type": "string"},
                        "notes": {"type": "string"},
                        "message": {"type": "string"},
                    },
                },
            },
        },
    },
    400: {"description": "Missing override value or unresolvable source value."},
    404: {"description": "Conflict record not found."},
}


@conflicts_router.post(
    "/conflicts/{conflict_id}/resolve",
    summary="Resolve Schedule Conflict (Interactive Web Form)",
    description=(
        "Administrative endpoint to manually resolve a schedule conflict "
        "and record an attribute override. Accepts JSON or URL-encoded form data."
    ),
    response_model=None,
    responses=RESOLVE_CONFLICT_RESPONSES,
)
@conflicts_router.post(
    "/api/v1/conflicts/{conflict_id}/resolve",
    summary="Resolve Schedule Conflict (REST API)",
    description=(
        "Administrative endpoint to manually resolve a schedule conflict "
        "and record an attribute override. Accepts JSON or URL-encoded form data."
    ),
    response_model=None,
    responses=RESOLVE_CONFLICT_RESPONSES,
)
async def resolve_schedule_conflict(
    conflict_id: str,
    request: Request,
) -> Response:
    """Resolve a conflict by setting an attribute override or accepting a source.

    Args:
        conflict_id: Identifier of the conflict or canonical game ID.
        request: Incoming FastAPI HTTP request.

    Returns:
        Content-negotiated 303 Redirect for web forms or 200 JSON payload.
    """
    params = await _extract_resolve_params(request)
    result = _dispatch_conflict_resolution(request, conflict_id, params)
    if _wants_html_response(request):
        return _build_resolve_redirect(request, conflict_id)

    return Response(
        content=json.dumps(result),
        media_type="application/json",
        status_code=200,
    )


__all__ = [
    "ALL_CONFLICT_CHANGE_TYPES",
    "CONFLICT_CHANGE_TYPES",
    "ConflictDictConvertible",
    "_active_conflicts_query",
    "list_schedule_conflicts",
    "resolve_schedule_conflict",
]

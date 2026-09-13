"""Administrative conflict inspection and discrepancy review route handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Protocol, runtime_checkable

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select

from ecu_hockey_calendar.api.auth import verify_admin_token
from ecu_hockey_calendar.api.negotiation import negotiate_response
from ecu_hockey_calendar.storage.engine import get_sync_session
from ecu_hockey_calendar.storage.models import GameChangeModel

if TYPE_CHECKING:
    from sqlalchemy import Engine

conflicts_router = APIRouter(
    prefix="/api/v1/conflicts",
    tags=["Administration", "Conflicts"],
    dependencies=[Depends(verify_admin_token)],
)


@runtime_checkable
class ConflictDictConvertible(Protocol):
    """Protocol for objects convertible to dictionary representation."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize object attributes to dictionary."""


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


def _change_model_to_conflict(change: GameChangeModel) -> dict[str, Any]:
    """Convert a GameChangeModel entity into an API conflict representation."""
    diffs = change.field_diffs or []

    return {
        "conflict_id": f"change-{change.id}",
        "game_id": change.canonical_game_id,
        "field": _extract_first_field(diffs),
        "severity": _extract_first_severity(diffs),
        "requires_review": True,
        "resolved": False,
        "summary": change.summary,
        "field_diffs": diffs,
        "snapshot_before": change.snapshot_before,
        "snapshot_after": change.snapshot_after,
        "recorded_at": (change.recorded_at.isoformat() if change.recorded_at else None),
    }


def _extract_conflicts(request: Request) -> list[dict[str, Any]]:
    """Retrieve raw conflicts from application state or relational database."""
    override = getattr(request.app.state, "conflicts_override", None)
    if override is not None:
        return [_convert_conflict_item(c) for c in override]

    engine: Engine | None = getattr(request.app.state, "db_engine", None)
    if engine is None:
        return []

    with get_sync_session(engine) as session:
        stmt = (
            select(GameChangeModel)
            .where(GameChangeModel.change_type.in_(["CONFLICT", "DISCREPANCY"]))
            .order_by(GameChangeModel.recorded_at.desc())
        )
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


def _build_conflicts_context(
    all_conflicts: list[dict[str, Any]],
    paginated_conflicts: list[dict[str, Any]],
    *,
    pagination: dict[str, Any],
    filters: dict[str, Any],
) -> dict[str, Any]:
    """Assemble complete Jinja2 template context for conflicts.html."""
    return {
        "active_tab": "conflicts",
        "conflicts": _enrich_conflict_items(paginated_conflicts),
        "pagination": pagination,
        "metrics": _count_conflict_metrics(all_conflicts),
        "filters": filters,
        "has_active_filters": _is_any_filter_active(filters),
    }


@conflicts_router.get(
    "",
    summary="List Schedule Conflicts and Discrepancies",
    description=(
        "Administrative endpoint listing multi-source schedule discrepancies with "
        "full field diff payloads. Requires administrator Bearer or API-key token."
    ),
    response_model=None,
    responses={
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
    },
)
def list_schedule_conflicts(
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
        limit: Max pagination count.
        offset: Pagination offset.

    Returns:
        Content-negotiated HTML triage dashboard or JSON response.
    """
    all_conflicts = _extract_conflicts(request)
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
    )

    return negotiate_response(
        request,
        payload,
        "conflicts.html",
        context=context,
    )


__all__ = [
    "ConflictDictConvertible",
    "list_schedule_conflicts",
]

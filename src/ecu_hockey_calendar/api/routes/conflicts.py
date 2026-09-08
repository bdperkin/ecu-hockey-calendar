"""Administrative conflict inspection and discrepancy review route handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Protocol, runtime_checkable

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from ecu_hockey_calendar.api.auth import verify_admin_token
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


def _change_model_to_conflict(change: GameChangeModel) -> dict[str, Any]:
    """Convert a GameChangeModel entity into an API conflict representation."""
    diffs = change.field_diffs or []
    first_field = diffs[0].get("field", "schedule") if diffs else "schedule"
    first_sev = diffs[0].get("severity", "medium") if diffs else "medium"

    return {
        "conflict_id": f"change-{change.id}",
        "game_id": change.canonical_game_id,
        "field": first_field,
        "severity": first_sev,
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


@conflicts_router.get(
    "",
    summary="List Schedule Conflicts and Discrepancies",
    description=(
        "Administrative endpoint listing multi-source schedule discrepancies with "
        "full field diff payloads. Requires administrator Bearer or API-key token."
    ),
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
) -> dict[str, Any]:
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
        Structured response with total count and matching conflict items.
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

    return {
        "total_conflicts": total_count,
        "filtered_count": len(paginated),
        "limit": limit,
        "offset": offset,
        "conflicts": paginated,
    }

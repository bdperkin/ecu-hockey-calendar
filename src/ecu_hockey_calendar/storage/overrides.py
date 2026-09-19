"""Administrative manual conflict resolution and schedule override service.

Provides capabilities to review, resolve, and override cross-source
schedule conflicts and discrepancies.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from sqlalchemy import Select, select

from ecu_hockey_calendar.storage.models import (
    ConflictOverrideModel,
    GameChangeModel,
    GameModel,
    GameStatus,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from ecu_hockey_calendar.reconciliation.models import ReconciledGame

CONFLICT_RESOLVED_CHANGE_TYPE = "CONFLICT_RESOLVED"


def _parse_iso_datetime(dt_str: object) -> datetime | None:
    """Parse ISO formatted timestamp into timezone-aware datetime."""
    if not isinstance(dt_str, str):
        return None

    try:
        dt = datetime.fromisoformat(dt_str)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _apply_game_times(game: GameModel, norm_field: str, value: str) -> None:
    """Apply start or end time override to GameModel."""
    if norm_field in ("start_time", "start"):
        parsed_dt = _parse_iso_datetime(value)
        if parsed_dt:
            game.start_time = parsed_dt
    elif norm_field in ("end_time", "end"):
        game.end_time = _parse_iso_datetime(value)


def _apply_game_scores(game: GameModel, norm_field: str, value: str) -> None:
    """Apply score overrides to GameModel."""
    with contextlib.suppress(ValueError, TypeError):
        int_val = int(value)
        if norm_field == "home_score":
            game.home_score = int_val
        elif norm_field == "away_score":
            game.away_score = int_val


def _apply_game_status_fields(game: GameModel, norm_field: str, value: str) -> None:
    """Apply status or result overrides to GameModel."""
    if norm_field == "status":
        game.status = value
    elif norm_field == "result":
        game.result = value


def _apply_field_to_game_model(
    game: GameModel,
    field_name: str,
    value: str,
) -> None:
    """Apply a single field override to a GameModel instance."""
    norm_field = field_name.strip().lower()
    if norm_field == "venue":
        game.venue = value

    _apply_game_times(game, norm_field, value)
    _apply_game_scores(game, norm_field, value)
    _apply_game_status_fields(game, norm_field, value)


def _maybe_update_game_model(
    session: Session,
    canonical_game_id: str,
    field_name: str,
    override_value: str,
) -> None:
    """Update stored GameModel entity if present in database."""
    stmt = select(GameModel).where(GameModel.game_id == canonical_game_id)
    game = session.scalars(stmt).first()
    if game:
        _apply_field_to_game_model(game, field_name, override_value)


def _deactivate_previous_overrides(
    session: Session,
    canonical_game_id: str,
    field_name: str,
) -> None:
    """Deactivate existing active overrides for the same game and field."""
    stmt = select(ConflictOverrideModel).where(
        ConflictOverrideModel.canonical_game_id == canonical_game_id,
        ConflictOverrideModel.field_name == field_name,
        ConflictOverrideModel.is_active.is_(True),
    )
    for existing in session.scalars(stmt).all():
        existing.is_active = False


def _create_resolution_change_record(
    canonical_game_id: str,
    field_name: str,
    override_value: str,
    resolved_by: str,
    notes: str | None,
) -> GameChangeModel:
    """Construct a GameChangeModel representing manual conflict resolution."""
    summary_text = f"Manual resolution: {field_name}={override_value} by {resolved_by}"
    diff = {
        "field_name": field_name,
        "new_value": override_value,
        "human_description": notes or "Manual override applied",
        "requires_review": False,
    }
    return GameChangeModel(
        sync_cycle_id="manual-resolution",
        canonical_game_id=canonical_game_id,
        change_type=CONFLICT_RESOLVED_CHANGE_TYPE,
        summary=summary_text[:512],
        field_diffs=[diff],
        snapshot_before=None,
        snapshot_after={field_name: override_value},
        recorded_at=datetime.now(UTC),
    )


def record_conflict_override(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    session: Session,
    *,
    conflict_id: str,
    canonical_game_id: str,
    field_name: str,
    override_value: str,
    accepted_source: str | None = None,
    resolved_by: str = "admin",
    notes: str | None = None,
) -> ConflictOverrideModel:
    """Persist manual conflict resolution and apply field override.

    Args:
        session: Active SQLAlchemy database session.
        conflict_id: Identifier of the resolved discrepancy.
        canonical_game_id: Target canonical fixture identifier.
        field_name: Overridden attribute name.
        override_value: Selected attribute value.
        accepted_source: Optional source whose data was accepted.
        resolved_by: Admin user identifier.
        notes: Optional resolution documentation.

    Returns:
        Created ConflictOverrideModel instance.
    """
    _deactivate_previous_overrides(session, canonical_game_id, field_name)
    override = ConflictOverrideModel(
        conflict_id=conflict_id,
        canonical_game_id=canonical_game_id,
        field_name=field_name,
        override_value=override_value,
        accepted_source=accepted_source,
        resolved_by=resolved_by,
        notes=notes,
        is_active=True,
    )
    session.add(override)
    _maybe_update_game_model(session, canonical_game_id, field_name, override_value)
    change_record = _create_resolution_change_record(
        canonical_game_id,
        field_name,
        override_value,
        resolved_by,
        notes,
    )
    session.add(change_record)
    session.flush()
    return override


def get_active_overrides(
    session: Session,
    canonical_game_id: str | None = None,
) -> list[ConflictOverrideModel]:
    """Query active conflict overrides from database.

    Args:
        session: Active SQLAlchemy session.
        canonical_game_id: Optional game ID filter.

    Returns:
        List of active ConflictOverrideModel entities.
    """
    stmt: Select[tuple[ConflictOverrideModel]] = select(
        ConflictOverrideModel,
    ).where(
        ConflictOverrideModel.is_active.is_(True),
    )
    if canonical_game_id:
        stmt = stmt.where(
            ConflictOverrideModel.canonical_game_id == canonical_game_id,
        )

    stmt = stmt.order_by(ConflictOverrideModel.created_at.desc())
    return list(session.scalars(stmt).all())


def _find_change_by_id_or_key(
    session: Session,
    conflict_id: str,
) -> GameChangeModel | None:
    """Find a GameChangeModel by numeric change id, prefix, or game key."""
    if conflict_id.startswith("change-"):
        raw_id = conflict_id.removeprefix("change-")
        if raw_id.isdigit():
            stmt = select(GameChangeModel).where(GameChangeModel.id == int(raw_id))
            return session.scalars(stmt).first()

    if conflict_id.isdigit():
        stmt = select(GameChangeModel).where(GameChangeModel.id == int(conflict_id))
        res = session.scalars(stmt).first()
        if res:
            return res

    stmt_key = (
        select(GameChangeModel)
        .where(GameChangeModel.canonical_game_id == conflict_id)
        .order_by(GameChangeModel.recorded_at.desc())
    )
    return session.scalars(stmt_key).first()


def _match_source_value_in_diff(
    diff: dict[str, Any],
    target: str,
) -> str | None:
    """Extract field value matching accepted source from a diff dict."""
    src_a = str(diff.get("source_a", "")).strip().lower()
    if src_a == target:
        return str(diff.get("value_a", ""))

    src_b = str(diff.get("source_b", "")).strip().lower()
    if src_b == target:
        return str(diff.get("value_b", ""))

    return None


def _diff_matches_field(diff: dict[str, Any], norm_field: str | None) -> bool:
    """Check whether diff matches expected field name."""
    if not norm_field:
        return True

    f_name = str(diff.get("field") or diff.get("field_name") or "").strip().lower()
    return f_name == norm_field


def _extract_source_value_from_diffs(
    diffs: list[dict[str, Any]],
    accept_source: str,
    target_field: str | None,
) -> str | None:
    """Find value associated with accepted source in diff list."""
    norm_field = target_field.strip().lower() if target_field else None
    target = accept_source.strip().lower()
    for diff in diffs:
        if _diff_matches_field(diff, norm_field):
            val = _match_source_value_in_diff(diff, target)
            if val is not None:
                return val

    return None


def _extract_snapshot_after_value(
    change: GameChangeModel,
    target_field: str | None,
) -> str | None:
    """Extract fallback value from snapshot_after."""
    if not target_field:
        return None

    after = change.snapshot_after or {}
    return str(after[target_field]) if target_field in after else None


def _extract_accepted_source_value(
    change: GameChangeModel | None,
    accept_source: str,
    target_field: str | None,
) -> str | None:
    """Determine proposed field value from an accepted source."""
    if not change:
        return None

    diffs = change.field_diffs or []
    val = _extract_source_value_from_diffs(diffs, accept_source, target_field)
    return (
        val if val is not None else _extract_snapshot_after_value(change, target_field)
    )


def _extract_field_from_change(change: GameChangeModel | None) -> str:
    """Derive primary conflicting field from change record."""
    if change and change.field_diffs:
        d0 = change.field_diffs[0]
        return str(d0.get("field") or d0.get("field_name") or "schedule")

    return "schedule"


def _resolve_game_and_field(
    change: GameChangeModel | None,
    conflict_id: str,
    explicit_field: str | None,
) -> tuple[str, str]:
    """Derive canonical game ID and conflicting field name."""
    game_id = change.canonical_game_id if change else conflict_id
    field_name = explicit_field or _extract_field_from_change(change)
    return game_id, field_name


def _resolve_final_value(
    override_value: str | None,
    change: GameChangeModel | None,
    accept_source: str | None,
    target_field: str,
) -> str | None:
    """Resolve the final override value from explicit string or accepted source."""
    if override_value is not None:
        return override_value

    if accept_source:
        return _extract_accepted_source_value(
            change,
            accept_source,
            target_field,
        )

    return None


def resolve_conflict(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    session: Session,
    conflict_id: str,
    *,
    field_name: str | None = None,
    override_value: str | None = None,
    accept_source: str | None = None,
    resolved_by: str = "admin",
    notes: str | None = None,
) -> dict[str, Any]:
    """Resolve a conflict by applying an explicit value or accepting a source.

    Args:
        session: Active SQLAlchemy session.
        conflict_id: ID of conflict or canonical game ID.
        field_name: Target attribute name.
        override_value: Explicit override value.
        accept_source: Source name whose proposed value should be accepted.
        resolved_by: Admin user identifier.
        notes: Optional resolution documentation.

    Returns:
        Dictionary summarizing the resolution result.

    Raises:
        ValueError: If conflict is missing or resolution values are ambiguous.
    """
    change = _find_change_by_id_or_key(session, conflict_id)
    if not change:
        err_msg = f"Conflict '{conflict_id}' not found."
        raise ValueError(err_msg)

    canonical_id, target_field = _resolve_game_and_field(
        change,
        conflict_id,
        field_name,
    )
    final_value = _resolve_final_value(
        override_value,
        change,
        accept_source,
        target_field,
    )
    if final_value is None:
        msg = (
            f"Unable to resolve conflict '{conflict_id}': "
            "Neither explicit value nor accepted source value found."
        )
        raise ValueError(msg)

    override = record_conflict_override(
        session,
        conflict_id=conflict_id,
        canonical_game_id=canonical_id,
        field_name=target_field,
        override_value=str(final_value),
        accepted_source=accept_source,
        resolved_by=resolved_by,
        notes=notes,
    )

    return {
        "status": "resolved",
        "conflict_id": conflict_id,
        "canonical_game_id": canonical_id,
        "game_id": canonical_id,
        "field": target_field,
        "value": str(final_value),
        "accepted_source": accept_source,
        "resolved_by": resolved_by,
        "notes": notes,
        "override_id": override.id,
    }


def _normalize_overrides_dict(loaded: object) -> list[dict[str, Any]]:
    """Extract list of dicts from parsed YAML or JSON structure."""
    items = loaded.get("overrides", []) if isinstance(loaded, dict) else loaded
    if isinstance(items, list):
        return [dict(x) for x in items if isinstance(x, dict)]

    return []


def _parse_overrides_payload(
    raw_text: str,
    *,
    is_json: bool,
) -> list[dict[str, Any]]:
    """Parse raw JSON or YAML text into override records list."""
    loaded = json.loads(raw_text) if is_json else yaml.safe_load(raw_text)
    return _normalize_overrides_dict(loaded)


def load_overrides_from_file(file_path: Path | str) -> list[dict[str, Any]]:
    """Load manual overrides configuration from a YAML or JSON file.

    Args:
        file_path: Filesystem path to YAML or JSON config.

    Returns:
        List of parsed override configuration dictionaries.
    """
    path = Path(file_path)
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8")
    return _parse_overrides_payload(
        content,
        is_json=(path.suffix.lower() == ".json"),
    )


def _get_first_str_key(d: dict[str, Any], key1: str, key2: str) -> str:
    """Retrieve first non-empty string value among two keys."""
    val = d.get(key1)
    if val:
        return str(val)

    return str(d.get(key2, ""))


def _get_first_val_key(d: dict[str, Any], key1: str, key2: str) -> str | None:
    """Retrieve first non-None value among two keys."""
    val = d.get(key1)
    if val is not None:
        return str(val)

    fallback = d.get(key2)
    return str(fallback) if fallback is not None else None


def _is_valid_override_keys(game_id: str, field: str, val: str | None) -> bool:
    """Validate presence of required override attributes."""
    return bool(game_id and field and val is not None)


def _apply_file_override_entry(session: Session, ov: dict[str, Any]) -> bool:
    """Validate and record a single file override entry."""
    game_id = _get_first_str_key(ov, "game_id", "canonical_game_id")
    field = _get_first_str_key(ov, "field", "field_name")
    val = _get_first_val_key(ov, "value", "override_value")
    if not _is_valid_override_keys(game_id, field, val):
        return False

    record_conflict_override(
        session,
        conflict_id=str(ov.get("conflict_id") or game_id),
        canonical_game_id=game_id,
        field_name=field,
        override_value=str(val),
        accepted_source=ov.get("accepted_source"),
        resolved_by=str(ov.get("resolved_by") or "config-file"),
        notes=ov.get("notes"),
    )
    return True


def apply_overrides_from_file(
    session: Session,
    file_path: Path | str,
) -> int:
    """Load and persist manual overrides from a configuration file.

    Args:
        session: Active SQLAlchemy session.
        file_path: Path to YAML or JSON configuration file.

    Returns:
        Count of successfully applied overrides.
    """
    overrides = load_overrides_from_file(file_path)
    count = 0
    for ov in overrides:
        if _apply_file_override_entry(session, ov):
            count += 1

    return count


def _apply_reconciled_scores(rg: ReconciledGame, fname: str, val: str) -> None:
    """Apply score overrides to ReconciledGame."""
    with contextlib.suppress(ValueError, TypeError):
        if fname == "home_score":
            rg.home_score = int(val)
        elif fname == "away_score":
            rg.away_score = int(val)


def _apply_reconciled_timing(rg: ReconciledGame, fname: str, val: str) -> None:
    """Apply timing overrides to ReconciledGame."""
    if fname in ("start_time", "start"):
        parsed_dt = _parse_iso_datetime(val)
        if parsed_dt:
            rg.start_time = parsed_dt


def _apply_reconciled_status(rg: ReconciledGame, fname: str, val: str) -> None:
    """Apply status overrides to ReconciledGame."""
    if fname == "status":
        with contextlib.suppress(ValueError):
            rg.status = GameStatus(val)


def _filter_matching_conflicts(
    rg: ReconciledGame,
    fname: str,
    val: str,
    accepted_source: str | None,
) -> None:
    """Filter or mark resolved conflicts on ReconciledGame matching field."""
    for conf in rg.conflicts:
        c_val = getattr(conf.field, "value", str(conf.field)).lower()
        if c_val == fname:
            conf.resolved = True
            conf.resolved_value = val
            conf.resolved_by_source = accepted_source or "manual"
            conf.requires_review = False


def _apply_single_override_to_reconciled(
    rg: ReconciledGame,
    override: ConflictOverrideModel,
) -> None:
    """Apply an active override model onto a domain ReconciledGame instance."""
    fname = override.field_name.strip().lower()
    val = override.override_value
    if fname == "venue":
        rg.venue = val

    _apply_reconciled_timing(rg, fname, val)
    _apply_reconciled_status(rg, fname, val)
    _apply_reconciled_scores(rg, fname, val)
    user_id = override.resolved_by or "admin"
    rg.field_provenance[fname] = f"manual-override:{user_id}"
    _filter_matching_conflicts(rg, fname, val, override.accepted_source)


def _group_overrides_by_game(
    overrides: Sequence[ConflictOverrideModel],
) -> dict[str, list[ConflictOverrideModel]]:
    """Index overrides by canonical_game_id."""
    game_map: dict[str, list[ConflictOverrideModel]] = {}
    for ov in overrides:
        game_map.setdefault(ov.canonical_game_id, []).append(ov)

    return game_map


def _apply_overrides_to_single_reconciled(
    rg: ReconciledGame,
    game_overrides: list[ConflictOverrideModel] | None,
) -> None:
    """Apply a list of overrides to one reconciled game."""
    if not game_overrides:
        return

    for ov in game_overrides:
        _apply_single_override_to_reconciled(rg, ov)


def apply_overrides_to_reconciled_games(
    reconciled_games: Sequence[ReconciledGame],
    overrides: Sequence[ConflictOverrideModel],
) -> None:
    """Apply active manual overrides across reconciled games.

    Args:
        reconciled_games: List of ReconciledGame entities.
        overrides: List of active ConflictOverrideModel records.
    """
    if not overrides or not reconciled_games:
        return

    game_map = _group_overrides_by_game(overrides)
    for rg in reconciled_games:
        _apply_overrides_to_single_reconciled(
            rg,
            game_map.get(rg.canonical_game_id),
        )


__all__ = [
    "CONFLICT_RESOLVED_CHANGE_TYPE",
    "apply_overrides_from_file",
    "apply_overrides_to_reconciled_games",
    "get_active_overrides",
    "load_overrides_from_file",
    "record_conflict_override",
    "resolve_conflict",
]

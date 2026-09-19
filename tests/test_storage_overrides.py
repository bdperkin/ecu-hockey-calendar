"""Tests for manual conflict resolution storage models, service, and helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from ecu_hockey_calendar.reconciliation.models import (
    ConflictField,
    ConflictSeverity,
    DetectedConflict,
    ReconciledGame,
)
from ecu_hockey_calendar.storage import (
    CONFLICT_RESOLVED_CHANGE_TYPE,
    ConflictOverrideModel,
    GameChangeModel,
    GameModel,
    GameStatus,
    TeamModel,
    apply_overrides_from_file,
    apply_overrides_to_reconciled_games,
    create_sync_engine,
    get_active_overrides,
    get_sync_session,
    init_db,
    load_overrides_from_file,
    record_conflict_override,
    resolve_conflict,
)
from ecu_hockey_calendar.storage.overrides import (
    _apply_field_to_game_model,
    _diff_matches_field,
    _extract_accepted_source_value,
    _extract_snapshot_after_value,
    _extract_source_value_from_diffs,
    _find_change_by_id_or_key,
    _get_first_val_key,
    _parse_iso_datetime,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session


@pytest.fixture
def db_session(tmp_path: Path):
    """Provide clean database session with initialized schema."""
    db_file = tmp_path / "test_overrides.db"
    engine = create_sync_engine(f"sqlite:///{db_file}")
    init_db(engine)
    with get_sync_session(engine) as session:
        home = TeamModel(name="East Carolina University", city="Greenville", state="NC")
        away = TeamModel(name="UNC Chapel Hill", city="Chapel Hill", state="NC")
        session.add_all([home, away])
        session.commit()
        yield session


def _create_sample_game(
    session: Session,
    game_id: str = "ecu-unc-20241011",
) -> GameModel:
    """Create and persist a test GameModel instance."""
    stmt_home = select(TeamModel).where(TeamModel.name == "East Carolina University")
    stmt_away = select(TeamModel).where(TeamModel.name == "UNC Chapel Hill")
    home = session.scalars(stmt_home).first()
    away = session.scalars(stmt_away).first()
    game = GameModel(
        game_id=game_id,
        home_team_id=home.id if home else 1,
        away_team_id=away.id if away else 2,
        start_time=datetime(2024, 10, 11, 19, 0, tzinfo=UTC),
        venue="Original Arena",
        status=GameStatus.SCHEDULED.value,
    )
    session.add(game)
    session.commit()
    return game


def _create_sample_change(
    session: Session,
    *,
    game_id: str = "ecu-unc-20241011",
    field: str = "venue",
    source_a: str = "ecuhockey",
    val_a: str = "The Triangle Rink",
    source_b: str = "achahockey",
    val_b: str = "Carolina Ice Palace",
) -> GameChangeModel:
    """Create and persist a test GameChangeModel representing a conflict."""
    change = GameChangeModel(
        sync_cycle_id="cycle-1",
        canonical_game_id=game_id,
        change_type="CONFLICT_DETECTED",
        summary=f"Venue conflict: '{val_a}' vs '{val_b}'",
        field_diffs=[
            {
                "field": field,
                "source_a": source_a,
                "value_a": val_a,
                "source_b": source_b,
                "value_b": val_b,
                "requires_review": True,
            },
        ],
        snapshot_after={field: val_a},
        recorded_at=datetime.now(UTC),
    )
    session.add(change)
    session.commit()
    return change


# ---------------------------------------------------------------------------
# 1. record_conflict_override and get_active_overrides Tests
# ---------------------------------------------------------------------------


def test_record_conflict_override_and_query(db_session: Session) -> None:
    """Verify record_conflict_override persists and updates GameModel."""
    _create_sample_game(db_session, "ecu-unc-20241011")
    override = record_conflict_override(
        db_session,
        conflict_id="change-1",
        canonical_game_id="ecu-unc-20241011",
        field_name="venue",
        override_value="Carolina Ice Palace",
        accepted_source="achahockey",
        resolved_by="lead_admin",
        notes="Confirmed by rink manager",
    )
    db_session.commit()

    assert override.id is not None
    assert override.canonical_game_id == "ecu-unc-20241011"
    assert override.field_name == "venue"
    assert override.override_value == "Carolina Ice Palace"
    assert override.accepted_source == "achahockey"
    assert override.resolved_by == "lead_admin"
    assert override.notes == "Confirmed by rink manager"
    assert override.is_active is True

    # Check that game entity in DB was updated
    game = db_session.scalars(
        select(GameModel).where(GameModel.game_id == "ecu-unc-20241011"),
    ).first()
    assert game is not None
    assert game.venue == "Carolina Ice Palace"

    # Query active overrides
    active = get_active_overrides(db_session, "ecu-unc-20241011")
    assert len(active) == 1
    assert active[0].id == override.id

    # Query active overrides without filter
    all_active = get_active_overrides(db_session)
    assert len(all_active) == 1


def test_record_override_deactivates_previous(db_session: Session) -> None:
    """Verify recording new override deactivates prior overrides for same field."""
    ov1 = record_conflict_override(
        db_session,
        conflict_id="change-1",
        canonical_game_id="ecu-unc-20241011",
        field_name="venue",
        override_value="Venue A",
    )
    db_session.commit()
    assert ov1.is_active is True

    ov2 = record_conflict_override(
        db_session,
        conflict_id="change-2",
        canonical_game_id="ecu-unc-20241011",
        field_name="venue",
        override_value="Venue B",
    )
    db_session.commit()
    assert ov2.is_active is True

    # Check ov1 is now inactive
    db_session.refresh(ov1)
    assert ov1.is_active is False

    active = get_active_overrides(db_session, "ecu-unc-20241011")
    assert len(active) == 1
    assert active[0].override_value == "Venue B"


# ---------------------------------------------------------------------------
# 2. _apply_field_to_game_model Attribute Updaters
# ---------------------------------------------------------------------------


def test_apply_field_to_game_model_all_attributes(db_session: Session) -> None:
    """Verify _apply_field_to_game_model covers times, scores, and status flags."""
    game = _create_sample_game(db_session, "ecu-unc-20241011")

    # Start time with ISO string
    _apply_field_to_game_model(game, "start_time", "2024-10-11T20:30:00+00:00")
    assert game.start_time == datetime(2024, 10, 11, 20, 30, tzinfo=UTC)

    # Scores
    _apply_field_to_game_model(game, "home_score", "5")
    _apply_field_to_game_model(game, "away_score", "3")
    assert game.home_score == 5
    assert game.away_score == 3

    # Status and result
    _apply_field_to_game_model(game, "status", "FINAL")
    _apply_field_to_game_model(game, "result", "WIN")
    assert game.status == "FINAL"
    assert game.result == "WIN"


# ---------------------------------------------------------------------------
# 3. resolve_conflict Service Tests
# ---------------------------------------------------------------------------


def test_resolve_conflict_by_change_prefix(db_session: Session) -> None:
    """Verify resolving conflict by 'change-<id>' using explicit override value."""
    change = _create_sample_change(db_session)
    result = resolve_conflict(
        db_session,
        f"change-{change.id}",
        field_name="venue",
        override_value="Carolina Ice Palace",
        resolved_by="admin_user",
        notes="Manual venue selection",
    )
    assert result["status"] == "resolved"
    assert result["conflict_id"] == f"change-{change.id}"
    assert result["game_id"] == "ecu-unc-20241011"
    assert result["field"] == "venue"
    assert result["value"] == "Carolina Ice Palace"
    assert result["resolved_by"] == "admin_user"
    assert result["notes"] == "Manual venue selection"

    # Verify resolution change was added
    res_change = db_session.scalars(
        select(GameChangeModel).where(
            GameChangeModel.change_type == CONFLICT_RESOLVED_CHANGE_TYPE,
        ),
    ).first()
    assert res_change is not None
    assert "Manual resolution" in res_change.summary


def test_resolve_conflict_by_numeric_id_and_accept_source(db_session: Session) -> None:
    """Verify resolving conflict by numeric id using accept_source."""
    change = _create_sample_change(db_session)
    result = resolve_conflict(
        db_session,
        str(change.id),
        accept_source="achahockey",
    )
    assert result["status"] == "resolved"
    assert result["value"] == "Carolina Ice Palace"
    assert result["accepted_source"] == "achahockey"


def test_resolve_conflict_by_canonical_game_id(db_session: Session) -> None:
    """Verify resolving conflict by canonical game ID."""
    _create_sample_change(db_session, game_id="ecu-unc-20241011")
    result = resolve_conflict(
        db_session,
        "ecu-unc-20241011",
        accept_source="ecuhockey",
    )
    assert result["status"] == "resolved"
    assert result["value"] == "The Triangle Rink"


def test_resolve_conflict_accept_source_fallback_snapshot(db_session: Session) -> None:
    """Verify accept_source falls back to snapshot when source not in diffs."""
    change = GameChangeModel(
        sync_cycle_id="cycle-1",
        canonical_game_id="ecu-unc-20241011",
        change_type="CONFLICT_DETECTED",
        summary="Timing dispute",
        field_diffs=[
            {
                "field": "venue",
                "source_a": "other_src",
                "value_a": "Some Rink",
            },
        ],
        snapshot_after={"venue": "Fallback Arena"},
        recorded_at=datetime.now(UTC),
    )
    db_session.add(change)
    db_session.commit()

    result = resolve_conflict(
        db_session,
        f"change-{change.id}",
        accept_source="unmatched_source",
    )
    assert result["value"] == "Fallback Arena"


def test_resolve_conflict_not_found(db_session: Session) -> None:
    """Verify resolve_conflict raises ValueError if change record cannot be found."""
    with pytest.raises(ValueError, match=r"Conflict 'change-9999' not found\."):
        resolve_conflict(db_session, "change-9999", override_value="Value")


def test_resolve_conflict_missing_value_and_source(db_session: Session) -> None:
    """Verify resolve_conflict raises ValueError when no value or source given."""
    change = _create_sample_change(db_session)
    with pytest.raises(ValueError, match="Neither explicit value nor accepted"):
        resolve_conflict(db_session, str(change.id))


def test_resolve_conflict_unresolvable_source(db_session: Session) -> None:
    """Verify resolve_conflict raises ValueError when source is unresolvable."""
    change = GameChangeModel(
        sync_cycle_id="cycle-1",
        canonical_game_id="ecu-unc-20241011",
        change_type="CONFLICT_DETECTED",
        summary="Empty diff conflict",
        field_diffs=[],
        snapshot_after={},
        recorded_at=datetime.now(UTC),
    )
    db_session.add(change)
    db_session.commit()

    with pytest.raises(ValueError, match="Neither explicit value nor accepted"):
        resolve_conflict(db_session, str(change.id), accept_source="unknown_src")


# ---------------------------------------------------------------------------
# 4. File-Based Overrides Configuration (YAML / JSON) Tests
# ---------------------------------------------------------------------------


def test_load_overrides_from_yaml(tmp_path: Path) -> None:
    """Verify load_overrides_from_file correctly parses valid YAML configuration."""
    yaml_file = tmp_path / "overrides.yaml"
    yaml_content = (
        "overrides:\n"
        "  - conflict_id: conf-1\n"
        "    game_id: ecu-unc-20241011\n"
        "    field: venue\n"
        "    value: Carolina Ice Palace\n"
        "    accepted_source: achahockey\n"
        "    resolved_by: admin\n"
        "    notes: Confirmed venue\n"
    )
    yaml_file.write_text(yaml_content, encoding="utf-8")
    loaded = load_overrides_from_file(yaml_file)
    assert len(loaded) == 1
    assert loaded[0]["game_id"] == "ecu-unc-20241011"
    assert loaded[0]["field"] == "venue"
    assert loaded[0]["value"] == "Carolina Ice Palace"


def test_load_overrides_from_json(tmp_path: Path) -> None:
    """Verify load_overrides_from_file correctly parses valid JSON configuration."""
    json_file = tmp_path / "overrides.json"
    data = [
        {
            "conflict_id": "conf-2",
            "game_id": "ecu-unc-20241011",
            "field": "start_time",
            "value": "2024-10-11T20:00:00Z",
            "notes": "Puck drop moved to 8pm",
        },
    ]
    json_file.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_overrides_from_file(json_file)
    assert len(loaded) == 1
    assert loaded[0]["field"] == "start_time"


def test_load_overrides_file_not_found(tmp_path: Path) -> None:
    """Verify load_overrides_from_file returns empty list for missing paths."""
    assert load_overrides_from_file(tmp_path / "missing.yaml") == []


def test_load_overrides_empty_file(tmp_path: Path) -> None:
    """Verify load_overrides_from_file returns empty list for empty file."""
    empty_file = tmp_path / "empty.yaml"
    empty_file.write_text("", encoding="utf-8")
    assert load_overrides_from_file(empty_file) == []


def test_load_overrides_invalid_schema(tmp_path: Path) -> None:
    """Verify load_overrides_from_file returns empty list when malformed."""
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("overrides: not-a-list\n", encoding="utf-8")
    assert load_overrides_from_file(bad_file) == []

    bad_entry = tmp_path / "bad_entry.yaml"
    bad_entry.write_text("- not-a-dict\n", encoding="utf-8")
    assert load_overrides_from_file(bad_entry) == []


def test_apply_overrides_from_file(db_session: Session, tmp_path: Path) -> None:
    """Verify apply_overrides_from_file persists all entries into database."""
    config_file = tmp_path / "overrides.yaml"
    config_content = (
        "- game_id: ecu-unc-20241011\n"
        "  field: venue\n"
        "  value: File Venue\n"
        "  notes: From config file\n"
        '- game_id: ""\n'
        "  field: venue\n"
        "  value: Invalid\n"
    )
    config_file.write_text(config_content, encoding="utf-8")
    applied_count = apply_overrides_from_file(db_session, config_file)
    assert applied_count == 1

    active = get_active_overrides(db_session, "ecu-unc-20241011")
    assert len(active) == 1
    assert active[0].override_value == "File Venue"


# ---------------------------------------------------------------------------
# 5. apply_overrides_to_reconciled_games Tests
# ---------------------------------------------------------------------------


def test_apply_overrides_to_reconciled_games() -> None:
    """Verify active overrides are correctly applied to ReconciledGame models."""
    game = ReconciledGame(
        canonical_game_id="ecu-unc-20241011",
        opponent_name="UNC",
        start_time=datetime(2024, 10, 11, 19, 0, tzinfo=UTC),
        venue="Old Arena",
        conflicts=[
            DetectedConflict(
                conflict_id="conf-1",
                game_key="ecu-unc-20241011",
                field=ConflictField.VENUE,
                severity=ConflictSeverity.MEDIUM,
                requires_review=True,
            ),
        ],
    )

    override = ConflictOverrideModel(
        conflict_id="conf-1",
        canonical_game_id="ecu-unc-20241011",
        field_name="venue",
        override_value="Override Arena",
        is_active=True,
    )

    apply_overrides_to_reconciled_games([game], [override])
    assert game.venue == "Override Arena"
    assert game.conflicts[0].resolved is True
    assert game.conflicts[0].resolved_value == "Override Arena"
    assert game.field_provenance["venue"] == "manual-override:admin"


def test_apply_overrides_start_time_and_scores() -> None:
    """Verify applying start_time and score overrides to ReconciledGame."""
    game = ReconciledGame(
        canonical_game_id="ecu-unc-20241011",
        opponent_name="UNC",
        start_time=datetime(2024, 10, 11, 19, 0, tzinfo=UTC),
        venue="Arena",
    )
    overrides = [
        ConflictOverrideModel(
            conflict_id="conf-1",
            canonical_game_id="ecu-unc-20241011",
            field_name="start_time",
            override_value="2024-10-11T20:00:00+00:00",
            is_active=True,
        ),
        ConflictOverrideModel(
            conflict_id="conf-2",
            canonical_game_id="ecu-unc-20241011",
            field_name="home_score",
            override_value="4",
            is_active=True,
        ),
        ConflictOverrideModel(
            conflict_id="conf-3",
            canonical_game_id="ecu-unc-20241011",
            field_name="away_score",
            override_value="2",
            is_active=True,
        ),
        ConflictOverrideModel(
            conflict_id="conf-4",
            canonical_game_id="ecu-unc-20241011",
            field_name="status",
            override_value="FINAL",
            is_active=True,
        ),
    ]

    apply_overrides_to_reconciled_games([game], overrides)
    assert game.start_time == datetime(2024, 10, 11, 20, 0, tzinfo=UTC)
    assert game.home_score == 4
    assert game.away_score == 2
    assert game.status == GameStatus.FINAL


def test_parse_iso_datetime_invalid() -> None:
    """Verify _parse_iso_datetime handles invalid strings and types gracefully."""
    assert _parse_iso_datetime("invalid-iso-string") is None
    assert _parse_iso_datetime(12345) is None


def test_apply_field_to_game_model_edge_cases(db_session: Session) -> None:
    """Verify _apply_field_to_game_model handles invalid dates and non-score ints."""
    game = _create_sample_game(db_session, "ecu-unc-20241011")
    original_start = game.start_time

    # Invalid start time leaves start_time unchanged
    _apply_field_to_game_model(game, "start_time", "invalid-date")
    assert game.start_time == original_start

    # Valid end time updates end_time
    _apply_field_to_game_model(game, "end_time", "2024-10-11T22:00:00+00:00")
    assert game.end_time == datetime(2024, 10, 11, 22, 0, tzinfo=UTC)

    # Integer value for non-score field executes _apply_game_scores with
    # non-matching field
    _apply_field_to_game_model(game, "venue", "100")
    assert game.venue == "100"
    assert game.home_score is None


def test_find_change_by_id_or_key_edge_cases(db_session: Session) -> None:
    """Verify _find_change_by_id_or_key handles non-digit prefix and bad id."""
    change = _create_sample_change(db_session, game_id="ecu-unc-key-lookup")

    # Prefix with non-digit falls through to canonical_game_id query
    res_prefix = _find_change_by_id_or_key(db_session, "change-notdigit")
    assert res_prefix is None

    # Prefix matching canonical_game_id
    res_key = _find_change_by_id_or_key(db_session, "ecu-unc-key-lookup")
    assert res_key is not None
    assert res_key.id == change.id

    # Digit id that does not exist falls through to canonical_game_id query
    res_missing_digit = _find_change_by_id_or_key(db_session, "999999")
    assert res_missing_digit is None


def test_diff_matching_and_extraction_helpers(db_session: Session) -> None:
    """Verify diff matching when norm_field is None and skipping non-matching."""
    assert _diff_matches_field({"field": "venue"}, None) is True

    diffs = [
        {
            "field": "start_time",
            "source_a": "src1",
            "value_a": "19:00",
            "source_b": "src2",
            "value_b": "20:00",
        },
        {
            "field": "venue",
            "source_a": "src1",
            "value_a": "Target Venue",
            "source_b": "src2",
            "value_b": "Other Venue",
        },
    ]
    # First diff is skipped because field is start_time, second matches venue
    extracted = _extract_source_value_from_diffs(diffs, "src1", "venue")
    assert extracted == "Target Venue"

    change = _create_sample_change(db_session)
    assert _extract_snapshot_after_value(change, None) is None
    assert _extract_accepted_source_value(None, "src1", "venue") is None


def test_get_first_val_key_helper() -> None:
    """Verify _get_first_val_key retrieves fallback when key is missing."""
    assert _get_first_val_key({"val1": "first"}, "val1", "val2") == "first"
    assert _get_first_val_key({"val2": "second"}, "val1", "val2") == "second"
    assert _get_first_val_key({}, "val1", "val2") is None


def test_apply_overrides_to_reconciled_games_branches() -> None:
    """Verify early exit, unmapped game, invalid time, and unmatched filtering."""
    game = ReconciledGame(
        canonical_game_id="ecu-unc-20241011",
        opponent_name="UNC",
        start_time=datetime(2024, 10, 11, 19, 0, tzinfo=UTC),
        venue="Original Rink",
        conflicts=[
            DetectedConflict(
                conflict_id="c-venue",
                game_key="ecu-unc-20241011",
                field=ConflictField.VENUE,
                severity=ConflictSeverity.MEDIUM,
            ),
            DetectedConflict(
                conflict_id="c-time",
                game_key="ecu-unc-20241011",
                field=ConflictField.START_TIME,
                severity=ConflictSeverity.HIGH,
            ),
        ],
    )

    # Empty inputs exit early
    apply_overrides_to_reconciled_games([], [])
    apply_overrides_to_reconciled_games([game], [])

    # Override for different game leaves target game untouched
    unrelated_override = ConflictOverrideModel(
        conflict_id="other-1",
        canonical_game_id="other-game-id",
        field_name="venue",
        override_value="Other Arena",
        is_active=True,
    )
    apply_overrides_to_reconciled_games([game], [unrelated_override])
    assert game.venue == "Original Rink"

    # Invalid datetime does not update start_time
    bad_time_override = ConflictOverrideModel(
        conflict_id="c-bad-time",
        canonical_game_id="ecu-unc-20241011",
        field_name="start_time",
        override_value="not-a-datetime",
        is_active=True,
    )
    apply_overrides_to_reconciled_games([game], [bad_time_override])
    assert game.start_time == datetime(2024, 10, 11, 19, 0, tzinfo=UTC)

    # Override venue on fresh game marks venue conflict resolved but skips
    # start_time conflict
    game2 = ReconciledGame(
        canonical_game_id="ecu-unc-20241011",
        opponent_name="UNC",
        start_time=datetime(2024, 10, 11, 19, 0, tzinfo=UTC),
        venue="Original Rink",
        conflicts=[
            DetectedConflict(
                conflict_id="c-venue",
                game_key="ecu-unc-20241011",
                field=ConflictField.VENUE,
                severity=ConflictSeverity.MEDIUM,
            ),
            DetectedConflict(
                conflict_id="c-time",
                game_key="ecu-unc-20241011",
                field=ConflictField.START_TIME,
                severity=ConflictSeverity.HIGH,
            ),
        ],
    )
    venue_override = ConflictOverrideModel(
        conflict_id="c-venue",
        canonical_game_id="ecu-unc-20241011",
        field_name="venue",
        override_value="New Rink",
        is_active=True,
    )
    apply_overrides_to_reconciled_games([game2], [venue_override])
    assert game2.venue == "New Rink"
    assert game2.conflicts[0].resolved is True
    assert game2.conflicts[1].resolved is False


def test_conflict_override_model_to_dict() -> None:
    """Verify ConflictOverrideModel.to_dict serialization."""
    now = datetime(2024, 10, 11, 12, 0, tzinfo=UTC)
    model = ConflictOverrideModel(
        id=1,
        conflict_id="conf-1",
        canonical_game_id="ecu-unc-20241011",
        field_name="venue",
        override_value="New Rink",
        accepted_source=None,
        resolved_by="admin",
        notes="Admin override",
        is_active=True,
        created_at=now,
    )
    data = model.to_dict()
    assert data["id"] == 1
    assert data["conflict_id"] == "conf-1"
    assert data["canonical_game_id"] == "ecu-unc-20241011"
    assert data["field_name"] == "venue"
    assert data["override_value"] == "New Rink"
    assert data["accepted_source"] is None
    assert data["resolved_by"] == "admin"
    assert data["notes"] == "Admin override"
    assert data["is_active"] is True
    assert data["created_at"] == now.isoformat()

    model_no_dt = ConflictOverrideModel(
        id=2,
        conflict_id="conf-2",
        canonical_game_id="ecu-unc-20241011",
        field_name="venue",
        override_value="New Rink",
        created_at=None,
    )
    assert model_no_dt.to_dict()["created_at"] is None

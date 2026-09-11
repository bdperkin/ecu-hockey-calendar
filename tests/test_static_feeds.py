"""Unit tests for static feed validation tool (RFC 5545, RFC 4180, and JSON)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from tools.validate_feeds import (
    EXPECTED_CSV_COLUMNS,
    main,
    validate_all_feeds,
    validate_csv_feed,
    validate_ics_feed,
    validate_json_feed,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "static"


# -----------------------------------------------------------------------------
# Existing static feed sanity checks
# -----------------------------------------------------------------------------


def test_validate_real_static_feeds() -> None:
    """Verify that the repository's static/ directory passes all checks cleanly."""
    errors = validate_all_feeds(STATIC_DIR)
    assert not errors, f"Static feed validation errors: {errors}"


def test_validate_real_static_ics() -> None:
    """Verify that calendar.ics passes validation and extracts game IDs."""
    errors, ids = validate_ics_feed(STATIC_DIR / "calendar.ics")
    assert not errors
    assert len(ids) > 0


def test_validate_real_static_csv() -> None:
    """Verify that schedule.csv passes validation and extracts game IDs."""
    errors, ids = validate_csv_feed(STATIC_DIR / "schedule.csv")
    assert not errors
    assert len(ids) > 0


def test_validate_real_static_json() -> None:
    """Verify that schedule.json passes validation and extracts game IDs."""
    errors, ids = validate_json_feed(STATIC_DIR / "schedule.json")
    assert not errors
    assert len(ids) > 0


# -----------------------------------------------------------------------------
# ICS Validation Unit Tests (RFC 5545)
# -----------------------------------------------------------------------------


def test_ics_file_not_found(tmp_path: Path) -> None:
    """Verify error when ICS file does not exist."""
    errors, ids = validate_ics_feed(tmp_path / "missing.ics")
    assert any("not found" in e.lower() for e in errors)
    assert not ids


def test_ics_read_error(tmp_path: Path) -> None:
    """Verify error handling when reading ICS file raises OSError."""
    ics_file = tmp_path / "test.ics"
    ics_file.write_text("dummy", encoding="utf-8")
    with patch.object(Path, "read_bytes", side_effect=OSError("Read failure")):
        errors, ids = validate_ics_feed(ics_file)

    assert any("failed to read" in e.lower() for e in errors)
    assert not ids


def test_ics_empty_file(tmp_path: Path) -> None:
    """Verify error when ICS file is empty."""
    ics_file = tmp_path / "empty.ics"
    ics_file.write_bytes(b"")
    errors, ids = validate_ics_feed(ics_file)
    assert any("empty" in e.lower() for e in errors)
    assert not ids


def test_ics_non_crlf_endings(tmp_path: Path) -> None:
    """Verify error when ICS file uses LF instead of CRLF."""
    ics_file = tmp_path / "lf.ics"
    ics_file.write_bytes(b"BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n")
    errors, _ = validate_ics_feed(ics_file)
    assert any("non-crlf" in e.lower() for e in errors)


def test_ics_line_length_exceeded(tmp_path: Path) -> None:
    """Verify error when an unfolded ICS line exceeds 75 octets."""
    long_line = b"DESCRIPTION:" + b"A" * 70  # 82 octets > 75
    content = (
        b"BEGIN:VCALENDAR\r\n"
        b"VERSION:2.0\r\n"
        b"PRODID:-//Test//EN\r\n" + long_line + b"\r\n"
        b"END:VCALENDAR\r\n"
    )
    ics_file = tmp_path / "long_line.ics"
    ics_file.write_bytes(content)
    errors, _ = validate_ics_feed(ics_file)
    assert any("exceeds 75 octets" in e for e in errors)


def test_ics_invalid_utf8(tmp_path: Path) -> None:
    """Verify error when ICS file contains invalid UTF-8 bytes."""
    ics_file = tmp_path / "invalid_utf8.ics"
    ics_file.write_bytes(b"BEGIN:VCALENDAR\r\n\xff\xfe\r\nEND:VCALENDAR\r\n")
    errors, ids = validate_ics_feed(ics_file)
    assert any("not valid utf-8" in e.lower() for e in errors)
    assert not ids


def test_ics_missing_headers_and_events(tmp_path: Path) -> None:
    """Verify errors when mandatory headers or events are missing."""
    content = b"X-SOMETHING:foo\r\nX-OTHER:bar\r\n"
    ics_file = tmp_path / "bad_headers.ics"
    ics_file.write_bytes(content)
    errors, _ = validate_ics_feed(ics_file)
    assert any("must begin with BEGIN:VCALENDAR" in e for e in errors)
    assert any("must end with END:VCALENDAR" in e for e in errors)
    assert any("missing mandatory VERSION:2.0" in e for e in errors)
    assert any("missing mandatory PRODID" in e for e in errors)
    assert any("contains no VEVENT components" in e for e in errors)


def test_ics_event_property_errors(tmp_path: Path) -> None:
    """Verify event property validation (UID, DTSTAMP, DTSTART, SUMMARY)."""
    content = (
        b"BEGIN:VCALENDAR\r\n"
        b"VERSION:2.0\r\n"
        b"PRODID:-//Test//EN\r\n"
        b"BEGIN:VEVENT\r\n"
        b"DESCRIPTION:No UID or timestamps\r\n"
        b"END:VEVENT\r\n"
        b"BEGIN:VEVENT\r\n"
        b"UID:   \r\n"
        b"DTSTAMP:invalid\r\n"
        b"DTSTART:invalid\r\n"
        b"SUMMARY:\r\n"
        b"END:VEVENT\r\n"
        b"BEGIN:VEVENT\r\n"
        b"UID:dup-uid\r\n"
        b"DTSTAMP:20260901T120000Z\r\n"
        b"DTSTART:20260901T140000Z\r\n"
        b"SUMMARY:Game 1\r\n"
        b"END:VEVENT\r\n"
        b"BEGIN:VEVENT\r\n"
        b"UID:dup-uid\r\n"
        b"DTSTAMP:20260901T120000Z\r\n"
        b"DTSTART:20260901T140000Z\r\n"
        b"SUMMARY:Game 2\r\n"
        b"END:VEVENT\r\n"
        b"END:VCALENDAR\r\n"
    )
    ics_file = tmp_path / "event_errors.ics"
    ics_file.write_bytes(content)
    errors, _ = validate_ics_feed(ics_file)
    assert any("missing mandatory UID" in e for e in errors)
    assert any("empty UID" in e for e in errors)
    assert any("duplicate UID: dup-uid" in e for e in errors)
    assert any("missing or invalid DTSTAMP" in e for e in errors)
    assert any("missing or invalid DTSTART" in e for e in errors)
    assert any("missing or empty SUMMARY" in e for e in errors)


# -----------------------------------------------------------------------------
# CSV Validation Unit Tests (RFC 4180)
# -----------------------------------------------------------------------------


def test_csv_file_not_found(tmp_path: Path) -> None:
    """Verify error when CSV file does not exist."""
    errors, ids = validate_csv_feed(tmp_path / "missing.csv")
    assert any("not found" in e.lower() for e in errors)
    assert not ids


def test_csv_read_error(tmp_path: Path) -> None:
    """Verify error handling when reading CSV file raises OSError."""
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("dummy", encoding="utf-8")
    with patch.object(Path, "read_text", side_effect=OSError("Read failure")):
        errors, ids = validate_csv_feed(csv_file)

    assert any("failed to read" in e.lower() for e in errors)
    assert not ids


def test_csv_empty_file(tmp_path: Path) -> None:
    """Verify error when CSV file is empty."""
    csv_file = tmp_path / "empty.csv"
    csv_file.write_text("", encoding="utf-8")
    errors, ids = validate_csv_feed(csv_file)
    assert any("empty" in e.lower() for e in errors)
    assert not ids


def test_csv_no_rows(tmp_path: Path) -> None:
    """Verify error when CSV file has no content rows."""
    csv_file = tmp_path / "blank.csv"
    csv_file.write_text("   \n\n", encoding="utf-8")
    errors, ids = validate_csv_feed(csv_file)
    assert any("empty" in e.lower() for e in errors)
    assert not ids


def test_csv_empty_iterator(tmp_path: Path) -> None:
    """Verify error when CSV reader yields no rows."""
    csv_file = tmp_path / "iter_empty.csv"
    csv_file.write_text("data", encoding="utf-8")
    with patch("csv.reader", return_value=iter([])):
        errors, ids = validate_csv_feed(csv_file)

    assert any("has no rows" in e.lower() for e in errors)
    assert not ids


def test_csv_header_mismatch_and_no_data(tmp_path: Path) -> None:
    """Verify error when CSV header differs from expected columns."""
    csv_file = tmp_path / "bad_header.csv"
    csv_file.write_text("col1,col2,col3\n", encoding="utf-8")
    errors, ids = validate_csv_feed(csv_file)
    assert any("header mismatch" in e.lower() for e in errors)
    assert any("no data rows" in e.lower() for e in errors)
    assert not ids


def test_csv_row_column_count_mismatch(tmp_path: Path) -> None:
    """Verify error when a CSV row has fewer or extra columns."""
    header = ",".join(EXPECTED_CSV_COLUMNS)
    content = f"{header}\nval1,val2,val3\n"
    csv_file = tmp_path / "mismatch.csv"
    csv_file.write_text(content, encoding="utf-8")
    errors, ids = validate_csv_feed(csv_file)
    assert any("column count mismatch" in e for e in errors)
    assert not ids


def test_csv_row_validation_errors(tmp_path: Path) -> None:
    """Verify CSV field validation (dates, times, designation, scores, IDs)."""
    header = ",".join(EXPECTED_CSV_COLUMNS)
    row1 = (
        "g1,2025-2026,bad-date,bad-time,bad-iso,ECU,Opp,Opp,"
        "Neutral,Rink,City,Final,not-num,NaN,http://tix"
    )
    row2 = (
        "g1,2025-2026,2026-01-10,19:00:00,2026-01-10T19:00:00Z,"
        "ECU,Opp,Opp,Home,Rink,City,Final,5,2,http://tix"
    )
    row3 = (
        "  ,2025-2026,2026-01-11,19:00:00,2026-01-11T19:00:00Z,"
        "ECU,Opp,Opp,Away,Rink,City,Scheduled,,,http://tix"
    )
    content = f"{header}\n{row1}\n{row2}\n{row3}\n"
    csv_file = tmp_path / "row_errors.csv"
    csv_file.write_text(content, encoding="utf-8")
    errors, ids = validate_csv_feed(csv_file)

    assert any("invalid date" in e for e in errors)
    assert any("invalid time_utc" in e for e in errors)
    assert any("invalid start_time_iso" in e for e in errors)
    assert any("invalid designation" in e for e in errors)
    assert any("invalid home_score" in e for e in errors)
    assert any("invalid away_score" in e for e in errors)
    assert any("duplicate game_id: g1" in e for e in errors)
    assert any("empty game_id" in e for e in errors)
    assert ids == ["g1"]


# -----------------------------------------------------------------------------
# JSON Validation Unit Tests
# -----------------------------------------------------------------------------


def test_json_file_not_found(tmp_path: Path) -> None:
    """Verify error when JSON file does not exist."""
    errors, ids = validate_json_feed(tmp_path / "missing.json")
    assert any("not found" in e.lower() for e in errors)
    assert not ids


def test_json_parse_error(tmp_path: Path) -> None:
    """Verify error when JSON content is malformed."""
    json_file = tmp_path / "bad.json"
    json_file.write_text("not json {", encoding="utf-8")
    errors, ids = validate_json_feed(json_file)
    assert any("failed to parse" in e.lower() for e in errors)
    assert not ids


def test_json_root_not_dict(tmp_path: Path) -> None:
    """Verify error when JSON root is a list or scalar."""
    json_file = tmp_path / "list_root.json"
    json_file.write_text("[]", encoding="utf-8")
    errors, ids = validate_json_feed(json_file)
    assert any("root must be an object/dict" in e for e in errors)
    assert not ids


def test_json_top_level_missing_keys_and_types(tmp_path: Path) -> None:
    """Verify top-level structural validation errors."""
    data = {
        "primary_team": "",
        "filters": "not-a-dict",
        "games": "not-a-list",
    }
    json_file = tmp_path / "bad_top.json"
    json_file.write_text(json.dumps(data), encoding="utf-8")
    errors, ids = validate_json_feed(json_file)
    assert any("missing required top-level keys" in e for e in errors)
    assert any("primary_team' must be a non-empty string" in e for e in errors)
    assert any("filters' must be a dictionary" in e for e in errors)
    assert any("games' must be a list" in e for e in errors)
    assert not ids


def test_json_games_count_and_empty(tmp_path: Path) -> None:
    """Verify total_games mismatch and empty games array errors."""
    data = {
        "primary_team": "East Carolina University",
        "season": "2025-2026",
        "total_games": 5,
        "filters": {},
        "games": [],
    }
    json_file = tmp_path / "empty_games.json"
    json_file.write_text(json.dumps(data), encoding="utf-8")
    errors, ids = validate_json_feed(json_file)
    assert any("does not match length of games array" in e for e in errors)
    assert any("games array is empty" in e for e in errors)
    assert not ids


def test_json_game_item_errors(tmp_path: Path) -> None:
    """Verify per-game validation errors."""
    data = {
        "primary_team": "East Carolina University",
        "season": "2025-2026",
        "total_games": 4,
        "filters": {},
        "games": [
            "not a dict",
            {
                "game_id": "",
                "season": "2025-2026",
                "start_time": "2026-01-10T19:00:00Z",
                "home_team": {},
                "away_team": "invalid",
                "opponent": "NC State",
                "designation": "Neutral",
                "is_home": "yes",
                "venue": "Rink",
                "location": "City",
                "status": "Scheduled",
                "result": None,
                "home_score": None,
                "away_score": None,
                "tickets_url": None,
            },
            {
                "game_id": "game-dup",
                "season": "2025-2026",
                "start_time": "2026-01-11T19:00:00Z",
                "home_team": {"name": "ECU"},
                "away_team": {"name": "NC State"},
                "opponent": "NC State",
                "designation": "Home",
                "is_home": True,
                "venue": "Rink",
                "location": "City",
                "status": "Scheduled",
                "result": None,
                "home_score": None,
                "away_score": None,
                "tickets_url": None,
            },
            {
                # Duplicate game_id and missing required keys
                "game_id": "game-dup",
            },
        ],
    }
    json_file = tmp_path / "game_errors.json"
    json_file.write_text(json.dumps(data), encoding="utf-8")
    errors, ids = validate_json_feed(json_file)

    assert any("entry 1 is not an object" in e for e in errors)
    assert any("entry 2 has empty game_id" in e for e in errors)
    assert any("entry 2 home_team invalid or missing name" in e for e in errors)
    assert any("entry 2 away_team invalid or missing name" in e for e in errors)
    assert any("entry 2 has invalid designation" in e for e in errors)
    assert any("entry 2 'is_home' must be a boolean" in e for e in errors)
    assert any("entry 4 missing required keys" in e for e in errors)
    assert any("entry 4 has duplicate game_id: game-dup" in e for e in errors)
    assert ids == ["game-dup"]


# -----------------------------------------------------------------------------
# Cross-Feed Consistency and CLI Entrypoint Tests
# -----------------------------------------------------------------------------


def test_cross_feed_mismatch(tmp_path: Path) -> None:
    """Verify that feed inconsistencies trigger errors in validate_all_feeds."""
    # ICS with game1 and game2
    ics_content = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:game-game1@ecuhockey.com\r\n"
        "DTSTAMP:20260901T120000Z\r\n"
        "DTSTART:20260901T140000Z\r\n"
        "SUMMARY:Game 1\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:game-game2@ecuhockey.com\r\n"
        "DTSTAMP:20260901T120000Z\r\n"
        "DTSTART:20260901T140000Z\r\n"
        "SUMMARY:Game 2\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    (tmp_path / "calendar.ics").write_text(ics_content, encoding="utf-8")

    # CSV with game1 and game3
    header = ",".join(EXPECTED_CSV_COLUMNS)
    r1 = (
        "game1,2025-2026,2026-01-10,19:00:00,2026-01-10T19:00:00Z,"
        "ECU,Opp,Opp,Home,Rink,City,Final,5,2,"
    )
    r2 = (
        "game3,2025-2026,2026-01-11,19:00:00,2026-01-11T19:00:00Z,"
        "ECU,Opp,Opp,Away,Rink,City,Final,1,2,"
    )
    (tmp_path / "schedule.csv").write_text(f"{header}\n{r1}\n{r2}\n", encoding="utf-8")

    # JSON with game1 only (count mismatch and ID mismatch)
    json_data = {
        "primary_team": "East Carolina University",
        "season": "2025-2026",
        "total_games": 1,
        "filters": {},
        "games": [
            {
                "game_id": "game1",
                "season": "2025-2026",
                "start_time": "2026-01-10T19:00:00Z",
                "home_team": {"name": "ECU"},
                "away_team": {"name": "Opp"},
                "opponent": "Opp",
                "designation": "Home",
                "is_home": True,
                "venue": "Rink",
                "location": "City",
                "status": "Final",
                "result": "W",
                "home_score": 5,
                "away_score": 2,
                "tickets_url": None,
            },
        ],
    }
    (tmp_path / "schedule.json").write_text(json.dumps(json_data), encoding="utf-8")

    errors = validate_all_feeds(tmp_path)
    assert any("Feed game counts mismatch" in e for e in errors)
    assert any("Game ID discrepancy between CSV and JSON" in e for e in errors)
    assert any("Game ID discrepancy between CSV and ICS" in e for e in errors)


def test_main_cli_success(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify main() returns 0 on successful validation."""
    code = main([str(STATIC_DIR)])
    captured = capsys.readouterr()
    assert code == 0
    assert "All static feeds passed validation" in captured.out


def test_main_cli_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify main() returns 1 on validation errors."""
    code = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 1
    assert "Validation failed" in captured.err


def test_main_cli_default_argv(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify main() defaults to static directory when argv is empty."""
    monkeypatch.chdir(REPO_ROOT)
    with patch.object(sys, "argv", ["validate_feeds.py"]):
        code = main()

    captured = capsys.readouterr()
    assert code == 0
    assert "All static feeds passed validation" in captured.out

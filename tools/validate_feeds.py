"""Static feed verification utility for ECU Hockey schedule exports.

Validates:
- static/calendar.ics: RFC 5545 iCalendar specification (CRLF line endings,
    line folding <= 75 octets, mandatory header tags, VEVENT properties, UIDs).
- static/schedule.csv: RFC 4180 CSV specification (column consistency, header
    names, field formats).
- static/schedule.json: Master schedule JSON schema (structure, types,
    total_games count, game entity integrity).
- Cross-feed consistency: Game counts and game_id sets match across feeds.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

RFC5545_MAX_OCTETS: int = 75

EXPECTED_CSV_COLUMNS: list[str] = [
    "game_id",
    "season",
    "date",
    "time_utc",
    "start_time_iso",
    "home_team",
    "away_team",
    "opponent",
    "designation",
    "venue",
    "location",
    "status",
    "home_score",
    "away_score",
    "tickets_url",
]

EXPECTED_JSON_TOP_KEYS: set[str] = {
    "primary_team",
    "season",
    "total_games",
    "filters",
    "games",
}

EXPECTED_JSON_GAME_KEYS: set[str] = {
    "game_id",
    "season",
    "start_time",
    "home_team",
    "away_team",
    "opponent",
    "designation",
    "is_home",
    "venue",
    "location",
    "status",
    "result",
    "home_score",
    "away_score",
    "tickets_url",
}


def _validate_single_event(
    idx: int,
    block: str,
    seen_uids: set[str],
) -> tuple[list[str], str | None]:
    """Validate a single VEVENT component from an iCalendar feed.

    Args:
        idx: 1-based index of the event component.
        block: Text content of the VEVENT block.
        seen_uids: Set of UIDs encountered so far.

    Returns:
        A tuple of (errors, extracted_game_id).
    """
    errors: list[str] = []
    extracted_gid: str | None = None

    uid_match = re.search(r"^UID:(.+)$", block, re.MULTILINE)
    if not uid_match:
        errors.append(f"Event {idx} missing mandatory UID property.")
    else:
        uid = uid_match.group(1).strip()
        if not uid:
            errors.append(f"Event {idx} has empty UID.")
        elif uid in seen_uids:
            errors.append(f"Event {idx} has duplicate UID: {uid}")
        else:
            seen_uids.add(uid)
            gid_m = re.match(r"^game-(.+)@ecuhockey\.com$", uid)
            if gid_m:
                extracted_gid = str(gid_m.group(1))

    if not re.search(r"^DTSTAMP:\d{8}T\d{6}Z", block, re.MULTILINE):
        errors.append(f"Event {idx} missing or invalid DTSTAMP timestamp.")

    if not re.search(r"^DTSTART:\d{8}T\d{6}Z", block, re.MULTILINE):
        errors.append(f"Event {idx} missing or invalid DTSTART timestamp.")

    if not re.search(r"^SUMMARY:(.+)$", block, re.MULTILINE):
        errors.append(f"Event {idx} missing or empty SUMMARY property.")

    return errors, extracted_gid


def _validate_ics_structure(lines: list[bytes], unfolded_lines: list[str]) -> list[str]:
    """Validate header, footer, and line length rules for RFC 5545.

    Args:
        lines: Raw bytes lines split by CRLF.
        unfolded_lines: Decoded and unfolded lines.

    Returns:
        List of validation errors found.
    """
    errors: list[str] = []

    for idx, line in enumerate(lines, 1):
        if len(line) > RFC5545_MAX_OCTETS:
            snippet = repr(line[:30])
            errors.append(
                f"ICS line {idx} exceeds {RFC5545_MAX_OCTETS} octets "
                f"({len(line)} octets): {snippet}...",
            )

    if not unfolded_lines or unfolded_lines[0] != "BEGIN:VCALENDAR":
        errors.append("ICS file must begin with BEGIN:VCALENDAR.")

    if not unfolded_lines or unfolded_lines[-1] != "END:VCALENDAR":
        errors.append("ICS file must end with END:VCALENDAR.")

    if not any(item == "VERSION:2.0" for item in unfolded_lines):
        errors.append("ICS file missing mandatory VERSION:2.0 property.")

    if not any(item.startswith("PRODID:") for item in unfolded_lines):
        errors.append("ICS file missing mandatory PRODID property.")

    return errors


def validate_ics_feed(path: Path) -> tuple[list[str], list[str]]:
    """Validate an iCalendar (.ics) file against RFC 5545 requirements.

    Args:
        path: Path to the .ics file.

    Returns:
        A tuple of (errors, extracted_game_ids).
    """
    errors: list[str] = []
    game_ids: list[str] = []

    if not path.is_file():
        return [f"ICS file not found: {path}"], []

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        return [f"Failed to read ICS file {path}: {exc}"], []

    if not raw_bytes:
        return [f"ICS file is empty: {path}"], []

    if b"\r" not in raw_bytes or raw_bytes.count(b"\r\n") != raw_bytes.count(b"\n"):
        errors.append("ICS file contains non-CRLF line endings (violates RFC 5545).")

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"ICS file is not valid UTF-8: {exc}"], []

    lines = raw_bytes.split(b"\r\n")
    unfolded = re.sub(r"\r\n[ \t]", "", text)
    unfolded_lines = [item.strip() for item in unfolded.splitlines() if item.strip()]

    errors.extend(_validate_ics_structure(lines, unfolded_lines))

    event_blocks = re.findall(
        r"BEGIN:VEVENT\r?\n(.*?)\r?\nEND:VEVENT",
        unfolded,
        re.DOTALL,
    )
    if not event_blocks:
        errors.append("ICS file contains no VEVENT components.")

    seen_uids: set[str] = set()
    for idx, block in enumerate(event_blocks, 1):
        event_errors, gid = _validate_single_event(idx, block, seen_uids)
        errors.extend(event_errors)
        if gid:
            game_ids.append(gid)

    return errors, game_ids


def _validate_csv_row(
    row_idx: int,
    row: list[str],
    seen_ids: set[str],
) -> tuple[list[str], str | None]:
    """Validate a single row of CSV schedule feed.

    Args:
        row_idx: 1-based line number for error reporting.
        row: Column values for this row.
        seen_ids: Set of game IDs encountered so far.

    Returns:
        A tuple of (errors, extracted_game_id).
    """
    errors: list[str] = []
    expected_len = len(EXPECTED_CSV_COLUMNS)

    if len(row) != expected_len:
        return [
            (
                f"CSV row {row_idx} column count mismatch: "
                f"expected {expected_len}, got {len(row)}."
            ),
        ], None

    row_dict = dict(zip(EXPECTED_CSV_COLUMNS, row, strict=True))
    gid = row_dict["game_id"].strip()
    extracted_gid: str | None = None

    if not gid:
        errors.append(f"CSV row {row_idx} has empty game_id.")
    elif gid in seen_ids:
        errors.append(f"CSV row {row_idx} has duplicate game_id: {gid}")
    else:
        seen_ids.add(gid)
        extracted_gid = gid

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", row_dict["date"]):
        errors.append(f"CSV row {row_idx} has invalid date: {row_dict['date']!r}")

    if not re.match(r"^\d{2}:\d{2}:\d{2}$", row_dict["time_utc"]):
        errors.append(
            f"CSV row {row_idx} has invalid time_utc: {row_dict['time_utc']!r}",
        )

    if not re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        row_dict["start_time_iso"],
    ):
        errors.append(
            f"CSV row {row_idx} has invalid start_time_iso: "
            f"{row_dict['start_time_iso']!r}",
        )

    if row_dict["designation"] not in {"Home", "Away"}:
        errors.append(
            f"CSV row {row_idx} has invalid designation: {row_dict['designation']!r}",
        )

    for score_col in ("home_score", "away_score"):
        val = row_dict[score_col].strip()
        if val and not val.isdigit():
            errors.append(
                f"CSV row {row_idx} has invalid {score_col}: {val!r} "
                "(must be integer or empty)",
            )

    return errors, extracted_gid


def validate_csv_feed(path: Path) -> tuple[list[str], list[str]]:
    """Validate a CSV schedule feed against RFC 4180 structure.

    Args:
        path: Path to the .csv file.

    Returns:
        A tuple of (errors, extracted_game_ids).
    """
    errors: list[str] = []
    game_ids: list[str] = []

    if not path.is_file():
        return [f"CSV file not found: {path}"], []

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"Failed to read CSV file {path}: {exc}"], []

    if not content.strip():
        return [f"CSV file is empty: {path}"], []

    reader = csv.reader(content.splitlines())
    try:
        header = next(reader)
    except StopIteration:
        return [f"CSV file has no rows: {path}"], []

    if header != EXPECTED_CSV_COLUMNS:
        errors.append(
            f"CSV header mismatch.\n"
            f"Expected: {EXPECTED_CSV_COLUMNS}\n"
            f"Found:    {header}",
        )

    seen_ids: set[str] = set()
    for row_idx, row in enumerate(reader, 2):
        row_errors, gid = _validate_csv_row(row_idx, row, seen_ids)
        errors.extend(row_errors)
        if gid:
            game_ids.append(gid)

    if not game_ids:
        errors.append("CSV file contains no data rows.")

    return errors, game_ids


def _validate_json_game(
    idx: int,
    game: object,
    seen_ids: set[str],
) -> tuple[list[str], str | None]:
    """Validate a single game entity within the JSON feed.

    Args:
        idx: 1-based index of the game in the games array.
        game: The game object to inspect.
        seen_ids: Set of game IDs encountered so far.

    Returns:
        A tuple of (errors, extracted_game_id).
    """
    errors: list[str] = []

    if not isinstance(game, dict):
        return [f"JSON game entry {idx} is not an object."], None

    missing_gkeys = EXPECTED_JSON_GAME_KEYS - game.keys()
    if missing_gkeys:
        errors.append(
            f"JSON game entry {idx} missing required keys: {sorted(missing_gkeys)}",
        )

    gid = str(game.get("game_id", "")).strip()
    extracted_gid: str | None = None
    if not gid:
        errors.append(f"JSON game entry {idx} has empty game_id.")
    elif gid in seen_ids:
        errors.append(f"JSON game entry {idx} has duplicate game_id: {gid}")
    else:
        seen_ids.add(gid)
        extracted_gid = gid

    home_team = game.get("home_team")
    if not isinstance(home_team, dict) or not home_team.get("name"):
        errors.append(f"JSON game entry {idx} home_team invalid or missing name.")

    away_team = game.get("away_team")
    if not isinstance(away_team, dict) or not away_team.get("name"):
        errors.append(f"JSON game entry {idx} away_team invalid or missing name.")

    if game.get("designation") not in {"Home", "Away"}:
        errors.append(
            f"JSON game entry {idx} has invalid designation: "
            f"{game.get('designation')!r}",
        )

    if not isinstance(game.get("is_home"), bool):
        errors.append(f"JSON game entry {idx} 'is_home' must be a boolean.")

    return errors, extracted_gid


def _validate_json_top_level(
    data: dict[str, object],
    games: list[object] | None,
) -> list[str]:
    """Validate top-level keys and structure of master schedule JSON.

    Args:
        data: Parsed JSON root object.
        games: Extracted games list or None.

    Returns:
        List of validation errors found.
    """
    errors: list[str] = []
    missing_keys = EXPECTED_JSON_TOP_KEYS - data.keys()
    if missing_keys:
        errors.append(f"JSON missing required top-level keys: {sorted(missing_keys)}")

    primary_team = data.get("primary_team")
    if not isinstance(primary_team, str) or not primary_team.strip():
        errors.append("JSON 'primary_team' must be a non-empty string.")

    if not isinstance(data.get("filters"), dict):
        errors.append("JSON 'filters' must be a dictionary.")

    if games is not None:
        total_games = data.get("total_games")
        if total_games != len(games):
            errors.append(
                f"JSON 'total_games' ({total_games}) does not match "
                f"length of games array ({len(games)}).",
            )

    return errors


def validate_json_feed(path: Path) -> tuple[list[str], list[str]]:
    """Validate master schedule JSON feed against schema.

    Args:
        path: Path to the .json file.

    Returns:
        A tuple of (errors, extracted_game_ids).
    """
    errors: list[str] = []
    game_ids: list[str] = []

    if not path.is_file():
        return [f"JSON file not found: {path}"], []

    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"Failed to parse JSON file {path}: {exc}"], []

    if not isinstance(data, dict):
        return [f"JSON root must be an object/dict: {path}"], []

    games = data.get("games")
    if not isinstance(games, list):
        top_errors = _validate_json_top_level(data, None)
        return [*top_errors, "JSON 'games' must be a list."], []

    errors.extend(_validate_json_top_level(data, games))

    seen_ids: set[str] = set()
    for idx, game in enumerate(games, 1):
        g_errors, gid = _validate_json_game(idx, game, seen_ids)
        errors.extend(g_errors)
        if gid:
            game_ids.append(gid)

    if not game_ids:
        errors.append("JSON games array is empty.")

    return errors, game_ids


def validate_all_feeds(directory: Path) -> list[str]:
    """Validate all static schedule export feeds in a directory.

    Args:
        directory: Directory containing calendar.ics, schedule.csv, and schedule.json.

    Returns:
        List of all validation errors found.
    """
    all_errors: list[str] = []

    ics_path = directory / "calendar.ics"
    csv_path = directory / "schedule.csv"
    json_path = directory / "schedule.json"

    ics_errors, ics_ids = validate_ics_feed(ics_path)
    csv_errors, csv_ids = validate_csv_feed(csv_path)
    json_errors, json_ids = validate_json_feed(json_path)

    all_errors.extend(ics_errors)
    all_errors.extend(csv_errors)
    all_errors.extend(json_errors)

    # Cross-feed consistency checks
    if ics_ids and csv_ids and json_ids:
        if len(ics_ids) != len(csv_ids) or len(csv_ids) != len(json_ids):
            all_errors.append(
                f"Feed game counts mismatch: "
                f"ICS={len(ics_ids)}, CSV={len(csv_ids)}, JSON={len(json_ids)}",
            )

        ics_set = set(ics_ids)
        csv_set = set(csv_ids)
        json_set = set(json_ids)

        if csv_set != json_set:
            diff_csv_json = csv_set ^ json_set
            all_errors.append(
                f"Game ID discrepancy between CSV and JSON: {diff_csv_json}",
            )

        if csv_set != ics_set:
            diff_csv_ics = csv_set ^ ics_set
            all_errors.append(
                f"Game ID discrepancy between CSV and ICS: {diff_csv_ics}",
            )

    return all_errors


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for static feed validation.

    Args:
        argv: Optional command line arguments.

    Returns:
        0 if all feeds pass validation, 1 otherwise.
    """
    args = argv if argv is not None else sys.argv[1:]
    target_dir = Path(args[0]) if args else Path("static")

    print(f"Validating static feeds in: {target_dir.resolve()}...")

    errors = validate_all_feeds(target_dir)

    if errors:
        print(f"\n❌ Validation failed with {len(errors)} error(s):", file=sys.stderr)
        for err in errors:
            print(f"  • {err}", file=sys.stderr)

        return 1

    print("\n✅ All static feeds passed validation:")
    print(f"  • {target_dir / 'calendar.ics'} (RFC 5545 compliant)")
    print(f"  • {target_dir / 'schedule.csv'} (RFC 4180 compliant)")
    print(f"  • {target_dir / 'schedule.json'} (Schema valid & cross-feed consistent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""HockeyTech ModuleKit JSON schedule and season parser for ACHA Hockey."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from ecu_hockey_calendar.ingestion.html_parser import (
    ParsedGameRecord,
    _generate_game_id,
)
from ecu_hockey_calendar.ingestion.normalizer import (
    normalize_logo_url,
    normalize_team_name,
    parse_game_datetime,
)
from ecu_hockey_calendar.storage.models import GameStatus

CLIENT_CODE = "acha"
DEFAULT_APP_KEY = "e6867b36742a0c9d"  # pragma: allowlist secret
ECU_TEAM_ID = "589"
DEFAULT_ACHA_PORTAL_URL = "https://www.achahockey.org"
DEFAULT_BASE_URL = "https://lscluster.hockeytech.com/feed/index.php"
DEFAULT_TIMEZONE = "America/New_York"
COLLEGIATE_SEASON_START_MONTH = 8
SHORT_YEAR_LENGTH = 2

KNOWN_SEASONS: dict[str, str] = {
    "2026-2027": "73",
    "2025-2026": "60",
    "2024-2025": "46",
    "2023-2024": "34",
    "2022-2023": "21",
}

KNOWN_SEASON_IDS: dict[str, str] = {
    season_id: season_str for season_str, season_id in KNOWN_SEASONS.items()
}


def clean_team_name(raw_name: str) -> str:
    """Clean team name by stripping collegiate division prefixes and normalizing.

    Args:
        raw_name: Uncleaned raw team name (e.g. 'MD2 East Carolina University').

    Returns:
        Canonical normalized team name.
    """
    cleaned = re.sub(
        r"^(?:MD?[1-3]|W[1-2]|M[1-3])\s+",
        "",
        raw_name.strip(),
    ).strip()
    return normalize_team_name(cleaned)


def _extract_overtime_note(game: dict[str, Any]) -> str | None:
    """Extract overtime or shootout modifier from game attributes."""
    status_text = str(game.get("game_status", "")).lower()
    if str(game.get("shootout", "")) == "1" or "so" in status_text:
        return "SO"

    if str(game.get("overtime", "")) == "1" or "ot" in status_text:
        return "OT"

    return None


def _is_final_game(
    game: dict[str, Any],
    status_code: str,
    status_text: str,
) -> bool:
    """Determine whether game has concluded."""
    return (
        str(game.get("final", "")) == "1"
        or status_code == "4"
        or "final" in status_text
    )


def _is_postponed_game(status_code: str, status_text: str) -> bool:
    """Determine whether game was postponed."""
    return status_code == "8" or "postponed" in status_text


def _is_in_progress_game(
    game: dict[str, Any],
    status_code: str,
    status_text: str,
) -> bool:
    """Determine whether game is currently live in progress."""
    return (
        str(game.get("started", "")) == "1"
        or status_code in ("2", "3")
        or "in progress" in status_text
    )


def parse_achahockey_game_status(
    game: dict[str, Any],
) -> tuple[GameStatus, str | None]:
    """Parse domain GameStatus and overtime note from HockeyTech game dictionary.

    Args:
        game: Raw game dictionary from HockeyTech feed.

    Returns:
        Tuple of (GameStatus, overtime_note).
    """
    status_code = str(game.get("status", "")).strip()
    status_text = str(game.get("game_status", "")).strip().lower()

    if _is_final_game(game, status_code, status_text):
        return GameStatus.FINAL, _extract_overtime_note(game)

    if _is_postponed_game(status_code, status_text):
        return GameStatus.POSTPONED, None

    if "cancel" in status_text:
        return GameStatus.CANCELLED, None

    if _is_in_progress_game(game, status_code, status_text):
        return GameStatus.IN_PROGRESS, None

    return GameStatus.SCHEDULED, None


def _parse_iso_string(iso_str: object) -> datetime | None:
    """Attempt parsing ISO8601 string and convert to UTC datetime."""
    if not isinstance(iso_str, str) or not iso_str:
        return None

    try:
        dt = datetime.fromisoformat(iso_str.strip())
        if dt.tzinfo is not None:
            return dt.astimezone(UTC)

        return dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _fallback_game_datetime(game: dict[str, Any]) -> datetime:
    """Fallback datetime parsing using separate date, time, and timezone fields."""
    date_str = str(game.get("date_played", "")).strip()
    time_str = str(
        game.get("scheduled_time") or game.get("schedule_time") or "",
    ).strip()
    tz_name = str(game.get("timezone") or DEFAULT_TIMEZONE).strip()
    return parse_game_datetime(date_str, time_str, tz_name=tz_name)


def parse_achahockey_datetime(game: dict[str, Any]) -> datetime:
    """Extract and normalize game start datetime to UTC.

    Args:
        game: Raw game item from HockeyTech schedule feed.

    Returns:
        Timezone-aware datetime in UTC.
    """
    dt_iso = _parse_iso_string(game.get("GameDateISO8601"))
    if dt_iso is not None:
        return dt_iso

    dt_played = _parse_iso_string(game.get("date_time_played"))
    if dt_played is not None:
        return dt_played

    return _fallback_game_datetime(game)


def format_achahockey_venue(game: dict[str, Any]) -> str:
    """Format venue string from name and location fields.

    Args:
        game: Raw game item from HockeyTech schedule feed.

    Returns:
        Consolidated venue string or 'TBD'.
    """
    name = str(game.get("venue_name", "")).strip()
    loc = str(game.get("venue_location", "")).strip()

    if not name:
        return loc or "TBD"

    if not loc or loc in name:
        return name

    return f"{name}, {loc}"


def _parse_int_score(score_val: object) -> int | None:
    """Safely convert score value to integer or None."""
    if score_val is None:
        return None

    try:
        return int(str(score_val).strip())
    except (ValueError, TypeError):
        return None


def parse_achahockey_scores(
    game: dict[str, Any],
    status: GameStatus,
) -> tuple[int | None, int | None]:
    """Extract home and away goal scores for completed or active games.

    Args:
        game: Raw game item from HockeyTech schedule feed.
        status: Normalized game status.

    Returns:
        Tuple of (home_score, away_score).
    """
    if status not in (GameStatus.FINAL, GameStatus.IN_PROGRESS):
        return None, None

    home_score = _parse_int_score(game.get("home_goal_count"))
    away_score = _parse_int_score(game.get("visiting_goal_count"))
    return home_score, away_score


def resolve_achahockey_teams(
    game: dict[str, Any],
    target_team_id: str = ECU_TEAM_ID,
) -> tuple[bool, str]:
    """Determine home orientation and clean opponent name.

    Args:
        game: Raw game item from HockeyTech schedule feed.
        target_team_id: Identifier for target team (ECU = '589').

    Returns:
        Tuple of (is_home, opponent_name).
    """
    is_home = str(game.get("home_team", "")).strip() == target_team_id
    raw_opp = str(
        game.get("visiting_team_name" if is_home else "home_team_name", ""),
    )
    return is_home, clean_team_name(raw_opp)


def resolve_achahockey_season(
    season_id: str,
    start_time: datetime,
    season_map: dict[str, str] | None = None,
) -> str:
    """Resolve canonical season string like '2026-2027' for a game.

    Args:
        season_id: Numeric HockeyTech season ID.
        start_time: Start timestamp of the fixture.
        season_map: Optional dynamic season ID to label map.

    Returns:
        Formatted season string 'YYYY-YYYY'.
    """
    if season_map and season_id in season_map:
        return season_map[season_id]

    if season_id in KNOWN_SEASON_IDS:
        return KNOWN_SEASON_IDS[season_id]

    if start_time.month >= COLLEGIATE_SEASON_START_MONTH:
        return f"{start_time.year}-{start_time.year + 1}"

    return f"{start_time.year - 1}-{start_time.year}"


def _filter_dict_items(items: object) -> list[dict[str, Any]]:
    """Filter list elements ensuring each item is a dictionary."""
    if not isinstance(items, list):
        return []

    return [item for item in items if isinstance(item, dict)]


def _extract_game_items_from_dict(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract game dictionaries from JSON mapping."""
    site_kit = payload.get("SiteKit")
    if isinstance(site_kit, dict) and "Schedule" in site_kit:
        return _filter_dict_items(site_kit["Schedule"])

    return _filter_dict_items(payload.get("Schedule"))


def _extract_game_items(payload: object) -> list[dict[str, Any]]:
    """Extract list of game dictionaries from parsed payload."""
    if isinstance(payload, list):
        return _filter_dict_items(payload)

    if isinstance(payload, dict):
        return _extract_game_items_from_dict(payload)

    return []


def _find_dict_key_value(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """Find first matching string value for given keys."""
    for key in keys:
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return str(val).strip()

    return None


def _format_cdn_team_logo(team_id: str) -> str | None:
    """Construct HockeyTech CDN team logo URL if team ID is numeric."""
    return (
        f"https://assets.leaguestat.com/acha/logos/{team_id}.png"
        if team_id.isdigit()
        else None
    )


def _extract_achahockey_opponent_logo(
    game: dict[str, Any],
    *,
    is_home: bool,
) -> str | None:
    """Extract or construct opponent logo URL from game record."""
    pfx = "visiting" if is_home else "home"
    keys = (f"{pfx}_team_logo", f"{pfx}_team_image", f"{pfx}_logo", "opponent_logo")
    raw_logo = _find_dict_key_value(game, keys)
    norm = normalize_logo_url(raw_logo)
    if norm:
        return norm

    team_id = str(game.get(f"{pfx}_team", "")).strip()
    return _format_cdn_team_logo(team_id)


def _build_game_metadata(
    game: dict[str, Any],
    league_game_id: str,
    season_id: str,
    season: str,
    opponent_logo_url: str | None = None,
) -> dict[str, Any]:
    """Assemble supplementary verification metadata dictionary."""
    return {
        "league_game_id": league_game_id,
        "season_id": season_id,
        "season": season,
        "source": "achahockey",
        "opponent_logo_url": opponent_logo_url,
        "venue_name": game.get("venue_name", ""),
        "venue_location": game.get("venue_location", ""),
        "venue_url": game.get("venue_url", ""),
        "mobile_calendar": game.get("mobile_calendar", ""),
    }


def _parse_game_item(  # pylint: disable=too-many-locals
    game: dict[str, Any],
    season_hint: str | None,
    season_map: dict[str, str] | None,
    target_team_id: str,
) -> ParsedGameRecord | None:
    """Parse a single HockeyTech schedule game item into ParsedGameRecord."""
    league_game_id = str(game.get("game_id") or game.get("id") or "").strip()
    if not league_game_id:
        return None

    is_home, opp_name = resolve_achahockey_teams(
        game,
        target_team_id=target_team_id,
    )
    start_time = parse_achahockey_datetime(game)
    status, ot_note = parse_achahockey_game_status(game)
    h_score, a_score = parse_achahockey_scores(game, status)
    venue = format_achahockey_venue(game)

    season_id = str(game.get("season_id", "")).strip()
    season = season_hint or resolve_achahockey_season(
        season_id,
        start_time,
        season_map,
    )

    opp_logo_url = _extract_achahockey_opponent_logo(game, is_home=is_home)
    metadata = _build_game_metadata(
        game,
        league_game_id,
        season_id,
        season,
        opponent_logo_url=opp_logo_url,
    )
    game_id = _generate_game_id(start_time, opp_name, is_home=is_home)
    return ParsedGameRecord(
        game_id=game_id,
        opponent_name=opp_name,
        is_home=is_home,
        start_time=start_time,
        venue=venue,
        status=status,
        home_score=h_score,
        away_score=a_score,
        overtime_note=ot_note,
        raw_text=json.dumps(game, sort_keys=True),
        league_game_id=league_game_id,
        opponent_logo_url=opp_logo_url,
        metadata=metadata,
    )


def _safe_json_loads(payload: object) -> object:
    """Safely decode JSON string or return structured object."""
    if not isinstance(payload, str):
        return payload

    try:
        return json.loads(payload)
    except (ValueError, TypeError):
        return None


def parse_achahockey_schedule_json(
    payload: str | dict[str, Any] | list[Any],
    *,
    season_hint: str | None = None,
    season_map: dict[str, str] | None = None,
    target_team_id: str = ECU_TEAM_ID,
) -> list[ParsedGameRecord]:
    """Parse HockeyTech ModuleKit schedule JSON payload into ParsedGameRecords.

    Args:
        payload: JSON string or parsed dictionary/list payload.
        season_hint: Optional season override string.
        season_map: Optional season_id to season_str mapping dictionary.
        target_team_id: Target team identifier code.

    Returns:
        List of parsed game records.
    """
    data = _safe_json_loads(payload)
    if data is None:
        return []

    items = _extract_game_items(data)
    records: list[ParsedGameRecord] = []

    for item in items:
        rec = _parse_game_item(
            item,
            season_hint,
            season_map,
            target_team_id,
        )
        if rec is not None:
            records.append(rec)

    return records


def _is_target_season_item(item: dict[str, Any]) -> bool:
    """Filter candidate seasons for Men's regular season divisions."""
    if str(item.get("playoff", "")).strip() != "0":
        return False

    name = str(item.get("season_name", "")).lower()
    if "women" in name:
        return False

    if "men" not in name:
        return False

    return "divisions" in name or "regular season" in name


def _extract_season_code(name: str) -> str | None:
    """Extract standard 'YYYY-YYYY' season format from season name string."""
    match = re.search(r"(\d{4})-(\d{2,4})", name)
    if not match:
        return None

    y1 = match.group(1)
    y2 = match.group(2)
    if len(y2) == SHORT_YEAR_LENGTH:
        y2 = f"{y1[:SHORT_YEAR_LENGTH]}{y2}"

    return f"{y1}-{y2}"


def _extract_season_items_from_dict(
    data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract season dictionaries from JSON mapping."""
    site_kit = data.get("SiteKit")
    if isinstance(site_kit, dict) and "Seasons" in site_kit:
        return _filter_dict_items(site_kit["Seasons"])

    return _filter_dict_items(data.get("Seasons"))


def _extract_season_items(data: object) -> list[dict[str, Any]]:
    """Extract list of candidate season dictionaries from payload."""
    if isinstance(data, list):
        return _filter_dict_items(data)

    if isinstance(data, dict):
        return _extract_season_items_from_dict(data)

    return []


def _parse_single_season(item: dict[str, Any]) -> tuple[str, str] | None:
    """Parse a single season item if it matches target filter."""
    if not _is_target_season_item(item):
        return None

    s_id = str(item.get("season_id", "")).strip()
    s_name = str(item.get("season_name", "")).strip()
    code = _extract_season_code(s_name)
    if code and s_id:
        return code, s_id

    return None


def parse_achahockey_seasons_json(
    payload: str | dict[str, Any] | list[Any],
) -> dict[str, str]:
    """Parse HockeyTech ModuleKit seasons JSON feed to discover season IDs.

    Args:
        payload: JSON string or parsed dictionary/list from seasons view.

    Returns:
        Dictionary mapping canonical season strings (e.g. '2026-2027') to season_id.
    """
    data = _safe_json_loads(payload)
    if data is None:
        return {}

    items = _extract_season_items(data)
    seasons: dict[str, str] = {}

    for item in items:
        res = _parse_single_season(item)
        if res is not None:
            code, s_id = res
            seasons[code] = s_id

    return seasons


def _clean_jsonp_payload(payload: str) -> str:
    """Strip JSONP wrapper if present."""
    trimmed = payload.strip()
    match = re.search(r"^[a-zA-Z0-9_$.]+\s*\(([\s\S]*)\)\s*;?$", trimmed)
    if match:
        return str(match.group(1)).strip()

    return trimmed


def _extract_dict_team_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract list of team dictionary entries from dictionary wrapper."""
    for key in ("teams", "teamsNoAll", "Teams", "team_list", "data"):
        val = data.get(key)
        if isinstance(val, list):
            return [x for x in val if isinstance(x, dict)]

    return []


def _extract_team_items_from_data(data: object) -> list[dict[str, Any]]:
    """Extract list of team dictionary entries from parsed JSON structure."""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]

    if isinstance(data, dict):
        return _extract_dict_team_items(data)

    return []


def _resolve_team_logo_from_dict(team_dict: dict[str, Any]) -> str | None:
    """Resolve normalized logo URL or CDN fallback from team dictionary."""
    keys = ("logo", "team_logo", "logo_url", "Logo")
    raw_logo = _find_dict_key_value(team_dict, keys)
    norm = normalize_logo_url(raw_logo)
    if norm:
        return norm

    team_id = str(team_dict.get("id") or team_dict.get("team_id") or "").strip()
    return _format_cdn_team_logo(team_id)


def _parse_single_team_logo(
    team_dict: dict[str, Any],
) -> tuple[str, str] | None:
    """Extract cleaned name and resolved logo for single team dictionary."""
    keys = ("name", "team_name", "Name")
    raw_name = _find_dict_key_value(team_dict, keys)
    if not raw_name:
        return None

    cleaned_name = clean_team_name(raw_name)
    logo = _resolve_team_logo_from_dict(team_dict)
    if logo and cleaned_name:
        return cleaned_name, logo

    return None


def parse_achahockey_teams_json(payload: object) -> dict[str, str]:
    """Parse HockeyTech teams feed JSON or JSONP payload into logo mapping.

    Args:
        payload: JSON string, JSONP string, or parsed dict/list.

    Returns:
        Mapping of cleaned normalized team name to canonical logo URL.
    """
    raw_obj = payload
    if isinstance(payload, str):
        cleaned_json = _clean_jsonp_payload(payload)
        raw_obj = _safe_json_loads(cleaned_json)

    if not raw_obj:
        return {}

    items = _extract_team_items_from_data(raw_obj)
    logos: dict[str, str] = {}
    for t_dict in items:
        pair = _parse_single_team_logo(t_dict)
        if pair is not None:
            logos[pair[0]] = pair[1]

    return logos


__all__ = [
    "CLIENT_CODE",
    "COLLEGIATE_SEASON_START_MONTH",
    "DEFAULT_ACHA_PORTAL_URL",
    "DEFAULT_APP_KEY",
    "DEFAULT_BASE_URL",
    "DEFAULT_TIMEZONE",
    "ECU_TEAM_ID",
    "KNOWN_SEASONS",
    "KNOWN_SEASON_IDS",
    "SHORT_YEAR_LENGTH",
    "clean_team_name",
    "format_achahockey_venue",
    "parse_achahockey_datetime",
    "parse_achahockey_game_status",
    "parse_achahockey_schedule_json",
    "parse_achahockey_scores",
    "parse_achahockey_seasons_json",
    "parse_achahockey_teams_json",
    "resolve_achahockey_season",
    "resolve_achahockey_teams",
]

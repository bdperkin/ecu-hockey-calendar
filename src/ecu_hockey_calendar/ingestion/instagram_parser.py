"""Parser for Instagram posts, game announcements, and schedule updates."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from ecu_hockey_calendar.ingestion.html_parser import ParsedGameRecord
from ecu_hockey_calendar.ingestion.normalizer import (
    DEFAULT_TIMEZONE,
    normalize_team_name,
)
from ecu_hockey_calendar.storage.models import GameStatus

if TYPE_CHECKING:
    from ecu_hockey_calendar.storage.models import GameModel

DEFAULT_INSTAGRAM_USERNAME = "ecuicehockey"
DEFAULT_INSTAGRAM_URL = "https://www.instagram.com/ecuicehockey/"
DEFAULT_GRAPH_API_URL = "https://graph.instagram.com/v19.0/me/media"
DEFAULT_WEB_PROFILE_URL = (
    "https://www.instagram.com/api/v1/users/web_profile_info/?username=ecuicehockey"
)
IG_APP_ID = "936619743392459"

_MONTHS_RAW = (
    "jan:1 january:1 feb:2 february:2 mar:3 march:3 apr:4 april:4 "
    "may:5 jun:6 june:6 jul:7 july:7 aug:8 august:8 "
    "sep:9 september:9 oct:10 october:10 nov:11 november:11 dec:12 december:12"
)
MONTH_MAP: dict[str, int] = {
    pair.split(":")[0]: int(pair.split(":")[1]) for pair in _MONTHS_RAW.split()
}

MIN_TEAM_NAME_LEN = 2
HOURS_IN_HALF_DAY = 12
MAX_HOURS_24 = 23
MAX_MINUTES_60 = 59
DATE_GROUP_YEAR_INDEX = 3
FOUR_DIGIT_YEAR_LEN = 4
CENTURY_2000_OFFSET = 2000


class AnnouncementType(StrEnum):
    """Classification of social media announcements."""

    GAME_DAY = "game_day"
    TIME_CHANGE = "time_change"
    CANCELLATION = "cancellation"
    POSTPONEMENT = "postponement"
    SCORE_UPDATE = "score_update"
    GENERAL = "general"


def _resolve_post_venue(post: ParsedInstagramPost, *, is_home: bool) -> str:
    """Resolve venue name for synthesized game record."""
    if post.venue:
        return post.venue

    return "Carolina Ice Palace" if is_home else "TBD"


def _resolve_post_status(post: ParsedInstagramPost) -> GameStatus:
    """Resolve game lifecycle status enum from post status override."""
    return post.status_override or GameStatus.SCHEDULED


def _post_to_game_record(
    post: ParsedInstagramPost,
    season: str,
) -> ParsedGameRecord | None:
    """Decomposed conversion of ParsedInstagramPost to ParsedGameRecord."""
    if not post.game_datetime or not post.opponent_name:
        return None

    is_home = post.is_home_game is not False
    return ParsedGameRecord(
        game_id=f"instagram-{post.shortcode or post.post_id}",
        opponent_name=post.opponent_name,
        is_home=is_home,
        start_time=post.game_datetime,
        venue=_resolve_post_venue(post, is_home=is_home),
        status=_resolve_post_status(post),
        metadata={
            "source": "instagram",
            "season": season,
            "source_url": post.url,
            "announcement_type": post.announcement_type.value,
            "caption_excerpt": post.caption[:160],
        },
    )


# pylint: disable=too-many-instance-attributes
@dataclass(frozen=True)
class ParsedInstagramPost:
    """Structured representation of an ingested Instagram social post."""

    post_id: str
    shortcode: str
    caption: str
    url: str
    published_at: datetime | None = None
    announcement_type: AnnouncementType = AnnouncementType.GENERAL
    opponent_name: str | None = None
    is_home_game: bool | None = None
    game_date: date | None = None
    game_time: time | None = None
    game_datetime: datetime | None = None
    venue: str | None = None
    status_override: GameStatus | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def to_parsed_game_record(
        self,
        season: str = "2026-2027",
    ) -> ParsedGameRecord | None:
        """Convert parsed announcement post into domain ParsedGameRecord entity."""
        return _post_to_game_record(self, season)


def _resolve_post_teams(post: ParsedInstagramPost) -> tuple[str, str]:
    """Resolve home and away team names from post."""
    opp = post.opponent_name or "Unknown Opponent"
    if post.is_home_game is False:
        return opp, "East Carolina University"

    return "East Carolina University", opp


def _clean_caption_text(caption: str) -> str:
    """Normalize raw caption string by removing excessive whitespace and hashtags."""
    no_tags = re.sub(r"#\S+", "", caption)
    return " ".join(no_tags.split()).strip()


def _is_cancellation(text: str) -> bool:
    """Check if caption text indicates a cancelled game."""
    return bool(
        re.search(r"(?i)\b(?:cancel(?:led|ed|lation)|no\s*game|called\s*off)\b", text),
    )


def _is_postponement(text: str) -> bool:
    """Check if caption text indicates a postponed game."""
    return bool(
        re.search(
            r"(?i)\b(?:postponed|postponement|postpone|rescheduled|reschedule)\b",
            text,
        ),
    )


def _is_time_change(text: str) -> bool:
    """Check if caption text indicates an altered start time."""
    pattern = (
        r"(?i)\b(?:time\s*change|puck\s*drop\s*(?:moved|delayed|changed|pushed)|"
        r"start\s*time\s*(?:moved|changed|delayed|pushed|updated))\b"
    )
    return bool(re.search(pattern, text))


def _is_score_update(text: str) -> bool:
    """Check if caption text indicates a final score update."""
    pattern = (
        r"(?i)(?:\bfinal(?:\s*score)?\s*[:\-]|won\s+\d+[\-–]\d+|lost\s+\d+[\-–]\d+)"  # noqa: RUF001
    )
    return bool(re.search(pattern, text))


def _is_game_day(text: str) -> bool:
    """Check if caption text indicates a game day announcement."""
    pattern = (
        r"(?i)\b(?:game\s*day|gameday|puck\s*drop|matchup|facing|"
        r"hosting|takes?\s*on|tonight)\b"
    )
    return bool(re.search(pattern, text))


def _classify_urgent(text: str) -> AnnouncementType | None:
    """Classify urgent operational changes (cancellations, time changes)."""
    if _is_cancellation(text):
        return AnnouncementType.CANCELLATION

    if _is_postponement(text):
        return AnnouncementType.POSTPONEMENT

    if _is_time_change(text):
        return AnnouncementType.TIME_CHANGE

    return None


def classify_announcement(caption: str) -> AnnouncementType:
    """Classify the primary announcement type from an Instagram caption.

    Args:
        caption: Raw post caption text.

    Returns:
        AnnouncementType classification enum.
    """
    clean = _clean_caption_text(caption)
    urgent = _classify_urgent(clean)
    if urgent is not None:
        return urgent

    if _is_score_update(clean):
        return AnnouncementType.SCORE_UPDATE

    if _is_game_day(clean):
        return AnnouncementType.GAME_DAY

    return AnnouncementType.GENERAL


def resolve_game_status_from_announcement(
    announcement_type: AnnouncementType,
) -> GameStatus | None:
    """Map announcement type to game lifecycle status override.

    Args:
        announcement_type: Classification of announcement.

    Returns:
        GameStatus enum or None if no status change.
    """
    mapping: dict[AnnouncementType, GameStatus] = {
        AnnouncementType.CANCELLATION: GameStatus.CANCELLED,
        AnnouncementType.POSTPONEMENT: GameStatus.POSTPONED,
        AnnouncementType.SCORE_UPDATE: GameStatus.FINAL,
        AnnouncementType.GAME_DAY: GameStatus.SCHEDULED,
        AnnouncementType.TIME_CHANGE: GameStatus.SCHEDULED,
    }
    return mapping.get(announcement_type)


def _contains_ecu(name: str) -> bool:
    """Check if a string refers to ECU or Pirates."""
    return bool(re.search(r"(?i)\b(?:ecu|east carolina|pirates)\b", name))


def _clean_extracted_team(raw: str) -> str | None:
    """Clean team string candidate and verify not ECU."""
    cleaned = re.sub(r"^[^\w]+|[^\w]+$", "", raw).strip()
    if not cleaned or _contains_ecu(cleaned) or len(cleaned) < MIN_TEAM_NAME_LEN:
        return None

    return normalize_team_name(cleaned)


def _match_prefix_opponent(text: str, prefix_pattern: str) -> str | None:
    """Match opponent candidate following a prefix pattern."""
    pat = (
        rf"(?i){prefix_pattern}\s+([A-Za-z0-9\.\s'&]+?)"
        r"(?:\s+(?:tonight|moved|at|on|this|starts?|begins?|puck)|\s*[,!|\.\n]|\s*\d|$)"
    )
    match = re.search(pat, text)
    return str(match.group(1)) if match else None


def _extract_at_opponent(clean: str) -> tuple[str | None, bool | None] | None:
    """Extract away opponent indicated by @ symbol."""
    candidate = _match_prefix_opponent(clean, r"@")
    if candidate:
        team = _clean_extracted_team(candidate)
        if team:
            return team, False

    return None


def _extract_other_opponent(clean: str) -> tuple[str | None, bool | None] | None:
    """Extract opponent from vs, hosting, or facing patterns."""
    patterns = [
        (r"\b(?:vs\.?|against)", True),
        (r"\b(?:hosting|hosts)", True),
        (r"\b(?:facing|faces|takes?\s*on)", None),
    ]
    for prefix, is_home in patterns:
        candidate = _match_prefix_opponent(clean, prefix)
        if candidate:
            team = _clean_extracted_team(candidate)
            if team:
                return team, is_home

    return None


def extract_opponent_from_caption(
    caption: str,
) -> tuple[str | None, bool | None]:
    """Extract opponent name and home/away status from caption.

    Args:
        caption: Caption text string.

    Returns:
        Tuple of (opponent_name, is_home_game).
    """
    clean = _clean_caption_text(caption)
    res = _extract_at_opponent(clean)
    if res:
        return res

    other = _extract_other_opponent(clean)
    return other or (None, None)


def _adjust_12h_period(hour: int, period: str) -> int:
    """Convert 12-hour period representation into 24-hour hour value."""
    if period == "pm" and hour != HOURS_IN_HALF_DAY:
        return hour + HOURS_IN_HALF_DAY

    if period == "am" and hour == HOURS_IN_HALF_DAY:
        return 0

    return hour


def _parse_12h_time(match: re.Match[str]) -> time | None:
    """Convert regex 12-hour match groups to time instance."""
    hour = _adjust_12h_period(int(match.group(1)), match.group(3).lower())
    minute = int(match.group(2)) if match.group(2) else 0
    if 0 <= hour <= MAX_HOURS_24 and 0 <= minute <= MAX_MINUTES_60:
        return time(hour, minute)

    return None


def extract_time_from_caption(caption: str) -> time | None:
    """Extract game start time from caption.

    Args:
        caption: Raw caption text.

    Returns:
        time object or None.
    """
    pattern = r"(?i)\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b"
    matches = list(re.finditer(pattern, caption))
    for m in matches:
        t = _parse_12h_time(m)
        if t is not None:
            return t

    return None


def _parse_month_name_date(match: re.Match[str], ref_year: int) -> date | None:
    """Parse Month Name + Day date match."""
    month_str = match.group(1).lower().rstrip(".")
    month_num = MONTH_MAP.get(month_str)
    if not month_num:
        return None

    day_num = int(match.group(2))
    has_year = len(match.groups()) >= DATE_GROUP_YEAR_INDEX and match.group(
        DATE_GROUP_YEAR_INDEX,
    )
    year = int(match.group(DATE_GROUP_YEAR_INDEX)) if has_year else ref_year
    try:
        return date(year, month_num, day_num)
    except ValueError:
        return None


def _parse_numeric_date(match: re.Match[str], ref_year: int) -> date | None:
    """Parse MM/DD[/YYYY] numeric date match."""
    month_num = int(match.group(1))
    day_num = int(match.group(2))
    raw_year = (
        match.group(DATE_GROUP_YEAR_INDEX)
        if len(match.groups()) >= DATE_GROUP_YEAR_INDEX
        else None
    )
    if raw_year:
        year = (
            int(raw_year)
            if len(raw_year) == FOUR_DIGIT_YEAR_LEN
            else CENTURY_2000_OFFSET + int(raw_year)
        )
    else:
        year = ref_year

    try:
        return date(year, month_num, day_num)
    except ValueError:
        return None


def extract_date_from_caption(
    caption: str,
    reference_year: int = 2026,
) -> date | None:
    """Extract calendar date from caption.

    Args:
        caption: Caption text.
        reference_year: Year to assume when year is omitted.

    Returns:
        date instance or None.
    """
    month_pat = (
        r"(?i)\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)\.?\s+(\d{1,2})(?:st|[n]d|rd|th)?"
        r"(?:\s*[,/]?\s*(\d{4}))?\b"
    )
    if (m := re.search(month_pat, caption)) and (
        d := _parse_month_name_date(m, reference_year)
    ):
        return d

    num_pat = r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b"
    if m_num := re.search(num_pat, caption):
        return _parse_numeric_date(m_num, reference_year)

    return None


def build_game_datetime(
    game_date: date | None,
    game_time: time | None,
    tz: ZoneInfo | None = None,
) -> datetime | None:
    """Combine date and time into a timezone-aware UTC datetime.

    Args:
        game_date: Game calendar date.
        game_time: Game time.
        tz: Optional originating timezone.

    Returns:
        datetime in UTC or None.
    """
    if not game_date:
        return None

    local_tz = tz or ZoneInfo(DEFAULT_TIMEZONE)
    return datetime.combine(
        game_date,
        game_time or time(19, 0),
        tzinfo=local_tz,
    ).astimezone(UTC)


def extract_venue_from_caption(caption: str) -> str | None:
    """Extract game arena or venue from caption.

    Args:
        caption: Caption text.

    Returns:
        Venue name string or None.
    """
    known_venues = (
        "Carolina Ice Palace",
        "Greensboro Coliseum Complex",
        "Greensboro Coliseum",
        "Greensboro Ice House",
        "The Factory",
        "Clearwater Ice Arena",
        "Innsbrook After Hours",
        "Richmond Ice Zone",
        "Wake Competition Center",
        "Fort Dupont Ice Arena",
    )
    for venue in known_venues:
        if re.search(rf"(?i)\b{re.escape(venue)}\b", caption):
            return venue

    pat = (
        r"(?i)\bat\s+(?:the\s+)?([A-Z][A-Za-z0-9\s'&]+?"
        r"(?:Center|Arena|Palace|Rink|Complex|Field|Pavilion|Forum|Ice|Coliseum))\b"
    )
    match = re.search(pat, caption)
    if match:
        return str(match.group(1)).strip()

    return None


def _parse_graph_timestamp(ts_obj: object) -> datetime | None:
    """Parse ISO timestamp from Instagram Graph API."""
    if not isinstance(ts_obj, str):
        return None

    try:
        return datetime.fromisoformat(ts_obj).astimezone(UTC)
    except ValueError:
        return None


def parse_graph_api_media_item(
    item: Mapping[str, object],
) -> ParsedInstagramPost | None:
    """Parse a single media entity from Instagram Graph API.

    Args:
        item: Media item dictionary.

    Returns:
        ParsedInstagramPost instance or None.
    """
    post_id = str(item.get("id", "")).strip()
    if not post_id:
        return None

    caption = str(item.get("caption", ""))
    permalink = str(item.get("permalink", f"https://www.instagram.com/p/{post_id}/"))
    shortcode = permalink.rstrip("/").rsplit("/", maxsplit=1)[-1]
    pub_at = _parse_graph_timestamp(item.get("timestamp"))

    atype = classify_announcement(caption)
    opp, is_home = extract_opponent_from_caption(caption)
    g_date = extract_date_from_caption(caption)
    if g_date is None and pub_at is not None and atype == AnnouncementType.GAME_DAY:
        g_date = pub_at.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()

    g_time = extract_time_from_caption(caption)
    g_dt = build_game_datetime(g_date, g_time)
    venue = extract_venue_from_caption(caption)
    st = resolve_game_status_from_announcement(atype)

    return ParsedInstagramPost(
        post_id=post_id,
        shortcode=shortcode,
        caption=caption,
        url=permalink,
        published_at=pub_at,
        announcement_type=atype,
        opponent_name=opp,
        is_home_game=is_home,
        game_date=g_date,
        game_time=g_time,
        game_datetime=g_dt,
        venue=venue,
        status_override=st,
        metadata={"source": "graph_api", "media_type": str(item.get("media_type", ""))},
    )


def _extract_graph_data_items(data: object) -> list[Mapping[str, object]]:
    """Extract list of media items from Graph API payload."""
    if not isinstance(data, (dict, Mapping)):
        return []

    items = data.get("data")
    if not isinstance(items, (list, tuple)):
        return []

    return [
        cast("Mapping[str, object]", item)
        for item in items
        if isinstance(item, (dict, Mapping))
    ]


def parse_graph_api_response(data: object) -> list[ParsedInstagramPost]:
    """Parse array of media objects from Instagram Graph API response.

    Args:
        data: JSON decoded Graph API response.

    Returns:
        List of ParsedInstagramPost objects.
    """
    return [
        post
        for item in _extract_graph_data_items(data)
        if (post := parse_graph_api_media_item(item)) is not None
    ]


def _extract_first_node_text(edges: Sequence[object]) -> str:
    """Extract text from the first edge item if available."""
    if edges and isinstance(edges[0], dict):
        node = edges[0].get("node")
        if isinstance(node, dict):
            return str(node.get("text", ""))

    return ""


def _extract_edge_caption(node: Mapping[str, object]) -> str:
    """Extract caption string from GraphQL edge node."""
    caption_edges = node.get("edge_media_to_caption")
    if not isinstance(caption_edges, dict):
        return ""

    edges = caption_edges.get("edges")
    if isinstance(edges, (list, tuple)):
        return _extract_first_node_text(edges)

    return ""


def _extract_edge_timestamp(node: Mapping[str, object]) -> datetime | None:
    """Extract published UTC datetime from GraphQL node."""
    taken = node.get("taken_at_timestamp")
    if isinstance(taken, (int, float)):
        return datetime.fromtimestamp(taken, tz=UTC)

    return None


def _resolve_post_date(
    caption: str,
    pub_at: datetime | None,
    atype: AnnouncementType,
) -> date | None:
    """Resolve post date from caption or fallback to publication date."""
    g_date = extract_date_from_caption(caption)
    if g_date is None and pub_at is not None and atype == AnnouncementType.GAME_DAY:
        return pub_at.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()

    return g_date


def _build_web_post(
    node: Mapping[str, object],
    pid: str,
    sc: str,
) -> ParsedInstagramPost:
    """Construct ParsedInstagramPost from web node attributes."""
    caption = _extract_edge_caption(node)
    pub_at = _extract_edge_timestamp(node)
    url = f"https://www.instagram.com/p/{sc}/" if sc else DEFAULT_INSTAGRAM_URL

    atype = classify_announcement(caption)
    opp, is_home = extract_opponent_from_caption(caption)
    g_date = _resolve_post_date(caption, pub_at, atype)
    g_time = extract_time_from_caption(caption)
    g_dt = build_game_datetime(g_date, g_time)

    return ParsedInstagramPost(
        post_id=pid or sc,
        shortcode=sc or pid,
        caption=caption,
        url=url,
        published_at=pub_at,
        announcement_type=atype,
        opponent_name=opp,
        is_home_game=is_home,
        game_date=g_date,
        game_time=g_time,
        game_datetime=g_dt,
        venue=extract_venue_from_caption(caption),
        status_override=resolve_game_status_from_announcement(atype),
        metadata={"source": "web_api"},
    )


def parse_web_profile_post_node(
    node: Mapping[str, object],
) -> ParsedInstagramPost | None:
    """Parse GraphQL post node from Instagram web profile.

    Args:
        node: Post node dictionary.

    Returns:
        ParsedInstagramPost instance or None.
    """
    pid = str(node.get("id", "")).strip()
    sc = str(node.get("shortcode", "")).strip()
    if not pid and not sc:
        return None

    return _build_web_post(node, pid, sc)


def _extract_nested_user(
    data: Mapping[str, object],
    key: str,
) -> Mapping[str, object] | None:
    """Extract user map from nested dictionary key."""
    val = data.get(key)
    if isinstance(val, dict) and isinstance(val.get("user"), (dict, Mapping)):
        return cast("Mapping[str, object]", val["user"])

    return None


def _extract_user_dict(data: object) -> Mapping[str, object] | None:
    """Extract user dictionary from GraphQL structure."""
    if not isinstance(data, (dict, Mapping)):
        return None

    data_map = cast("Mapping[str, object]", data)
    return _extract_nested_user(data_map, "data") or _extract_nested_user(
        data_map,
        "graphql",
    )


def _extract_edges_list(user: Mapping[str, object]) -> Sequence[object]:
    """Extract edge list from timeline media dictionary."""
    timeline = user.get("edge_owner_to_timeline_media")
    if isinstance(timeline, dict) and isinstance(timeline.get("edges"), (list, tuple)):
        return cast("Sequence[object]", timeline["edges"])

    return []


def _extract_web_edges(data: object) -> list[Mapping[str, object]]:
    """Extract media edges from web profile GraphQL data."""
    user = _extract_user_dict(data)
    if not user:
        return []

    edges = _extract_edges_list(user)
    return [
        cast("Mapping[str, object]", edge["node"])
        for edge in edges
        if isinstance(edge, (dict, Mapping))
        and isinstance(edge.get("node"), (dict, Mapping))
    ]


def parse_public_feed_json(data: object) -> list[ParsedInstagramPost]:
    """Parse public web profile JSON response from Instagram.

    Args:
        data: Parsed JSON payload.

    Returns:
        List of parsed Instagram posts.
    """
    return [
        p
        for node in _extract_web_edges(data)
        if (p := parse_web_profile_post_node(node)) is not None
    ]


def _parse_single_ld_script(content: str) -> ParsedInstagramPost | None:
    """Parse single ld+json script tag content."""
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError):
        return None

    if not isinstance(parsed, dict) or "articleBody" not in parsed:
        return None

    caption = str(parsed.get("articleBody", ""))
    pid = str(parsed.get("identifier", "ld_item"))
    atype = classify_announcement(caption)
    return ParsedInstagramPost(
        post_id=pid,
        shortcode=pid,
        caption=caption,
        url=str(parsed.get("url", DEFAULT_INSTAGRAM_URL)),
        announcement_type=atype,
        status_override=resolve_game_status_from_announcement(atype),
        metadata={"source": "html_ld_json"},
    )


def _extract_ld_json_items(soup: BeautifulSoup) -> list[ParsedInstagramPost]:
    """Extract posts from Schema.org ld+json script blocks."""
    return [
        p
        for tag in soup.find_all("script", type="application/ld+json")
        if (p := _parse_single_ld_script(tag.string or "")) is not None
    ]


def _extract_og_meta_url(soup: BeautifulSoup) -> str:
    """Extract OpenGraph URL or fallback to default."""
    tag = soup.find("meta", property="og:url")
    return str(tag["content"]) if tag and tag.get("content") else DEFAULT_INSTAGRAM_URL


def _extract_og_meta_item(soup: BeautifulSoup | None) -> ParsedInstagramPost | None:
    """Extract post description from OpenGraph meta tag."""
    if soup is None:
        return None

    meta_desc = soup.find("meta", property="og:description")
    if not meta_desc or not meta_desc.get("content"):
        return None

    caption = str(meta_desc["content"])
    atype = classify_announcement(caption)

    return ParsedInstagramPost(
        post_id="og_profile",
        shortcode="og_profile",
        caption=caption,
        url=_extract_og_meta_url(soup),
        announcement_type=atype,
        status_override=resolve_game_status_from_announcement(atype),
        metadata={"source": "html_og_meta"},
    )


def parse_html_instagram_feed(html_text: str) -> list[ParsedInstagramPost]:
    """Parse public HTML profile page for post descriptions and announcements.

    Args:
        html_text: Raw HTML page text.

    Returns:
        List of parsed Instagram posts.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    if ld_posts := _extract_ld_json_items(soup):
        return ld_posts

    og_post = _extract_og_meta_item(soup)
    return [og_post] if og_post is not None else []


def _is_same_calendar_day(dt1: datetime, dt2: datetime) -> bool:
    """Check if two UTC datetimes fall on the same local date."""
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    return dt1.astimezone(tz).date() == dt2.astimezone(tz).date()


def _is_opponent_match(game_opp: str, post_opp: str) -> bool:
    """Check if post opponent matches game opponent."""
    norm_game = normalize_team_name(game_opp).lower()
    norm_post = normalize_team_name(post_opp).lower()
    return norm_game in norm_post or norm_post in norm_game


def _matches_post_opponent(game: GameModel, post: ParsedInstagramPost) -> bool:
    """Check whether game and post opponents correspond."""
    if not post.opponent_name:
        return True

    opp = (
        game.away_team.name
        if _contains_ecu(game.home_team.name)
        else game.home_team.name
    )
    return _is_opponent_match(opp, post.opponent_name)


def _matches_post_timing(game: GameModel, post: ParsedInstagramPost) -> bool:
    """Check whether game timing aligns with post date or publish timestamp."""
    if post.game_datetime:
        return _is_same_calendar_day(game.start_time, post.game_datetime)

    if post.game_date:
        tz = ZoneInfo(DEFAULT_TIMEZONE)
        return game.start_time.astimezone(tz).date() == post.game_date

    urgent_types = {
        AnnouncementType.GAME_DAY,
        AnnouncementType.TIME_CHANGE,
        AnnouncementType.CANCELLATION,
    }
    if post.published_at and post.announcement_type in urgent_types:
        return _is_same_calendar_day(game.start_time, post.published_at)

    return False


def matches_post_to_game(game: GameModel, post: ParsedInstagramPost) -> bool:
    """Determine if an Instagram announcement corresponds to a GameModel.

    Args:
        game: GameModel entity from database.
        post: Parsed Instagram social post.

    Returns:
        True if announcement matches game opponent and timing.
    """
    if not _matches_post_opponent(game, post):
        return False

    return _matches_post_timing(game, post)


_matches_post_to_game = matches_post_to_game


def _update_game_time_from_post(
    game: GameModel,
    post: ParsedInstagramPost,
) -> bool:
    """Update game start time and duration if post provides a new time."""
    if not post.game_time or post.announcement_type != AnnouncementType.TIME_CHANGE:
        return False

    tz = ZoneInfo(DEFAULT_TIMEZONE)
    cur_date = game.start_time.astimezone(tz).date()
    new_start = datetime.combine(cur_date, post.game_time, tzinfo=tz).astimezone(UTC)
    if game.start_time != new_start:
        dur = game.end_time - game.start_time if game.end_time else timedelta(hours=2.5)
        game.start_time = new_start
        game.end_time = new_start + dur
        return True

    return False


def _update_game_status_from_post(
    game: GameModel,
    post: ParsedInstagramPost,
) -> bool:
    """Update game lifecycle status if post provides a status override."""
    if not post.status_override or game.status == post.status_override.value:
        return False

    game.status = post.status_override.value
    return True


def _apply_announcement_to_game(
    game: GameModel,
    post: ParsedInstagramPost,
) -> bool:
    """Apply announcement updates to a GameModel entity."""
    changed = _update_game_status_from_post(game, post)
    if _update_game_time_from_post(game, post):
        changed = True

    if post.venue and game.venue in {"", "TBD"} and post.venue not in {"", "TBD"}:
        game.venue = post.venue
        changed = True

    return changed


def _cross_reference_single_game(
    game: GameModel,
    posts: Sequence[ParsedInstagramPost],
) -> bool:
    """Cross-reference single game against all Instagram posts."""
    matched = False
    for post in posts:
        if _matches_post_to_game(game, post) and _apply_announcement_to_game(
            game,
            post,
        ):
            matched = True

    return matched


def cross_reference_announcements_with_games(
    games: Sequence[GameModel],
    posts: Sequence[ParsedInstagramPost],
) -> list[GameModel]:
    """Cross-reference Instagram announcements against scheduled games.

    Args:
        games: Sequence of GameModel instances.
        posts: Ingested Instagram posts.

    Returns:
        List of modified GameModel entities.
    """
    return [game for game in games if _cross_reference_single_game(game, posts)]


__all__ = [
    "DEFAULT_GRAPH_API_URL",
    "DEFAULT_INSTAGRAM_URL",
    "DEFAULT_INSTAGRAM_USERNAME",
    "DEFAULT_WEB_PROFILE_URL",
    "IG_APP_ID",
    "MONTH_MAP",
    "AnnouncementType",
    "ParsedInstagramPost",
    "build_game_datetime",
    "classify_announcement",
    "cross_reference_announcements_with_games",
    "extract_date_from_caption",
    "extract_opponent_from_caption",
    "extract_time_from_caption",
    "extract_venue_from_caption",
    "matches_post_to_game",
    "parse_graph_api_media_item",
    "parse_graph_api_response",
    "parse_html_instagram_feed",
    "parse_public_feed_json",
    "parse_web_profile_post_node",
    "resolve_game_status_from_announcement",
]

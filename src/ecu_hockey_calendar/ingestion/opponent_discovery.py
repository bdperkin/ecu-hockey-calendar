"""Opponent website discovery and schedule feed auto-detection engine.

Spiders target club hockey websites to discover schedule feeds (iCal, JSON, HTML),
home venues, canonical institution names, team aliases, and website metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from ecu_hockey_calendar.ingestion.client import ResilientHttpClient
from ecu_hockey_calendar.ingestion.normalizer import normalize_team_name
from ecu_hockey_calendar.ingestion.opponent_config import (
    OpponentConfigError,
    OpponentDirectory,
    OpponentEndpointConfig,
    OpponentFeedType,
)

if TYPE_CHECKING:
    from pathlib import Path


class ConfidenceLevel(StrEnum):
    """Confidence rating for auto-detected opponent configuration attributes."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# Minimum length thresholds
MIN_NAME_LENGTH = 3
MIN_VENUE_LENGTH = 4
MIN_INITIALS_LENGTH = 2
MIN_ALIAS_LENGTH = 3

# Common static asset extensions to avoid spidering
_STATIC_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".pdf",
    ".mp4",
    ".zip",
    ".css",
    ".js",
    ".woff",
    ".woff2",
)

# Known collegiate nicknames and mascots for alias generation
_KNOWN_MASCOTS: dict[str, tuple[str, ...]] = {
    "NC State University": ("nc state", "ncstate", "icepack", "pack", "wolfpack"),
    "UNC Chapel Hill": ("unc", "north carolina", "tar heels"),
    "UNC Wilmington": ("uncw", "wilmington", "seahawks"),
    "UNC Charlotte": ("uncc", "charlotte", "49ers"),
    "Appalachian State University": ("app state", "appalachian", "mountaineers"),
    "Virginia Tech": ("vt", "virginia tech", "hokies"),
    "Wake Forest University": ("wake forest", "demon deacons", "deacons"),
    "Duke University": ("duke", "blue devils"),
    "Elon University": ("elon", "phoenix"),
    "High Point University": ("hpu", "high point", "panthers"),
    "Clemson University": ("clemson", "tigers"),
    "Georgia Tech": ("ga tech", "georgia tech", "yellow jackets"),
    "University of Virginia": ("uva", "virginia", "cavaliers"),
    "University of Richmond": ("richmond", "spiders"),
    "James Madison University": ("jmu", "dukes"),
    "Rowan University": ("rowan", "profs"),
    "Georgetown University": ("georgetown", "hoyas"),
    "University of Alabama": ("alabama", "crimson tide", "bama"),
}

# Venue keyword indicators
_VENUE_SUFFIXES = (
    "Arena",
    "Center",
    "Centre",
    "Sportsplex",
    "Rink",
    "Coliseum",
    "House",
    "Complex",
    "Park",
)

_SCORE_RULES: tuple[tuple[tuple[str, ...], int], ...] = (
    (("schedule", "calendar", "events", "games"), 10),
    (("rink", "facility", "arena", "venue", "location"), 5),
    (("about", "tickets", "info", "contact", "team"), 2),
)

_DEFAULT_DIVISION = "ACHA M2"
_DEFAULT_CONFERENCE = "ACCHL"
_DEFAULT_MAX_PAGES = 10


def normalize_discovery_url(url: str) -> str:
    """Normalize input URL with https scheme and clean trailing slash."""
    raw = url.strip()
    if not raw:
        return ""

    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    scheme = "https" if parsed.scheme == "webcal" else parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") if parsed.path != "/" else ""
    return f"{scheme}://{netloc}{path}"


def get_root_domain(netloc: str) -> str:
    """Extract root domain without port and leading www."""
    host = netloc.split(":", maxsplit=1)[0].lower()
    return host.removeprefix("www.")


def is_internal_url(url: str, root_domain: str) -> bool:
    """Check if URL belongs to target root domain and is not static asset."""
    parsed = urlparse(url)
    if not parsed.netloc:
        return True

    if get_root_domain(parsed.netloc) != root_domain:
        return False

    return not parsed.path.lower().endswith(_STATIC_EXTENSIONS)


def _matches_keywords(text: str, keywords: tuple[str, ...]) -> bool:
    """Check if any keyword substring is present in text."""
    return any(kw in text for kw in keywords)


def score_link_relevance(path_or_url: str) -> int:
    """Calculate spidering priority score based on path keywords."""
    lowered = path_or_url.lower()
    for keywords, score in _SCORE_RULES:
        if _matches_keywords(lowered, keywords):
            return score

    return 0


def _extract_google_cal_id(parsed_qs: dict[str, list[str]]) -> str | None:
    """Extract and validate calendar ID from query parameters."""
    src = parsed_qs.get("src", [""])[0]
    return src or None


def extract_google_calendar_feed(url: str) -> str | None:
    """Convert Google Calendar embed or view URL to direct public iCal URL."""
    parsed = urlparse(url)
    if parsed.netloc.lower() not in (
        "calendar.google.com",
        "www.calendar.google.com",
    ):
        return None

    if "/calendar/ical/" in parsed.path and parsed.path.endswith(".ics"):
        return url

    qs = parse_qs(parsed.query)
    cal_id = _extract_google_cal_id(qs)
    if not cal_id:
        return None

    return f"https://calendar.google.com/calendar/ical/{cal_id}/public/basic.ics"


def _extract_tag_href(tag: Tag | BeautifulSoup) -> str | None:
    """Extract first non-empty href or src attribute value."""
    for attr in ("href", "src"):
        val = tag.get(attr)
        if isinstance(val, str) and val.strip():
            return val.strip()

    return None


def _resolve_feed_href(href: str, base_url: str) -> str | None:
    """Resolve raw link string into canonical feed URL if recognized."""
    gcal = extract_google_calendar_feed(href)
    if gcal:
        return gcal

    if href.startswith("webcal://"):
        return href.replace("webcal://", "https://", 1)

    if href.endswith(".ics") or "format=ical" in href:
        return urljoin(base_url, href)

    return None


def extract_ical_link_from_element(
    tag: Tag | BeautifulSoup,
    base_url: str,
) -> str | None:
    """Extract potential iCal or webcal URL from HTML tag."""
    href = _extract_tag_href(tag)
    if not href:
        return None

    return _resolve_feed_href(href, base_url)


def _find_ical_feed(soup: BeautifulSoup, page_url: str) -> str | None:
    """Scan HTML elements for iCal feed links."""
    for tag in soup.find_all(["a", "link", "iframe"]):
        ical = extract_ical_link_from_element(tag, page_url)
        if ical:
            return ical

    return None


def _find_json_feed(soup: BeautifulSoup, page_url: str) -> str | None:
    """Scan HTML elements for JSON schedule endpoints."""
    for tag in soup.find_all(["a", "link"]):
        href = tag.get("href", "")
        if isinstance(href, str) and (
            "feed=modulekit" in href or "/api/schedule" in href
        ):
            return urljoin(page_url, href)

    return None


def _is_html_schedule_page(soup: BeautifulSoup, page_url: str) -> bool:
    """Check if page represents an HTML schedule with table elements."""
    if "schedule" not in page_url.lower():
        return False

    return soup.find(["table", "tbody"]) is not None


def extract_schedule_feed(
    soup: BeautifulSoup,
    page_url: str,
) -> tuple[str | None, OpponentFeedType | None]:
    """Inspect page elements for iCal, JSON, or HTML schedule feeds."""
    ical = _find_ical_feed(soup, page_url)
    if ical:
        return ical, OpponentFeedType.ICAL

    json_feed = _find_json_feed(soup, page_url)
    if json_feed:
        return json_feed, OpponentFeedType.JSON

    if _is_html_schedule_page(soup, page_url):
        return page_url, OpponentFeedType.HTML

    return None, None


def _clean_raw_team_title(text: str) -> str:
    """Remove boilerplate suffixes and descriptors from team title text."""
    pattern = (
        r"\s*[-|\u2013\u2014]\s*"
        r"(?:Home|Official Website|Official Site|Schedule|Calendar).*$"
    )
    cleaned = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
    return re.sub(
        r"\s*(?:Men's Ice Hockey|Club Hockey|Ice Hockey Club|Hockey Club|"
        r"Ice Hockey Team|Ice Hockey|Club Team|Hockey)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()


def _extract_og_site_name(soup: BeautifulSoup) -> str | None:
    """Extract OpenGraph og:site_name metadata."""
    og_name = soup.find("meta", property="og:site_name")
    if og_name and og_name.get("content"):
        return _clean_raw_team_title(str(og_name["content"]))

    return None


def _extract_title_text(soup: BeautifulSoup) -> str | None:
    """Extract HTML document title text."""
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text():
        return _clean_raw_team_title(title_tag.get_text())

    return None


def _extract_h1_text(soup: BeautifulSoup) -> str | None:
    """Extract first top-level header h1 text."""
    h1_tag = soup.find("h1")
    if h1_tag and h1_tag.get_text():
        return _clean_raw_team_title(h1_tag.get_text())

    return None


def _extract_name_from_headings(soup: BeautifulSoup) -> str | None:
    """Extract team candidate text from page title, meta, or h1 tags."""
    return (
        _extract_og_site_name(soup)
        or _extract_title_text(soup)
        or _extract_h1_text(soup)
    )


def _match_known_mascot(text: str) -> str | None:
    """Check if text contains any known collegiate mascot or alias."""
    lowered = text.lower()
    for canonical_name, mascots in _KNOWN_MASCOTS.items():
        if any(re.search(rf"\b{re.escape(m)}\b", lowered) for m in mascots):
            return canonical_name

    return None


def _classify_markup_candidate(
    candidate: str,
) -> tuple[str, ConfidenceLevel] | None:
    """Classify confidence level of candidate name extracted from markup."""
    normalized = normalize_team_name(candidate)
    if normalized and normalized != candidate:
        return normalized, ConfidenceLevel.HIGH

    mascot_match = _match_known_mascot(candidate)
    if mascot_match:
        return mascot_match, ConfidenceLevel.HIGH

    if len(candidate) >= MIN_NAME_LENGTH:
        return candidate, ConfidenceLevel.MEDIUM

    return None


def _detect_name_from_markup(
    soup: BeautifulSoup,
) -> tuple[str, ConfidenceLevel] | None:
    """Detect name candidate from HTML markup."""
    candidate = _extract_name_from_headings(soup)
    return _classify_markup_candidate(candidate) if candidate else None


def _classify_domain_cleaned(cleaned: str) -> tuple[str, ConfidenceLevel]:
    """Classify confidence level of domain-derived team candidate."""
    mascot_match = _match_known_mascot(cleaned)
    if mascot_match:
        return mascot_match, ConfidenceLevel.MEDIUM

    normalized = normalize_team_name(cleaned)
    if normalized and normalized != cleaned:
        return normalized, ConfidenceLevel.MEDIUM

    return cleaned, ConfidenceLevel.LOW


def _detect_name_from_domain(
    base_url: str,
) -> tuple[str, ConfidenceLevel]:
    """Derive fallback name candidate from domain host."""
    parsed = urlparse(base_url)
    slug = get_root_domain(parsed.netloc).split(".")[0]
    cleaned = slug.replace("hockey", "").replace("-", " ").title().strip()
    if cleaned:
        return _classify_domain_cleaned(cleaned)

    return "Unknown Opponent", ConfidenceLevel.LOW


def detect_canonical_name(
    soup: BeautifulSoup,
    base_url: str,
) -> tuple[str, ConfidenceLevel]:
    """Detect canonical institution name from HTML structure and normalizer."""
    markup_res = _detect_name_from_markup(soup)
    if markup_res is not None:
        return markup_res

    return _detect_name_from_domain(base_url)


def _extract_venue_from_regex(text: str) -> str | None:
    """Find venue string matching home rink label regex."""
    pattern = (
        r"(?:Home Rink|Home Arena|Home Venue|Facility|Arena|Rink|"
        r"Home Games Played At|Games Played At)[:\s]+"
        r"([A-Z0-9][A-Za-z0-9\s&',.\-\u2013]+?(?:" + "|".join(_VENUE_SUFFIXES) + r"))"
    )
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return str(match.group(1)).strip()

    return None


def _extract_venue_from_headings(soup: BeautifulSoup) -> str | None:
    """Check headings for arena/rink facility names."""
    for tag in soup.find_all(["h1", "h2", "h3", "strong"]):
        txt = tag.get_text().strip()
        if (
            any(txt.endswith(sfx) for sfx in _VENUE_SUFFIXES)
            and len(txt) >= MIN_VENUE_LENGTH
        ):
            return txt

    return None


def detect_home_venue(
    soup: BeautifulSoup,
    page_text: str,
) -> tuple[str, ConfidenceLevel]:
    """Detect home arena or facility from page text and headings."""
    regex_venue = _extract_venue_from_regex(page_text)
    if regex_venue:
        return regex_venue, ConfidenceLevel.HIGH

    heading_venue = _extract_venue_from_headings(soup)
    if heading_venue:
        return heading_venue, ConfidenceLevel.MEDIUM

    return "TBD", ConfidenceLevel.LOW


def _generate_initials(name: str) -> str:
    """Generate acronym initials from multi-word institution name."""
    words = [w for w in name.split() if w.lower() not in ("of", "at", "the", "and")]
    return "".join(w[0] for w in words).lower()


def _detect_known_aliases(
    canonical_name: str,
) -> tuple[tuple[str, ...], ConfidenceLevel] | None:
    """Look up known collegiate mascot and alias mappings."""
    if canonical_name in _KNOWN_MASCOTS:
        return _KNOWN_MASCOTS[canonical_name], ConfidenceLevel.HIGH

    return None


def _add_institutional_aliases(canonical_name: str, aliases: set[str]) -> None:
    """Add acronym and stripped name variants to alias set."""
    initials = _generate_initials(canonical_name)
    if len(initials) >= MIN_INITIALS_LENGTH:
        aliases.add(initials)

    clean_short = (
        canonical_name.replace("University", "").replace("College", "").strip().lower()
    )
    if clean_short and clean_short != canonical_name.lower():
        aliases.add(clean_short)


def _add_domain_aliases(base_url: str, aliases: set[str]) -> None:
    """Add domain prefix slug to alias set."""
    parsed = urlparse(base_url)
    slug = (
        get_root_domain(parsed.netloc)
        .split(".")[0]
        .replace("hockey", "")
        .strip()
        .lower()
    )
    if len(slug) >= MIN_ALIAS_LENGTH:
        aliases.add(slug)


def _add_title_aliases(page_title: str, aliases: set[str]) -> None:
    """Extract individual mascot/brand words from page title."""
    for word in page_title.split():
        clean_word = re.sub(r"[^\w]", "", word).lower()
        if len(clean_word) >= MIN_ALIAS_LENGTH and clean_word not in (
            "home",
            "site",
            "official",
            "ice",
            "hockey",
            "page",
        ):
            aliases.add(clean_word)


def detect_aliases(
    canonical_name: str,
    base_url: str,
    page_title: str,
) -> tuple[tuple[str, ...], ConfidenceLevel]:
    """Generate search and matching aliases for detected opponent."""
    known = _detect_known_aliases(canonical_name)
    if known is not None:
        return known

    aliases_set: set[str] = set()
    _add_institutional_aliases(canonical_name, aliases_set)
    _add_domain_aliases(base_url, aliases_set)
    _add_title_aliases(page_title, aliases_set)

    ordered = tuple(sorted(aliases_set))
    return ordered, ConfidenceLevel.MEDIUM if ordered else ConfidenceLevel.LOW


@dataclass(frozen=True)
class DiscoveredOpponent:
    """Structured opponent configuration discovered by spidering target website."""

    canonical_name: str
    feed_url: str
    feed_type: OpponentFeedType
    home_venue: str = "TBD"
    division: str = _DEFAULT_DIVISION
    conference: str = _DEFAULT_CONFERENCE
    aliases: tuple[str, ...] = ()
    website: str | None = None
    enabled: bool = True
    confidence_scores: dict[str, ConfidenceLevel] = field(default_factory=dict)
    pages_crawled: tuple[str, ...] = ()

    def overall_confidence(self) -> ConfidenceLevel:
        """Calculate overall confidence level based on key fields."""
        scores = [
            self.confidence_scores.get("canonical_name", ConfidenceLevel.LOW),
            self.confidence_scores.get("feed_url", ConfidenceLevel.LOW),
            self.confidence_scores.get("home_venue", ConfidenceLevel.LOW),
        ]
        if all(s == ConfidenceLevel.HIGH for s in scores[:2]):
            return ConfidenceLevel.HIGH

        if any(s == ConfidenceLevel.LOW for s in scores[:2]):
            return ConfidenceLevel.LOW

        return ConfidenceLevel.MEDIUM

    def to_endpoint_config(self) -> OpponentEndpointConfig:
        """Convert discovered opponent into valid OpponentEndpointConfig entity."""
        return OpponentEndpointConfig(
            canonical_name=self.canonical_name,
            feed_url=self.feed_url,
            feed_type=self.feed_type,
            home_venue=self.home_venue,
            division=self.division,
            conference=self.conference,
            aliases=self.aliases,
            website=self.website,
            enabled=self.enabled,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert discovered opponent to structured dictionary."""
        return {
            "canonical_name": self.canonical_name,
            "feed_url": self.feed_url,
            "feed_type": self.feed_type.value,
            "home_venue": self.home_venue,
            "division": self.division,
            "conference": self.conference,
            "aliases": list(self.aliases),
            "website": self.website,
            "enabled": self.enabled,
            "confidence": {k: v.value for k, v in self.confidence_scores.items()},
            "overall_confidence": self.overall_confidence().value,
            "pages_crawled": list(self.pages_crawled),
        }

    def to_yaml_snippet(self) -> str:
        """Format candidate opponent configuration as clean YAML snippet."""
        alias_repr = f"[{', '.join(self.aliases)}]" if self.aliases else "[]"
        web_repr = self.website or self.feed_url
        return (
            f"  - canonical_name: {self.canonical_name}\n"
            f"    feed_url: {self.feed_url}\n"
            f"    feed_type: {self.feed_type.value}\n"
            f"    home_venue: {self.home_venue}\n"
            f"    division: {self.division}\n"
            f"    conference: {self.conference}\n"
            f"    aliases: {alias_repr}\n"
            f"    website: {web_repr}\n"
            f"    enabled: {'true' if self.enabled else 'false'}"
        )


def _clean_internal_link(
    href: str,
    current_url: str,
    root_domain: str,
) -> str | None:
    """Validate and clean internal link target string."""
    clean = href.strip()
    if not clean or clean.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None

    resolved = urljoin(current_url, clean)
    if not is_internal_url(resolved, root_domain):
        return None

    return resolved.split("#")[0]


def _collect_page_links(
    soup: BeautifulSoup,
    current_url: str,
    root_domain: str,
) -> list[str]:
    """Collect internal navigation link targets from page."""
    candidates: list[str] = []
    for tag in soup.find_all("a"):
        href = tag.get("href")
        if isinstance(href, str):
            clean = _clean_internal_link(href, current_url, root_domain)
            if clean:
                candidates.append(clean)

    return candidates


def _sort_links_by_priority(links: list[str]) -> list[str]:
    """Sort links by score descending preserving encounter order."""
    return sorted(links, key=score_link_relevance, reverse=True)


@dataclass
class _SpiderState:
    """Internal state tracking during website spider traversal."""

    visited: set[str] = field(default_factory=set)
    pages_crawled: list[str] = field(default_factory=list)
    best_name: tuple[str, ConfidenceLevel] = (
        "Unknown Opponent",
        ConfidenceLevel.LOW,
    )
    best_feed: tuple[
        str | None,
        OpponentFeedType | None,
        ConfidenceLevel,
    ] = (None, None, ConfidenceLevel.LOW)
    best_venue: tuple[str, ConfidenceLevel] = ("TBD", ConfidenceLevel.LOW)
    best_title: str = ""


class OpponentDiscoverySpider:
    """Crawler that spiders opponent websites and detects schedule configuration."""

    def __init__(
        self,
        client: ResilientHttpClient | None = None,
        max_pages: int = _DEFAULT_MAX_PAGES,
    ) -> None:
        """Initialize discovery spider.

        Args:
            client: Optional HTTP client override.
            max_pages: Maximum number of pages to spider within target domain.
        """
        self.client = client or ResilientHttpClient()
        self.max_pages = max(1, max_pages)

    async def _fetch_page_safely(self, url: str) -> tuple[str, str]:
        """Fetch page text and content hash or empty on error."""
        try:
            return await self.client.fetch_text(url)
        except (httpx.HTTPError, OSError, ValueError):
            return "", ""

    def _process_page_feed(
        self,
        soup: BeautifulSoup,
        url: str,
        best_feed: tuple[str | None, OpponentFeedType | None, ConfidenceLevel],
    ) -> tuple[str | None, OpponentFeedType | None, ConfidenceLevel]:
        """Check page for feed candidates and update best feed."""
        f_url, f_type = extract_schedule_feed(soup, url)
        if f_url and f_type:
            if f_type in (OpponentFeedType.ICAL, OpponentFeedType.JSON):
                return f_url, f_type, ConfidenceLevel.HIGH

            if best_feed[0] is None:
                return f_url, f_type, ConfidenceLevel.MEDIUM

        return best_feed

    def _process_page_venue(
        self,
        soup: BeautifulSoup,
        html: str,
        best_venue: tuple[str, ConfidenceLevel],
    ) -> tuple[str, ConfidenceLevel]:
        """Check page for venue candidates and update best venue."""
        if best_venue[1] == ConfidenceLevel.HIGH:
            return best_venue

        v_name, v_conf = detect_home_venue(soup, html)
        if v_conf == ConfidenceLevel.HIGH:
            return v_name, v_conf

        if v_name != "TBD" and best_venue[0] == "TBD":
            return v_name, v_conf

        return best_venue

    def _update_candidate_name(
        self,
        soup: BeautifulSoup,
        url: str,
        norm_base: str,
        state: _SpiderState,
    ) -> None:
        """Update candidate canonical name if priority condition is met."""
        if url != norm_base and state.best_name[1] != ConfidenceLevel.LOW:
            return

        cand_name, cand_conf = detect_canonical_name(soup, norm_base)
        if cand_conf != ConfidenceLevel.LOW:
            state.best_name = (cand_name, cand_conf)

    def _update_page_state(
        self,
        soup: BeautifulSoup,
        html: str,
        url: str,
        norm_base: str,
        state: _SpiderState,
    ) -> None:
        """Inspect fetched page and update spider state."""
        state.pages_crawled.append(url)
        if not state.best_title and soup.title:
            state.best_title = soup.title.get_text()

        self._update_candidate_name(soup, url, norm_base, state)
        state.best_feed = self._process_page_feed(soup, url, state.best_feed)
        state.best_venue = self._process_page_venue(soup, html, state.best_venue)

    def _enqueue_new_links(
        self,
        soup: BeautifulSoup,
        url: str,
        root_domain: str,
        queue: list[str],
        visited: set[str],
    ) -> None:
        """Collect and sort new unvisited links to queue."""
        new_links = _collect_page_links(soup, url, root_domain)
        for link in _sort_links_by_priority(new_links):
            if link not in visited and link not in queue:
                queue.append(link)

    def _build_discovered_result(
        self,
        state: _SpiderState,
        norm_base: str,
        division: str,
        conference: str,
        *,
        enabled: bool,
    ) -> DiscoveredOpponent:
        """Assemble DiscoveredOpponent from spider state."""
        best_name = state.best_name
        if best_name[0] == "Unknown Opponent":
            best_name = _detect_name_from_domain(norm_base)

        resolved_feed_url = state.best_feed[0] or norm_base
        resolved_feed_type = state.best_feed[1] or OpponentFeedType.HTML
        aliases, alias_conf = detect_aliases(
            best_name[0],
            norm_base,
            state.best_title,
        )
        confidence_map = {
            "canonical_name": best_name[1],
            "feed_url": state.best_feed[2],
            "feed_type": state.best_feed[2],
            "home_venue": state.best_venue[1],
            "aliases": alias_conf,
            "website": ConfidenceLevel.HIGH,
        }
        return DiscoveredOpponent(
            canonical_name=best_name[0],
            feed_url=resolved_feed_url,
            feed_type=resolved_feed_type,
            home_venue=state.best_venue[0],
            division=division,
            conference=conference,
            aliases=aliases,
            website=norm_base,
            enabled=enabled,
            confidence_scores=confidence_map,
            pages_crawled=tuple(state.pages_crawled),
        )

    async def discover(
        self,
        base_url: str,
        *,
        division: str = _DEFAULT_DIVISION,
        conference: str = _DEFAULT_CONFERENCE,
        enabled: bool = True,
    ) -> DiscoveredOpponent:
        """Spider target opponent website and auto-detect schedule configuration.

        Args:
            base_url: Opponent website entry point URL.
            division: Target division string.
            conference: Target conference string.
            enabled: Initial enabled state.

        Returns:
            Populated DiscoveredOpponent instance.
        """
        norm_base = normalize_discovery_url(base_url)
        parsed_base = urlparse(norm_base)
        root_domain = get_root_domain(parsed_base.netloc)

        queue: list[str] = [norm_base]
        state = _SpiderState()

        while queue and len(state.visited) < self.max_pages:
            url = queue.pop(0)
            if url in state.visited:
                continue

            state.visited.add(url)
            html, _ = await self._fetch_page_safely(url)
            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")
            self._update_page_state(soup, html, url, norm_base, state)
            self._enqueue_new_links(soup, url, root_domain, queue, state.visited)

        return self._build_discovered_result(
            state,
            norm_base,
            division,
            conference,
            enabled=enabled,
        )


def append_opponent_to_yaml_file(
    filepath: Path,
    opponent: DiscoveredOpponent,
) -> None:
    """Append candidate opponent configuration to existing or new YAML file.

    Args:
        filepath: Target YAML file path.
        opponent: Discovered opponent candidate configuration.

    Raises:
        OpponentConfigError: If opponent already exists in configuration file.
    """
    if filepath.is_file():
        existing_dir = OpponentDirectory.from_yaml(filepath)
        if opponent.canonical_name in existing_dir:
            msg = (
                f"Opponent '{opponent.canonical_name}' already exists "
                f"in configuration file: {filepath}"
            )
            raise OpponentConfigError(msg)

        content = filepath.read_text(encoding="utf-8")
        if not content.endswith("\n"):
            content += "\n"

        content += opponent.to_yaml_snippet() + "\n"
        filepath.write_text(content, encoding="utf-8")
    else:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        content = "---\nopponents:\n" + opponent.to_yaml_snippet() + "\n"
        filepath.write_text(content, encoding="utf-8")

    # Validate output schema consistency
    OpponentDirectory.from_yaml(filepath)

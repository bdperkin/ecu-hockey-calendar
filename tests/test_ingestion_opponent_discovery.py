# pylint: disable=too-many-lines,too-many-public-methods,protected-access
"""Tests for the opponent discovery engine and spider.

Covers URL normalization, feed extraction (iCal, JSON, HTML), Google Calendar
embed parsing, canonical name detection, venue extraction, alias generation,
spider traversal, and YAML persistence.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from bs4 import BeautifulSoup

from ecu_hockey_calendar.ingestion.opponent_config import (
    OpponentConfigError,
    OpponentDirectory,
    OpponentFeedType,
)
from ecu_hockey_calendar.ingestion.opponent_discovery import (
    ConfidenceLevel,
    DiscoveredOpponent,
    OpponentDiscoverySpider,
    _add_domain_aliases,
    _add_institutional_aliases,
    _add_title_aliases,
    _clean_internal_link,
    _clean_raw_team_title,
    _collect_page_links,
    _detect_name_from_domain,
    _detect_name_from_markup,
    _extract_google_cal_id,
    _extract_h1_text,
    _extract_og_site_name,
    _extract_tag_href,
    _extract_title_text,
    _extract_venue_from_headings,
    _extract_venue_from_regex,
    _generate_initials,
    _is_html_schedule_page,
    _resolve_feed_href,
    _sort_links_by_priority,
    _SpiderState,
    append_opponent_to_yaml_file,
    detect_aliases,
    detect_canonical_name,
    detect_home_venue,
    extract_google_calendar_feed,
    extract_ical_link_from_element,
    extract_schedule_feed,
    get_root_domain,
    is_internal_url,
    normalize_discovery_url,
    score_link_relevance,
)


class TestUrlHelpers:
    """Tests for URL normalization and domain extraction utilities."""

    def test_normalize_discovery_url_empty(self) -> None:
        """Verify empty or whitespace strings return empty string."""
        assert normalize_discovery_url("") == ""
        assert normalize_discovery_url("   \n\t") == ""

    def test_normalize_discovery_url_no_scheme(self) -> None:
        """Verify URL missing scheme gets https prepended."""
        url = normalize_discovery_url("ncstatehockey.com")
        assert url == "https://ncstatehockey.com"

    def test_normalize_discovery_url_webcal(self) -> None:
        """Verify webcal scheme is normalized to https."""
        url = normalize_discovery_url("webcal://example.com/calendar.ics")
        assert url == "https://example.com/calendar.ics"

    def test_normalize_discovery_url_trailing_slash_and_case(self) -> None:
        """Verify trailing slash removal and lowercase netloc."""
        url = normalize_discovery_url("HTTPS://EXAMPLE.COM/schedule/")
        assert url == "https://example.com/schedule"

    def test_normalize_discovery_url_root_path(self) -> None:
        """Verify root path slash is stripped."""
        url = normalize_discovery_url("https://example.com/")
        assert url == "https://example.com"

    def test_get_root_domain(self) -> None:
        """Verify extraction of root domain without port and www."""
        assert get_root_domain("www.ncstatehockey.com") == "ncstatehockey.com"
        assert get_root_domain("ncstatehockey.com:8080") == "ncstatehockey.com"
        assert get_root_domain("icepack.com") == "icepack.com"

    def test_is_internal_url_relative(self) -> None:
        """Verify relative URLs are considered internal."""
        assert is_internal_url("/schedule", "example.com") is True

    def test_is_internal_url_external(self) -> None:
        """Verify URLs with different domain are not internal."""
        assert is_internal_url("https://other.com/schedule", "example.com") is False

    def test_is_internal_url_matching_domain(self) -> None:
        """Verify URLs with matching root domain are internal."""
        assert (
            is_internal_url("https://www.example.com/schedule", "example.com") is True
        )

    def test_is_internal_url_static_asset(self) -> None:
        """Verify static image/asset URLs are excluded."""
        assert is_internal_url("https://example.com/logo.png", "example.com") is False
        assert is_internal_url("https://example.com/doc.pdf", "example.com") is False
        assert is_internal_url("https://example.com/font.woff2", "example.com") is False

    def test_score_link_relevance(self) -> None:
        """Verify priority scoring based on link path keywords."""
        assert score_link_relevance("/team/schedule") == 10
        assert score_link_relevance("/calendar/2026") == 10
        assert score_link_relevance("/rink-directions") == 5
        assert score_link_relevance("/facility/arena") == 5
        assert score_link_relevance("/about-the-pack") == 2
        assert score_link_relevance("/tickets/buy") == 2
        assert score_link_relevance("/news/blog-post") == 0


class TestFeedExtraction:
    """Tests for schedule feed extraction (iCal, JSON, Google Calendar)."""

    def test_extract_google_calendar_feed_not_google(self) -> None:
        """Verify non-Google calendar URLs return None."""
        assert extract_google_calendar_feed("https://example.com/cal") is None

    def test_extract_google_calendar_feed_direct_ics(self) -> None:
        """Verify direct Google Calendar .ics URL is preserved."""
        url = "https://calendar.google.com/calendar/ical/test%40group.calendar.google.com/public/basic.ics"
        assert extract_google_calendar_feed(url) == url

    def test_extract_google_calendar_feed_embed(self) -> None:
        """Verify Google Calendar embed URL is converted to public iCal URL."""
        embed = (
            "https://calendar.google.com/calendar/embed?"
            "src=test%40gmail.com&ctz=America%2FNew_York"
        )
        expected = (
            "https://calendar.google.com/calendar/ical/test@gmail.com/public/basic.ics"
        )
        assert extract_google_calendar_feed(embed) == expected

    def test_extract_google_calendar_feed_missing_src(self) -> None:
        """Verify Google Calendar embed URL missing src returns None."""
        url = "https://calendar.google.com/calendar/embed?ctz=America%2FNew_York"
        assert extract_google_calendar_feed(url) is None

    def test_extract_google_cal_id_empty(self) -> None:
        """Verify _extract_google_cal_id with empty query."""
        assert _extract_google_cal_id({}) is None
        assert _extract_google_cal_id({"src": [""]}) is None

    def test_extract_tag_href(self) -> None:
        """Verify href and src attribute extraction from tags."""
        soup = BeautifulSoup(
            '<a href=" https://example.com ">Link</a>'
            '<iframe src="/frame"></iframe><div></div>',
            "html.parser",
        )
        a_tag = soup.find("a")
        iframe_tag = soup.find("iframe")
        div_tag = soup.find("div")
        assert a_tag is not None
        assert iframe_tag is not None
        assert div_tag is not None
        assert _extract_tag_href(a_tag) == "https://example.com"
        assert _extract_tag_href(iframe_tag) == "/frame"
        assert _extract_tag_href(div_tag) is None

    def test_resolve_feed_href_google_cal(self) -> None:
        """Verify google calendar embed resolution in _resolve_feed_href."""
        url = "https://calendar.google.com/calendar/embed?src=team%40gmail.com"
        res = _resolve_feed_href(url, "https://example.com")
        assert (
            res
            == "https://calendar.google.com/calendar/ical/team@gmail.com/public/basic.ics"
        )

    def test_resolve_feed_href_webcal(self) -> None:
        """Verify webcal:// link resolution to https."""
        res = _resolve_feed_href("webcal://example.com/cal.ics", "https://example.com")
        assert res == "https://example.com/cal.ics"

    def test_resolve_feed_href_ics_relative(self) -> None:
        """Verify relative .ics link resolution."""
        res = _resolve_feed_href("schedule.ics", "https://example.com/team/")
        assert res == "https://example.com/team/schedule.ics"

    def test_resolve_feed_href_format_ical(self) -> None:
        """Verify format=ical query parameter link resolution."""
        res = _resolve_feed_href("events?format=ical", "https://example.com")
        assert res == "https://example.com/events?format=ical"

    def test_resolve_feed_href_unrecognized(self) -> None:
        """Verify unrecognized href returns None."""
        res = _resolve_feed_href("/roster", "https://example.com")
        assert res is None

    def test_extract_ical_link_from_element_empty(self) -> None:
        """Verify empty tag returns None."""
        soup = BeautifulSoup("<p>Text</p>", "html.parser")
        p_tag = soup.find("p")
        assert p_tag is not None
        assert extract_ical_link_from_element(p_tag, "https://example.com") is None

    def test_extract_schedule_feed_ical(self) -> None:
        """Verify detecting iCal feed from anchor tag."""
        html = '<div><a href="/calendar.ics">Download Calendar</a></div>'
        soup = BeautifulSoup(html, "html.parser")
        url, feed_type = extract_schedule_feed(soup, "https://example.com")
        assert url == "https://example.com/calendar.ics"
        assert feed_type == OpponentFeedType.ICAL

    def test_extract_schedule_feed_json(self) -> None:
        """Verify detecting JSON feed from modulekit or api link."""
        html = (
            '<div><a href="/index.php?feed=modulekit&type=schedule">API Feed</a></div>'
        )
        soup = BeautifulSoup(html, "html.parser")
        url, feed_type = extract_schedule_feed(soup, "https://example.com")
        assert url == "https://example.com/index.php?feed=modulekit&type=schedule"
        assert feed_type == OpponentFeedType.JSON

    def test_extract_schedule_feed_html(self) -> None:
        """Verify detecting HTML table schedule feed."""
        html = "<div><table><tr><td>Game 1</td></tr></table></div>"
        soup = BeautifulSoup(html, "html.parser")
        url, feed_type = extract_schedule_feed(soup, "https://example.com/schedule")
        assert url == "https://example.com/schedule"
        assert feed_type == OpponentFeedType.HTML

    def test_extract_schedule_feed_none(self) -> None:
        """Verify pages without schedule feeds return (None, None)."""
        html = "<div><p>Welcome to our team page</p></div>"
        soup = BeautifulSoup(html, "html.parser")
        url, feed_type = extract_schedule_feed(soup, "https://example.com/about")
        assert url is None
        assert feed_type is None

    def test_is_html_schedule_page_non_schedule_url(self) -> None:
        """Verify table on non-schedule page is not treated as HTML schedule feed."""
        html = "<table><tr><td>Roster</td></tr></table>"
        soup = BeautifulSoup(html, "html.parser")
        assert _is_html_schedule_page(soup, "https://example.com/roster") is False


class TestNameAndVenueDetection:
    """Tests for canonical institution name and home venue detection."""

    def test_clean_raw_team_title(self) -> None:
        """Verify title cleaning strips suffixes and boilerplate."""
        assert _clean_raw_team_title("NC State Icepack - Home") == "NC State Icepack"
        assert _clean_raw_team_title("ECU Club Hockey | Official Website") == "ECU"
        assert _clean_raw_team_title("UNC Men's Ice Hockey") == "UNC"

    def test_extract_og_site_name(self) -> None:
        """Verify OpenGraph site_name extraction."""
        html = '<meta property="og:site_name" content="NC State Icepack Hockey">'
        soup = BeautifulSoup(html, "html.parser")
        assert _extract_og_site_name(soup) == "NC State Icepack"

    def test_extract_og_site_name_missing(self) -> None:
        """Verify missing og:site_name returns None."""
        soup = BeautifulSoup("<html></html>", "html.parser")
        assert _extract_og_site_name(soup) is None

    def test_extract_title_text(self) -> None:
        """Verify title text extraction."""
        soup = BeautifulSoup("<title>Appalachian State Hockey</title>", "html.parser")
        assert _extract_title_text(soup) == "Appalachian State"

    def test_extract_title_text_missing(self) -> None:
        """Verify missing title returns None."""
        soup = BeautifulSoup("<html></html>", "html.parser")
        assert _extract_title_text(soup) is None

    def test_extract_h1_text(self) -> None:
        """Verify h1 text extraction."""
        soup = BeautifulSoup("<h1>Virginia Tech Ice Hockey</h1>", "html.parser")
        assert _extract_h1_text(soup) == "Virginia Tech"

    def test_extract_h1_text_missing(self) -> None:
        """Verify missing h1 returns None."""
        soup = BeautifulSoup("<html></html>", "html.parser")
        assert _extract_h1_text(soup) is None

    def test_detect_name_from_markup_normalized(self) -> None:
        """Verify normalizer promotion to HIGH confidence."""
        html = "<title>NC State Icepack</title>"
        soup = BeautifulSoup(html, "html.parser")
        res = _detect_name_from_markup(soup)
        assert res is not None
        name, conf = res
        assert name == "NC State University"
        assert conf == ConfidenceLevel.HIGH

    def test_detect_name_from_markup_unnormalized_valid(self) -> None:
        """Verify non-normalized candidate with length >= 3 returns MEDIUM."""
        html = "<title>Raleigh Red Wings Hockey Club</title>"
        soup = BeautifulSoup(html, "html.parser")
        res = _detect_name_from_markup(soup)
        assert res is not None
        name, conf = res
        assert name == "Raleigh Red Wings"
        assert conf == ConfidenceLevel.MEDIUM

    def test_detect_name_from_markup_too_short(self) -> None:
        """Verify candidate shorter than MIN_NAME_LENGTH returns None."""
        html = "<title>AB</title>"
        soup = BeautifulSoup(html, "html.parser")
        assert _detect_name_from_markup(soup) is None

    def test_detect_name_from_domain_normalized(self) -> None:
        """Verify domain fallback resolves via normalizer."""
        name, conf = _detect_name_from_domain("https://saint-thomas-hockey.com")
        assert name == "St. Thomas University"
        assert conf == ConfidenceLevel.MEDIUM

    def test_detect_name_from_domain_mascot(self) -> None:
        """Verify domain fallback resolves via mascot dictionary."""
        name, conf = _detect_name_from_domain("https://ncstatehockey.com")
        assert name == "NC State University"
        assert conf == ConfidenceLevel.MEDIUM

    def test_detect_name_from_domain_unnormalized(self) -> None:
        """Verify domain fallback for unrecognized domain."""
        name, conf = _detect_name_from_domain("https://raleighclubhockey.org")
        assert name == "Raleighclub"
        assert conf == ConfidenceLevel.LOW

    def test_detect_name_from_domain_empty(self) -> None:
        """Verify domain fallback when cleaned domain is empty."""
        name, conf = _detect_name_from_domain("https://hockey.com")
        assert name == "Unknown Opponent"
        assert conf == ConfidenceLevel.LOW

    def test_detect_canonical_name_markup_fallback(self) -> None:
        """Verify detect_canonical_name falls back to domain if markup empty."""
        soup = BeautifulSoup("<html></html>", "html.parser")
        name, conf = detect_canonical_name(soup, "https://ncstatehockey.com")
        assert name == "NC State University"
        assert conf == ConfidenceLevel.MEDIUM

    def test_extract_venue_from_regex(self) -> None:
        """Verify venue regex matching."""
        text = "Our Home Rink: Polar Ice House in Wake Forest."
        assert _extract_venue_from_regex(text) == "Polar Ice House"

        text_games = "Home Games Played At: Invisalign Arena on Saturday"
        assert _extract_venue_from_regex(text_games) == "Invisalign Arena"

        assert _extract_venue_from_regex("No venue mentioned here.") is None
        assert _extract_venue_from_regex("Home Rink: Ice") is None

    def test_extract_venue_from_headings(self) -> None:
        """Verify venue extraction from heading tags."""
        html = "<h2>Wake Competition Center</h2>"
        soup = BeautifulSoup(html, "html.parser")
        assert _extract_venue_from_headings(soup) == "Wake Competition Center"

        html_short = "<h2>Ice Rink</h2>"
        soup_short = BeautifulSoup(html_short, "html.parser")
        assert _extract_venue_from_headings(soup_short) == "Ice Rink"

        html_none = "<h2>Welcome Fans</h2>"
        soup_none = BeautifulSoup(html_none, "html.parser")
        assert _extract_venue_from_headings(soup_none) is None

    def test_detect_home_venue(self) -> None:
        """Verify detect_home_venue precedence and confidence."""
        soup = BeautifulSoup("<h3>Garner Ice House</h3>", "html.parser")
        text = "Home Rink: Polar Ice House"
        venue, conf = detect_home_venue(soup, text)
        assert venue == "Polar Ice House"
        assert conf == ConfidenceLevel.HIGH

        venue_med, conf_med = detect_home_venue(soup, "No rink info in body.")
        assert venue_med == "Garner Ice House"
        assert conf_med == ConfidenceLevel.MEDIUM

        empty_soup = BeautifulSoup("<html></html>", "html.parser")
        venue_low, conf_low = detect_home_venue(empty_soup, "No rink info.")
        assert venue_low == "TBD"
        assert conf_low == ConfidenceLevel.LOW


class TestAliasDetection:
    """Tests for alias and abbreviation generation."""

    def test_generate_initials(self) -> None:
        """Verify generating initials from multi-word institution."""
        assert _generate_initials("East Carolina University") == "ecu"
        assert (
            _generate_initials("University of North Carolina at Chapel Hill") == "uncch"
        )

    def test_detect_known_aliases(self) -> None:
        """Verify known collegiate mascot alias lookup."""
        aliases, conf = detect_aliases(
            "NC State University",
            "https://ncsu.edu",
            "NC State",
        )
        assert "icepack" in aliases
        assert "wolfpack" in aliases
        assert conf == ConfidenceLevel.HIGH

    def test_detect_aliases_derived(self) -> None:
        """Verify deriving aliases from institution name, domain, and title."""
        aliases, conf = detect_aliases(
            "Coastal Carolina University",
            "https://chantshockey.com",
            "Coastal Carolina Chanticleers",
        )
        assert "ccu" in aliases
        assert "coastal carolina" in aliases
        assert "chants" in aliases
        assert "chanticleers" in aliases
        assert conf == ConfidenceLevel.MEDIUM

    def test_detect_aliases_empty(self) -> None:
        """Verify empty alias generation yields LOW confidence."""
        aliases, conf = detect_aliases("A", "https://a.com", "")
        assert aliases == ()
        assert conf == ConfidenceLevel.LOW

    def test_add_institutional_aliases_short_clean(self) -> None:
        """Verify institutional aliases without college or university suffix."""
        res: set[str] = set()
        _add_institutional_aliases("Duke University", res)
        assert "duke" in res
        assert "du" in res

    def test_add_domain_aliases_short(self) -> None:
        """Verify domain alias shorter than MIN_ALIAS_LENGTH is ignored."""
        res: set[str] = set()
        _add_domain_aliases("https://ab.com", res)
        assert not res

    def test_add_title_aliases_stopwords(self) -> None:
        """Verify title alias extraction filters common stopwords."""
        res: set[str] = set()
        _add_title_aliases("Official Home Ice Hockey Page", res)
        assert not res


class TestDiscoveredOpponentDataclass:
    """Tests for DiscoveredOpponent representation and methods."""

    def test_overall_confidence_high(self) -> None:
        """Verify HIGH overall confidence when name and feed are HIGH."""
        opp = DiscoveredOpponent(
            canonical_name="NC State University",
            feed_url="https://example.com/cal.ics",
            feed_type=OpponentFeedType.ICAL,
            confidence_scores={
                "canonical_name": ConfidenceLevel.HIGH,
                "feed_url": ConfidenceLevel.HIGH,
                "home_venue": ConfidenceLevel.LOW,
            },
        )
        assert opp.overall_confidence() == ConfidenceLevel.HIGH

    def test_overall_confidence_low(self) -> None:
        """Verify LOW overall confidence when either name or feed is LOW."""
        opp = DiscoveredOpponent(
            canonical_name="Unknown Opponent",
            feed_url="https://example.com",
            feed_type=OpponentFeedType.HTML,
            confidence_scores={
                "canonical_name": ConfidenceLevel.LOW,
                "feed_url": ConfidenceLevel.HIGH,
            },
        )
        assert opp.overall_confidence() == ConfidenceLevel.LOW

    def test_overall_confidence_medium(self) -> None:
        """Verify MEDIUM overall confidence when neither is LOW and not both HIGH."""
        opp = DiscoveredOpponent(
            canonical_name="NC State University",
            feed_url="https://example.com/schedule",
            feed_type=OpponentFeedType.HTML,
            confidence_scores={
                "canonical_name": ConfidenceLevel.HIGH,
                "feed_url": ConfidenceLevel.MEDIUM,
            },
        )
        assert opp.overall_confidence() == ConfidenceLevel.MEDIUM

    def test_to_endpoint_config(self) -> None:
        """Verify conversion to OpponentEndpointConfig."""
        opp = DiscoveredOpponent(
            canonical_name="NC State University",
            feed_url="https://example.com/cal.ics",
            feed_type=OpponentFeedType.ICAL,
            home_venue="Invisalign Arena",
            division="ACHA M2",
            conference="ACCHL",
            aliases=("icepack",),
            website="https://ncstatehockey.com",
            enabled=True,
        )
        cfg = opp.to_endpoint_config()
        assert cfg.canonical_name == "NC State University"
        assert cfg.feed_url == "https://example.com/cal.ics"
        assert cfg.home_venue == "Invisalign Arena"
        assert cfg.aliases == ("icepack",)

    def test_to_dict(self) -> None:
        """Verify dictionary serialization."""
        opp = DiscoveredOpponent(
            canonical_name="NC State University",
            feed_url="https://example.com/cal.ics",
            feed_type=OpponentFeedType.ICAL,
            home_venue="Invisalign Arena",
            division="ACHA M2",
            conference="ACCHL",
            aliases=("icepack",),
            website="https://ncstatehockey.com",
            enabled=True,
            confidence_scores={"canonical_name": ConfidenceLevel.HIGH},
            pages_crawled=("https://ncstatehockey.com",),
        )
        d = opp.to_dict()
        assert d["canonical_name"] == "NC State University"
        assert d["feed_type"] == "ical"
        assert d["overall_confidence"] == "LOW"
        assert d["pages_crawled"] == ["https://ncstatehockey.com"]

    def test_to_yaml_snippet_disabled_and_no_aliases(self) -> None:
        """Verify YAML formatting when disabled and aliases empty."""
        opp = DiscoveredOpponent(
            canonical_name="Wake Forest University",
            feed_url="https://example.com/schedule",
            feed_type=OpponentFeedType.HTML,
            home_venue="Annex",
            division="ACHA M2",
            conference="ACCHL",
            aliases=(),
            website=None,
            enabled=False,
        )
        yaml_str = opp.to_yaml_snippet()
        assert "enabled: false" in yaml_str
        assert "aliases: []" in yaml_str
        assert "website: https://example.com/schedule" in yaml_str


class TestInternalLinkHelpers:
    """Tests for internal link cleaning and sorting."""

    def test_clean_internal_link_invalid(self) -> None:
        """Verify non-navigational links return None."""
        assert _clean_internal_link("", "https://example.com", "example.com") is None
        assert (
            _clean_internal_link("#section", "https://example.com", "example.com")
            is None
        )
        assert (
            _clean_internal_link(
                "mailto:info@team.com",
                "https://example.com",
                "example.com",
            )
            is None
        )
        assert (
            _clean_internal_link("tel:555-1234", "https://example.com", "example.com")
            is None
        )
        assert (
            _clean_internal_link(
                "javascript:void(0)",
                "https://example.com",
                "example.com",
            )
            is None
        )
        assert (
            _clean_internal_link(
                "https://google.com",
                "https://example.com",
                "example.com",
            )
            is None
        )

    def test_clean_internal_link_valid(self) -> None:
        """Verify valid relative link cleans fragment."""
        clean = _clean_internal_link(
            "/schedule#games",
            "https://example.com",
            "example.com",
        )
        assert clean == "https://example.com/schedule"

    def test_collect_page_links(self) -> None:
        """Verify collecting internal links from page soup."""
        html = (
            '<a href="/schedule">Schedule</a>'
            '<a href="/about">About</a>'
            '<a href="https://external.com">External</a>'
            "<a>No href</a>"
        )
        soup = BeautifulSoup(html, "html.parser")
        links = _collect_page_links(soup, "https://example.com", "example.com")
        assert "https://example.com/schedule" in links
        assert "https://example.com/about" in links
        assert len(links) == 2

    def test_sort_links_by_priority(self) -> None:
        """Verify sorting links by relevance score."""
        links = [
            "https://example.com/about",
            "https://example.com/schedule",
            "https://example.com/rink",
        ]
        sorted_links = _sort_links_by_priority(links)
        assert sorted_links[0] == "https://example.com/schedule"
        assert sorted_links[1] == "https://example.com/rink"
        assert sorted_links[2] == "https://example.com/about"


class TestOpponentDiscoverySpider:
    """Tests for the OpponentDiscoverySpider traversal and discovery."""

    @pytest.mark.anyio
    async def test_fetch_page_safely_error(self) -> None:
        """Verify fetch error returns empty strings."""
        client = MagicMock()
        client.fetch_text = AsyncMock(side_effect=httpx.ConnectError("Failed"))
        spider = OpponentDiscoverySpider(client=client)
        text, hash_val = await spider._fetch_page_safely("https://example.com")
        assert text == ""
        assert hash_val == ""

    @pytest.mark.anyio
    async def test_discover_full_flow(self) -> None:
        """Verify full spidering discovery across mock pages."""
        home_html = (
            "<html><head><title>NC State Icepack Hockey Club</title></head>"
            '<body><h1>NC State Icepack</h1><a href="/schedule">View Schedule</a>'
            '<a href="/arena">Our Arena</a></body></html>'
        )
        sched_html = (
            "<html><head><title>Schedule - NC State Icepack</title></head>"
            '<body><a href="/calendar.ics">Subscribe to Calendar</a>'
            "<table><tr><td>Game 1</td></tr></table></body></html>"
        )
        arena_html = (
            "<html><head><title>Arena - NC State Icepack</title></head>"
            "<body><p>Home Rink: Invisalign Arena</p></body></html>"
        )

        mock_responses = {
            "https://ncstatehockey.com": (home_html, "hash1"),
            "https://ncstatehockey.com/schedule": (sched_html, "hash2"),
            "https://ncstatehockey.com/arena": (arena_html, "hash3"),
        }

        async def _mock_fetch(url: str) -> tuple[str, str]:
            return mock_responses.get(url, ("", ""))

        client = MagicMock()
        client.fetch_text = AsyncMock(side_effect=_mock_fetch)
        spider = OpponentDiscoverySpider(client=client, max_pages=5)

        discovered = await spider.discover("https://ncstatehockey.com")

        assert discovered.canonical_name == "NC State University"
        assert discovered.feed_url == "https://ncstatehockey.com/calendar.ics"
        assert discovered.feed_type == OpponentFeedType.ICAL
        assert discovered.home_venue == "Invisalign Arena"
        assert discovered.overall_confidence() == ConfidenceLevel.HIGH
        assert discovered.pages_crawled[0] == "https://ncstatehockey.com"

    @pytest.mark.anyio
    async def test_discover_html_feed_fallback(self) -> None:
        """Verify HTML table fallback when no iCal or JSON feed exists."""
        home_html = (
            "<html><head><title>Coastal Carolina Hockey</title></head>"
            '<body><a href="/schedule">Schedule</a></body></html>'
        )
        sched_html = (
            "<html><head><title>Schedule</title></head>"
            "<body><h3>Inlet Ice House</h3>"
            "<table><tr><td>Game vs ECU</td></tr></table></body></html>"
        )

        mock_responses = {
            "https://coastalhockey.com": (home_html, "h1"),
            "https://coastalhockey.com/schedule": (sched_html, "h2"),
        }

        async def _mock_fetch(url: str) -> tuple[str, str]:
            return mock_responses.get(url, ("", ""))

        client = MagicMock()
        client.fetch_text = AsyncMock(side_effect=_mock_fetch)
        spider = OpponentDiscoverySpider(client=client, max_pages=5)

        discovered = await spider.discover("https://coastalhockey.com")

        assert discovered.feed_type == OpponentFeedType.HTML
        assert discovered.feed_url == "https://coastalhockey.com/schedule"
        assert discovered.home_venue == "Inlet Ice House"

    @pytest.mark.anyio
    async def test_discover_empty_page_skipped(self) -> None:
        """Verify spider handles empty page responses gracefully."""
        client = MagicMock()
        client.fetch_text = AsyncMock(return_value=("", ""))
        spider = OpponentDiscoverySpider(client=client, max_pages=2)

        discovered = await spider.discover("https://deadlink.com")
        assert discovered.canonical_name == "Deadlink"
        assert discovered.feed_url == "https://deadlink.com"

    def test_process_page_venue_preserves_high(self) -> None:
        """Verify venue processing preserves HIGH confidence."""
        spider = OpponentDiscoverySpider()
        soup = BeautifulSoup("<h3>Other Center</h3>", "html.parser")
        current = ("Existing Arena", ConfidenceLevel.HIGH)
        res = spider._process_page_venue(soup, "some text", current)
        assert res == current

    def test_process_page_feed_preserves_existing(self) -> None:
        """Verify feed processing preserves existing feed if HTML."""
        spider = OpponentDiscoverySpider()
        soup = BeautifulSoup("<table><tr><td>Game</td></tr></table>", "html.parser")
        current = (
            "https://example.com/sched.ics",
            OpponentFeedType.ICAL,
            ConfidenceLevel.HIGH,
        )
        res = spider._process_page_feed(soup, "https://example.com/schedule", current)
        assert res == current

    def test_update_candidate_name_non_base_skipped(self) -> None:
        """Verify non-base url does not overwrite existing good name."""
        spider = OpponentDiscoverySpider()
        state = _SpiderState(best_name=("NC State University", ConfidenceLevel.HIGH))
        soup = BeautifulSoup("<title>Other Name</title>", "html.parser")
        spider._update_candidate_name(
            soup,
            "https://example.com/subpage",
            "https://example.com",
            state,
        )
        assert state.best_name[0] == "NC State University"

    def test_update_candidate_name_low_ignored(self) -> None:
        """Verify detect_canonical_name returning LOW does not overwrite state."""
        spider = OpponentDiscoverySpider()
        state = _SpiderState(best_name=("NC State University", ConfidenceLevel.HIGH))
        soup = BeautifulSoup("<html></html>", "html.parser")
        spider._update_candidate_name(
            soup,
            "https://hockey.com",
            "https://hockey.com",
            state,
        )
        assert state.best_name[0] == "NC State University"

    def test_enqueue_new_links_duplicates(self) -> None:
        """Verify duplicate or already visited links are not enqueued."""
        spider = OpponentDiscoverySpider()
        soup = BeautifulSoup(
            '<a href="/schedule">Schedule</a><a href="/about">About</a>',
            "html.parser",
        )
        queue = ["https://example.com/schedule"]
        visited = {"https://example.com/about"}
        spider._enqueue_new_links(
            soup,
            "https://example.com",
            "example.com",
            queue,
            visited,
        )
        assert queue == ["https://example.com/schedule"]

    @pytest.mark.anyio
    async def test_discover_skips_visited(self) -> None:
        """Verify discover skips already visited URLs in queue."""
        client = MagicMock()
        client.fetch_text = AsyncMock(
            return_value=("<html><title>Duke Hockey</title></html>", "hash1"),
        )
        spider = OpponentDiscoverySpider(client=client, max_pages=3)
        with patch.object(
            spider,
            "_enqueue_new_links",
            side_effect=lambda s, u, r, q, v: q.append("https://dukehockey.com"),
        ):
            discovered = await spider.discover("https://dukehockey.com")

        assert discovered.canonical_name == "Duke University"


class TestYamlPersistence:
    """Tests for appending discovered opponent to YAML configuration files."""

    def test_append_opponent_to_new_file(self, tmp_path: Path) -> None:
        """Verify creating new YAML file and appending opponent entry."""
        target_file = tmp_path / "subdir" / "opponents.yaml"
        opp = DiscoveredOpponent(
            canonical_name="NC State University",
            feed_url="https://ncstatehockey.com/calendar.ics",
            feed_type=OpponentFeedType.ICAL,
            home_venue="Invisalign Arena",
            division="ACHA M2",
            conference="ACCHL",
            aliases=("icepack", "pack"),
            website="https://ncstatehockey.com",
            enabled=True,
        )

        append_opponent_to_yaml_file(target_file, opp)
        assert target_file.is_file()

        dir_obj = OpponentDirectory.from_yaml(target_file)
        assert "NC State University" in dir_obj
        entry = dir_obj.get("NC State University")
        assert entry is not None
        assert entry.feed_type == OpponentFeedType.ICAL
        assert entry.home_venue == "Invisalign Arena"

    def test_append_opponent_to_existing_file(self, tmp_path: Path) -> None:
        """Verify appending to existing YAML file with valid syntax."""
        target_file = tmp_path / "opponents.yaml"
        opp1 = DiscoveredOpponent(
            canonical_name="NC State University",
            feed_url="https://ncstatehockey.com/cal.ics",
            feed_type=OpponentFeedType.ICAL,
            home_venue="Invisalign Arena",
        )
        append_opponent_to_yaml_file(target_file, opp1)

        opp2 = DiscoveredOpponent(
            canonical_name="Wake Forest University",
            feed_url="https://wakehockey.com/cal.ics",
            feed_type=OpponentFeedType.ICAL,
            home_venue="Winston-Salem Fairgrounds Annex",
        )
        append_opponent_to_yaml_file(target_file, opp2)

        dir_obj = OpponentDirectory.from_yaml(target_file)
        assert "NC State University" in dir_obj
        assert "Wake Forest University" in dir_obj

    def test_append_opponent_to_existing_file_without_trailing_newline(
        self,
        tmp_path: Path,
    ) -> None:
        """Verify appending to existing YAML file without trailing newline."""
        target_file = tmp_path / "opponents.yaml"
        opp1 = DiscoveredOpponent(
            canonical_name="NC State University",
            feed_url="https://ncstatehockey.com/cal.ics",
            feed_type=OpponentFeedType.ICAL,
        )
        append_opponent_to_yaml_file(target_file, opp1)
        content = target_file.read_text(encoding="utf-8").rstrip("\n")
        target_file.write_text(content, encoding="utf-8")

        opp2 = DiscoveredOpponent(
            canonical_name="Wake Forest University",
            feed_url="https://wakehockey.com/cal.ics",
            feed_type=OpponentFeedType.ICAL,
        )
        append_opponent_to_yaml_file(target_file, opp2)
        dir_obj = OpponentDirectory.from_yaml(target_file)
        assert "Wake Forest University" in dir_obj

    def test_append_opponent_duplicate_raises_error(self, tmp_path: Path) -> None:
        """Verify duplicate canonical name raises OpponentConfigError."""
        target_file = tmp_path / "opponents.yaml"
        opp = DiscoveredOpponent(
            canonical_name="NC State University",
            feed_url="https://ncstatehockey.com/cal.ics",
            feed_type=OpponentFeedType.ICAL,
        )
        append_opponent_to_yaml_file(target_file, opp)

        with pytest.raises(OpponentConfigError, match="already exists"):
            append_opponent_to_yaml_file(target_file, opp)

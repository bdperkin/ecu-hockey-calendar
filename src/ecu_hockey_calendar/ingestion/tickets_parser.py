"""ECU Hockey ticketing and promotional theme parser."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from ecu_hockey_calendar.ingestion.html_parser import (
    ParsedGameRecord,
    _clean_text,
    _generate_game_id,
)
from ecu_hockey_calendar.ingestion.normalizer import (
    normalize_team_name,
    parse_game_datetime,
)
from ecu_hockey_calendar.storage.models import GameStatus

DEFAULT_TICKETS_PAGE_URL = "https://www.ecuhockey.com/tickets"
DEFAULT_ECU_CANONICAL = "East Carolina University"
ECU_KEYWORDS = ("ecu", "east carolina", "pirates")

PROMOTIONAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"military\s+appreciation", re.IGNORECASE),
        "Military Appreciation Night",
    ),
    (
        re.compile(r"teddy\s+bear\s+toss", re.IGNORECASE),
        "Teddy Bear Toss",
    ),
    (
        re.compile(
            r"pucks?\s*(?:&|and)\s*paws|pups?\s+at\s+the\s+rink",
            re.IGNORECASE,
        ),
        "Pucks & Paws",
    ),
    (
        re.compile(
            r"pink\s+in\s+the\s+rink|breast\s+cancer\s+awareness",
            re.IGNORECASE,
        ),
        "Pink in the Rink",
    ),
    (
        re.compile(r"senior\s+night", re.IGNORECASE),
        "Senior Night",
    ),
    (
        re.compile(r"alumni\s+(?:night|weekend|game)", re.IGNORECASE),
        "Alumni Weekend",
    ),
    (
        re.compile(
            r"youth\s+hockey\s+night|kids?\s+day",
            re.IGNORECASE,
        ),
        "Youth Hockey Night",
    ),
    (
        re.compile(r"star\s+wars\s+night", re.IGNORECASE),
        "Star Wars Night",
    ),
    (
        re.compile(r"retro\s+night|(?:80s|90s)\s+night", re.IGNORECASE),
        "Retro Night",
    ),
    (
        re.compile(
            r"st\.?\s*patrick'?s?\s+day|green\s+game",
            re.IGNORECASE,
        ),
        "St. Patrick's Day",
    ),
    (
        re.compile(
            r"give\s+back\s+to\s+greenville|community\s+night",
            re.IGNORECASE,
        ),
        "Give Back to Greenville Day",
    ),
    (
        re.compile(r"outdoor\s+classic|winter\s+classic", re.IGNORECASE),
        "ACCHL Outdoor Classic",
    ),
    (
        re.compile(r"playoffs?|championship|tournament", re.IGNORECASE),
        "Playoffs / Tournament",
    ),
    (
        re.compile(r"white\s*out", re.IGNORECASE),
        "Whiteout",
    ),
    (
        re.compile(r"black\s*out", re.IGNORECASE),
        "Blackout",
    ),
    (
        re.compile(r"gold\s*rush", re.IGNORECASE),
        "Gold Rush",
    ),
    (
        re.compile(r"hawaiian|beach\s+night", re.IGNORECASE),
        "Hawaiian Night",
    ),
    (
        re.compile(r"raffle(?:\s+drawing)?", re.IGNORECASE),
        "Raffle Drawing",
    ),
)


@dataclass(frozen=True, slots=True)
class TicketPriceTier:
    """Individual price tier within a ticket offering."""

    name: str
    price_cents: int
    currency: str = "usd"
    description: str = ""

    @property
    def price_dollars(self) -> float:
        """Convert price in cents to dollars float."""
        return self.price_cents / 100.0


def _build_ticket_game_metadata(
    ticket: ParsedTicketRecord,
    season: str,
) -> dict[str, object]:
    """Build metadata dictionary for game generated from ticket listing."""
    meta: dict[str, object] = {
        "ticket_id": ticket.ticket_id,
        "ticket_url": ticket.ticket_url,
        "promotion": ticket.promotion,
        "price_min": ticket.price_min,
        "price_max": ticket.price_max,
        "in_stock": ticket.in_stock,
        "season": season,
    }
    if ticket.metadata:
        meta.update(ticket.metadata)

    return meta


def _ticket_record_to_game(
    ticket: ParsedTicketRecord,
    season: str = "2026-2027",
) -> ParsedGameRecord | None:
    """Convert ticket record to ParsedGameRecord if game details exist."""
    if not ticket.opponent_name or ticket.start_time is None:
        return None

    meta = _build_ticket_game_metadata(ticket, season)
    game_id = _generate_game_id(
        ticket.start_time,
        ticket.opponent_name,
        is_home=ticket.is_home_game,
    )
    return ParsedGameRecord(
        game_id=game_id,
        opponent_name=ticket.opponent_name,
        is_home=ticket.is_home_game,
        start_time=ticket.start_time,
        venue=ticket.venue,
        status=GameStatus.SCHEDULED,
        raw_text=ticket.raw_text or ticket.title,
        metadata=meta,
    )


# pylint: disable=too-many-instance-attributes
@dataclass(frozen=True, slots=True)
class ParsedTicketRecord:
    """Intermediate parsed representation of a ticketing listing or promotion.

    Attributes:
        ticket_id: Unique identifier for the ticket listing or event.
        title: Title of ticket listing.
        opponent_name: Opponent team name if extracted from game listing.
        start_time: Scheduled date and start time in UTC.
        venue: Arena or venue location.
        promotion: Extracted promotional theme night or special event notes.
        ticket_url: Direct checkout link or ticketing vendor URL.
        price_min: Minimum ticket price in dollars.
        price_max: Maximum ticket price in dollars.
        price_description: Textual description of pricing.
        in_stock: Whether tickets are currently available for purchase.
        is_home_game: Whether listing corresponds to an ECU home game.
        prices: Individual price tier definitions.
        raw_text: Raw unparsed text snippet for auditing.
        metadata: Supplementary attributes dictionary.
    """

    ticket_id: str
    title: str
    opponent_name: str | None = None
    start_time: datetime | None = None
    venue: str = "TBD"
    promotion: str | None = None
    ticket_url: str = ""
    price_min: float | None = None
    price_max: float | None = None
    price_description: str | None = None
    in_stock: bool = True
    is_home_game: bool = True
    prices: tuple[TicketPriceTier, ...] = ()
    raw_text: str = ""
    metadata: dict[str, object] | None = None

    def to_parsed_game_record(
        self,
        *,
        season: str = "2026-2027",
    ) -> ParsedGameRecord | None:
        """Convert ticket record to ParsedGameRecord if game details exist.

        Args:
            season: Target collegiate hockey season.

        Returns:
            ParsedGameRecord instance or None if not an identifiable game.
        """
        return _ticket_record_to_game(self, season=season)


def extract_promotional_theme(text: str | None) -> str | None:
    """Identify promotional theme night or event category from text.

    Args:
        text: Arbitrary promotional description or title string.

    Returns:
        Canonical promotional theme name if recognized, else None.
    """
    if not text:
        return None

    for pattern, theme in PROMOTIONAL_PATTERNS:
        if pattern.search(text):
            return theme

    return None


def _is_unpriced_text(clean: str) -> bool:
    """Check if price text represents missing or unavailable pricing."""
    return not clean or clean.lower() in {"n/a", "tbd", "tba"}


def _extract_price_numbers(clean: str) -> list[float]:
    """Extract numeric dollar amounts from cleaned text."""
    matches = re.findall(r"\$?\s*(\d+(?:\.\d{1,2})?)", clean)
    return [float(m) for m in matches]


def parse_price_text(text: str | None) -> tuple[float | None, float | None]:
    """Parse price string into minimum and maximum dollar amounts.

    Args:
        text: Raw price text like '$10', '$5 - $15', 'From $1 USD to $15 USD', 'Free'.

    Returns:
        Tuple of (price_min, price_max) in dollar floats, or (None, None).
    """
    if not text:
        return None, None

    clean = text.strip()
    if _is_unpriced_text(clean):
        return None, None

    if "free" in clean.lower():
        return 0.0, 0.0

    numbers = _extract_price_numbers(clean)
    if not numbers:
        return None, None

    return min(numbers), max(numbers)


def identify_ticketing_vendor(url: str | None) -> str:
    """Detect ticketing platform vendor name from checkout URL.

    Args:
        url: Full checkout or ticket detail link.

    Returns:
        Vendor identifier such as 'etix', 'eventbrite', 'ticketmaster', or 'optimx'.
    """
    if not url:
        return "unknown"

    host = urlparse(url).netloc.lower()
    vendor_map = {
        "etix.com": "etix",
        "eventbrite.com": "eventbrite",
        "ticketmaster.com": "ticketmaster",
        "seatgeek.com": "seatgeek",
        "axs.com": "axs",
        "gofan.co": "gofan",
        "ecuhockey.com": "optimx",
    }
    for domain, vendor in vendor_map.items():
        if domain in host:
            return vendor

    return "external"


def _clean_opponent_text(text: str) -> str:
    """Strip extraneous date, venue, and theme noise from candidate opponent string."""
    sub = re.sub(
        r"(?i)\s+(?:on\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{1,2}(?:st|[n]d|rd|th)?.*$",
        "",
        text,
    )
    sub = re.sub(r"(?i)\s+on\s+\d{2}-\d{2}-\d{4}.*$", "", sub)
    sub = re.sub(r"\s*[-|\u2013\u2014]\s*.*$", "", sub)
    return sub.strip()


def _contains_ecu(text: str) -> bool:
    """Check if text contains ECU team keywords."""
    low = text.lower()
    return any(k in low for k in ECU_KEYWORDS)


def _clean_team(raw: str) -> str | None:
    """Clean and normalize candidate opponent text."""
    cleaned = _clean_opponent_text(raw)
    return normalize_team_name(cleaned) or None


def _match_vs_opponent(clean: str) -> tuple[str | None, bool] | None:
    """Extract opponent from 'vs' or 'against' format."""
    parts = re.split(r"(?i)\s+(?:vs\.?|against)\s+", clean, maxsplit=1)
    if len(parts) <= 1:
        return None

    t1, t2 = parts[0].strip(), parts[1].strip()
    if _contains_ecu(t1):
        return _clean_team(t2), True

    if _contains_ecu(t2):
        return _clean_team(t1), False

    return None


def _match_at_opponent(clean: str) -> tuple[str | None, bool] | None:
    """Extract opponent from '@' format."""
    parts = re.split(r"\s+@\s+", clean, maxsplit=1)
    if len(parts) <= 1:
        return None

    t1, t2 = parts[0].strip(), parts[1].strip()
    if _contains_ecu(t1):
        return _clean_team(t2), False

    if _contains_ecu(t2):
        return _clean_team(t1), True

    return None


def _match_prefix_opponent(clean: str) -> tuple[str | None, bool] | None:
    """Extract opponent from 'game vs <opponent>' prefix format."""
    match = re.match(r"(?i)^game\s+vs\s+(.*?)(?:\s+on\s+.*)?$", clean)
    if not match:
        return None

    return _clean_team(match.group(1)), True


def extract_opponent_from_title(title: str | None) -> tuple[str | None, bool]:
    """Extract opponent name and home/away status from game title.

    Args:
        title: Title string like 'ECU vs NC State - Military Night'.

    Returns:
        Tuple of (canonical_opponent_name, is_home).
    """
    if not title:
        return None, True

    clean = title.strip()
    return (
        _match_vs_opponent(clean)
        or _match_at_opponent(clean)
        or _match_prefix_opponent(clean)
        or (None, True)
    )


def _get_map_str(
    fields: Mapping[str, object],
    key: str,
    default: str = "",
) -> str:
    """Extract stringValue from Firestore field map."""
    val = fields.get(key)
    if isinstance(val, dict) and val.get("stringValue"):
        return str(val["stringValue"])

    return default


def _get_map_int(
    fields: Mapping[str, object],
    key: str,
    default: int = 0,
) -> int:
    """Extract integerValue from Firestore field map."""
    val = fields.get(key)
    if isinstance(val, dict) and val.get("integerValue"):
        try:
            return int(val["integerValue"])
        except (ValueError, TypeError):
            return default

    return default


def _extract_map_fields(item: object) -> Mapping[str, object] | None:
    """Extract non-empty fields map from Firestore item."""
    if not isinstance(item, dict):
        return None

    m_fields = item.get("mapValue", {}).get("fields")
    if not isinstance(m_fields, (dict, Mapping)) or not m_fields:
        return None

    return cast("Mapping[str, object]", m_fields)


def _parse_single_price_tier(item: object) -> TicketPriceTier | None:
    """Parse single price tier map dictionary from Firestore arrayValue item."""
    m_fields = _extract_map_fields(item)
    if m_fields is None:
        return None

    return TicketPriceTier(
        name=_get_map_str(m_fields, "title", "General"),
        price_cents=_get_map_int(m_fields, "price", 0),
        currency=_get_map_str(m_fields, "currency", "usd"),
        description=_get_map_str(m_fields, "description", ""),
    )


def _extract_firestore_tier_list(
    prices_field: Mapping[str, object],
) -> list[TicketPriceTier]:
    """Extract list of valid TicketPriceTier objects from Firestore price field."""
    tiers: list[TicketPriceTier] = []
    array_val = prices_field.get("arrayValue", {})
    if not isinstance(array_val, dict):
        return tiers

    values = array_val.get("values", [])
    if not isinstance(values, list):
        return tiers

    for item in values:
        tier = _parse_single_price_tier(item)
        if tier is not None:
            tiers.append(tier)

    return tiers


def _parse_firestore_price_values(
    prices_field: Mapping[str, object],
) -> tuple[list[TicketPriceTier], float | None, float | None]:
    """Parse Firestore arrayValue of price map entries."""
    tiers = _extract_firestore_tier_list(prices_field)
    if not tiers:
        return tiers, None, None

    dollars = [t.price_dollars for t in tiers]
    return tiers, min(dollars), max(dollars)


def _extract_single_timestamp(field_val: object) -> datetime | None:
    """Parse single Firestore timestampValue dictionary."""
    if not isinstance(field_val, dict):
        return None

    ts = field_val.get("timestampValue")
    if not ts or not isinstance(ts, str):
        return None

    try:
        clean_ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(clean_ts).astimezone(UTC)
    except ValueError:
        return None


def _parse_firestore_event_time(
    fields: Mapping[str, object],
) -> datetime | None:
    """Extract start timestamp from Firestore ticket fields."""
    for key in ("timeOfEvent", "validFrom", "timeCreated"):
        dt = _extract_single_timestamp(fields.get(key))
        if dt is not None:
            return dt

    return None


def _extract_doc_id(
    doc: Mapping[str, object],
    fields: Mapping[str, object],
) -> str:
    """Extract unique identifier from Firestore ticket fields or document name."""
    id_field = fields.get("id")
    if isinstance(id_field, dict) and id_field.get("stringValue"):
        return str(id_field["stringValue"])

    return str(doc.get("name", "")).rsplit("/", maxsplit=1)[-1]


def _extract_doc_title(fields: Mapping[str, object]) -> str:
    """Extract title from eventTitle or title field."""
    for key in ("eventTitle", "title"):
        val = fields.get(key)
        if isinstance(val, dict) and val.get("stringValue"):
            return str(val["stringValue"])

    return ""


def _extract_doc_prices(
    fields: Mapping[str, object],
    price_desc: str,
) -> tuple[tuple[TicketPriceTier, ...], float | None, float | None]:
    """Extract price tiers and bounds from Firestore prices or price description."""
    prices_raw = fields.get("prices")
    prices_dict: Mapping[str, object] = (
        prices_raw if isinstance(prices_raw, (dict, Mapping)) else {}
    )
    tiers, p_min, p_max = _parse_firestore_price_values(prices_dict)
    if p_min is None and price_desc:
        p_min, p_max = parse_price_text(price_desc)

    return tuple(tiers), p_min, p_max


def _extract_doc_stripe_metadata(
    fields: Mapping[str, object],
) -> dict[str, object]:
    """Extract stripe IDs from document fields."""
    stripe_acc = fields.get("stripeAccountId", {})
    stripe_prod = fields.get("stripeProductId", {})
    return {
        "stripe_account_id": (
            stripe_acc.get("stringValue") if isinstance(stripe_acc, dict) else None
        ),
        "stripe_product_id": (
            stripe_prod.get("stringValue") if isinstance(stripe_prod, dict) else None
        ),
    }


def _extract_doc_in_stock(fields: Mapping[str, object]) -> bool:
    """Extract inStock boolean flag defaulting to True."""
    val = fields.get("inStock")
    return not (isinstance(val, dict) and val.get("booleanValue") is False)


def parse_firestore_ticket_doc(
    doc: Mapping[str, object],
    *,
    default_base_url: str = "https://www.ecuhockey.com",
) -> ParsedTicketRecord | None:
    """Parse single Firestore ticket document into ParsedTicketRecord.

    Args:
        doc: Firestore document dictionary with 'fields' and 'name'.
        default_base_url: Base domain for checkout links.

    Returns:
        ParsedTicketRecord instance or None if deleted/invalid.
    """
    fields = doc.get("fields")
    if not isinstance(fields, (dict, Mapping)):
        return None

    if fields.get("deleted", {}).get("booleanValue") is True:
        return None

    title = _extract_doc_title(fields)
    if not title:
        return None

    doc_id = _extract_doc_id(doc, fields)
    venue = _get_map_str(fields, "eventVenue", "TBD")
    short_desc = _get_map_str(fields, "shortDescription")
    price_desc = _get_map_str(fields, "priceDescription")
    tiers, p_min, p_max = _extract_doc_prices(fields, price_desc)

    return ParsedTicketRecord(
        ticket_id=doc_id,
        title=title,
        opponent_name=extract_opponent_from_title(title)[0],
        start_time=_parse_firestore_event_time(fields),
        venue=venue,
        promotion=extract_promotional_theme(f"{title} {short_desc}"),
        ticket_url=f"{default_base_url}/tickets/{doc_id}",
        price_min=p_min,
        price_max=p_max,
        price_description=price_desc or None,
        in_stock=_extract_doc_in_stock(fields),
        is_home_game=extract_opponent_from_title(title)[1],
        prices=tiers,
        raw_text=f"{title} {price_desc}".strip(),
        metadata=_extract_doc_stripe_metadata(fields),
    )


def _extract_response_items(
    data: Sequence[object] | Mapping[str, object],
) -> Sequence[object]:
    """Normalize input data into a sequence of items."""
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes, Mapping)):
        return data

    return [data]


def parse_firestore_tickets_response(
    data: Sequence[object] | Mapping[str, object],
    *,
    default_base_url: str = "https://www.ecuhockey.com",
) -> list[ParsedTicketRecord]:
    """Parse Firestore runQuery response into list of ParsedTicketRecord.

    Args:
        data: Array or map returned from documents:runQuery.
        default_base_url: Base domain for checkout URLs.

    Returns:
        List of parsed ticket records.
    """
    records: list[ParsedTicketRecord] = []
    for item in _extract_response_items(data):
        if not isinstance(item, (dict, Mapping)):
            continue

        doc = item.get("document")
        if not isinstance(doc, (dict, Mapping)):
            continue

        rec = parse_firestore_ticket_doc(doc, default_base_url=default_base_url)
        if rec is not None:
            records.append(rec)

    return records


def _find_card_title_tag(card: Tag) -> Tag | None:
    """Find title or heading tag within card markup."""
    return card.find(
        class_=re.compile(r"title|event-name|ticket-name|heading", re.IGNORECASE),
    ) or card.find(["h2", "h3", "h4", "h5"])


def _find_card_link_tag(card: Tag) -> Tag | None:
    """Find checkout or ticketing link tag within card markup."""
    return card.find(
        "a",
        href=re.compile(
            r"tickets|checkout|eventbrite|etix|ticketmaster",
            re.IGNORECASE,
        ),
    ) or card.find("a", href=True)


def _extract_card_title_and_link(
    card: Tag,
    base_url: str,
) -> tuple[str, str]:
    """Extract listing title text and normalized checkout URL."""
    title_tag = _find_card_title_tag(card)
    title_text = _clean_text(title_tag) if isinstance(title_tag, Tag) else ""

    link_tag = _find_card_link_tag(card)
    checkout_url = ""
    if isinstance(link_tag, Tag) and link_tag.get("href"):
        checkout_url = urljoin(base_url, str(link_tag.get("href")))
        if not title_text:
            title_text = _clean_text(link_tag)

    return title_text, checkout_url


def _extract_card_datetime(
    card: Tag,
    season: str,
) -> datetime | None:
    """Extract and parse start datetime from card markup."""
    date_tag = card.find(
        class_=re.compile(r"date|time|datetime|schedule", re.IGNORECASE),
    ) or card.find("time")
    if not isinstance(date_tag, Tag):
        return None

    raw_date = _clean_text(date_tag)
    if not raw_date:
        return None

    try:
        return parse_game_datetime(raw_date, season=season)
    except ValueError:
        return None


def _extract_card_venue_and_price(
    card: Tag,
) -> tuple[str, tuple[float | None, float | None], str | None]:
    """Extract venue name and price values from card element."""
    venue_tag = card.find(
        class_=re.compile(r"venue|location|rink|arena", re.IGNORECASE),
    )
    venue = _clean_text(venue_tag) if isinstance(venue_tag, Tag) else "TBD"

    price_tag = card.find(class_=re.compile(r"price|cost|tier", re.IGNORECASE))
    price_text = _clean_text(price_tag) if isinstance(price_tag, Tag) else None
    prices = parse_price_text(price_text)
    return venue or "TBD", prices, price_text


def _parse_single_ticket_card(
    card: Tag,
    index: int,
    base_url: str,
    season: str,
) -> ParsedTicketRecord | None:
    """Parse single HTML ticket card or listing tag."""
    title_text, checkout_url = _extract_card_title_and_link(card, base_url)
    if not title_text:
        return None

    start_time = _extract_card_datetime(card, season)
    venue, (p_min, p_max), price_text = _extract_card_venue_and_price(card)
    opponent, is_home = extract_opponent_from_title(title_text)
    promotion = extract_promotional_theme(f"{title_text} {card.get_text()}")
    card_id = (
        card.get("id")
        or card.get("data-ticket-id")
        or card.get("data-id")
        or f"ticket-{index}"
    )

    return ParsedTicketRecord(
        ticket_id=str(card_id),
        title=title_text,
        opponent_name=opponent,
        start_time=start_time,
        venue=venue,
        promotion=promotion,
        ticket_url=checkout_url,
        price_min=p_min,
        price_max=p_max,
        price_description=price_text,
        in_stock=True,
        is_home_game=is_home,
        raw_text=_clean_text(card),
    )


def _select_ticket_card_tags(soup: BeautifulSoup) -> list[Tag]:
    """Find ticket listing tags across standard and fallback CSS classes."""
    cards = soup.select(
        ".ticket-card, .ticket-item, .event-card, .event-item, tr.ticket-row",
    )
    if cards:
        return cards

    candidates = soup.find_all(
        ["div", "article"],
        class_=re.compile(r"ticket|event", re.IGNORECASE),
    )
    return [
        c
        for c in candidates
        if not c.find(class_=re.compile(r"ticket|event", re.IGNORECASE))
    ]


def parse_html_ticket_listings(
    html: str,
    *,
    base_url: str = DEFAULT_TICKETS_PAGE_URL,
    season: str = "2026-2027",
) -> list[ParsedTicketRecord]:
    """Parse raw ticketing HTML into structured ticket and promotional records.

    Args:
        html: Raw HTML page content.
        base_url: Base domain for resolving relative checkout URLs.
        season: Collegiate hockey season.

    Returns:
        List of parsed ticket records.
    """
    soup = BeautifulSoup(html, "html.parser")
    records: list[ParsedTicketRecord] = []
    cards = _select_ticket_card_tags(soup)

    for idx, card in enumerate(cards, start=1):
        rec = _parse_single_ticket_card(card, idx, base_url, season)
        if rec is not None:
            records.append(rec)

    return records


def _build_enriched_metadata(
    game: ParsedGameRecord,
    ticket: ParsedTicketRecord,
) -> dict[str, object]:
    """Attach ticketing metadata to game dictionary."""
    meta = dict(game.metadata or {})
    meta["ticket_id"] = ticket.ticket_id
    meta["ticket_url"] = ticket.ticket_url
    meta["ticketing_vendor"] = identify_ticketing_vendor(ticket.ticket_url)
    meta["ticket_in_stock"] = ticket.in_stock

    if ticket.promotion:
        meta["promotion"] = ticket.promotion

    if ticket.price_min is not None:
        meta["ticket_price_min"] = ticket.price_min

    if ticket.price_max is not None:
        meta["ticket_price_max"] = ticket.price_max

    return meta


def _resolve_enriched_venue(game_venue: str, ticket_venue: str) -> str:
    """Resolve venue preferring verified ticket venue if game venue is TBD."""
    if (game_venue in {"", "TBD"}) and ticket_venue not in {"", "TBD"}:
        return ticket_venue

    return game_venue


def _enrich_game_with_ticket(
    game: ParsedGameRecord,
    ticket: ParsedTicketRecord,
) -> ParsedGameRecord:
    """Return new ParsedGameRecord with ticket and promotional metadata attached."""
    meta = _build_enriched_metadata(game, ticket)
    venue = _resolve_enriched_venue(game.venue, ticket.venue)

    return ParsedGameRecord(
        game_id=game.game_id,
        opponent_name=game.opponent_name,
        is_home=game.is_home,
        start_time=game.start_time,
        venue=venue,
        status=game.status,
        home_score=game.home_score,
        away_score=game.away_score,
        overtime_note=game.overtime_note,
        raw_text=game.raw_text,
        league_game_id=game.league_game_id,
        metadata=meta,
    )


def _is_same_day(dt1: datetime, dt2: datetime) -> bool:
    """Check if two UTC datetimes fall on the exact same calendar day."""
    return dt1.year == dt2.year and dt1.month == dt2.month and dt1.day == dt2.day


def _matches_game_and_ticket(
    game: ParsedGameRecord,
    ticket: ParsedTicketRecord,
) -> bool:
    """Check whether a ticket record corresponds to a given scheduled game."""
    if ticket.start_time is None:
        return False

    if not _is_same_day(game.start_time, ticket.start_time):
        return False

    if not ticket.opponent_name:
        return True

    return game.opponent_name == ticket.opponent_name


def _find_matching_ticket(
    game: ParsedGameRecord,
    tickets: Sequence[ParsedTicketRecord],
) -> ParsedTicketRecord | None:
    """Find first ticket matching scheduled game."""
    for ticket in tickets:
        if _matches_game_and_ticket(game, ticket):
            return ticket

    return None


def _collect_unmatched_ticket_games(
    tickets: Sequence[ParsedTicketRecord],
    matched_ids: set[str],
    season: str,
) -> list[ParsedGameRecord]:
    """Convert unmatched home game tickets into ParsedGameRecord instances."""
    new_games: list[ParsedGameRecord] = []
    for ticket in tickets:
        if ticket.ticket_id in matched_ids:
            continue

        unmatched_game = ticket.to_parsed_game_record(season=season)
        if unmatched_game is not None:
            new_games.append(unmatched_game)

    return new_games


def cross_reference_tickets_with_games(
    tickets: Sequence[ParsedTicketRecord],
    games: Sequence[ParsedGameRecord],
    *,
    season: str = "2026-2027",
) -> list[ParsedGameRecord]:
    """Cross-reference ticket offerings with schedule data and enrich games.

    Args:
        tickets: Sequence of parsed ticket and promotional offerings.
        games: Sequence of primary parsed schedule game records.
        season: Collegiate hockey season.

    Returns:
        Updated list of ParsedGameRecord instances with enriched ticketing metadata.
    """
    enriched: list[ParsedGameRecord] = []
    matched_ticket_ids: set[str] = set()

    for game in games:
        matched_ticket = _find_matching_ticket(game, tickets)
        if matched_ticket is not None:
            enriched.append(_enrich_game_with_ticket(game, matched_ticket))
            matched_ticket_ids.add(matched_ticket.ticket_id)
        else:
            enriched.append(game)

    unmatched_games = _collect_unmatched_ticket_games(
        tickets,
        matched_ticket_ids,
        season,
    )
    enriched.extend(unmatched_games)
    return enriched

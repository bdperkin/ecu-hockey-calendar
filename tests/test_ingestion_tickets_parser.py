"""Unit tests for the ECU Hockey ticketing and promotional theme parser."""

# pylint: disable=too-many-locals

from __future__ import annotations

from datetime import UTC, datetime

from bs4 import BeautifulSoup, Tag

from ecu_hockey_calendar.ingestion.html_parser import ParsedGameRecord
from ecu_hockey_calendar.ingestion.tickets_parser import (
    ParsedTicketRecord,
    TicketPriceTier,
    _clean_opponent_text,
    _enrich_game_with_ticket,
    _extract_card_datetime,
    _extract_card_title_and_link,
    _get_map_int,
    _get_map_str,
    _matches_game_and_ticket,
    _parse_firestore_event_time,
    _parse_firestore_price_values,
    _parse_single_ticket_card,
    cross_reference_tickets_with_games,
    extract_opponent_from_title,
    extract_promotional_theme,
    identify_ticketing_vendor,
    parse_firestore_ticket_doc,
    parse_firestore_tickets_response,
    parse_html_ticket_listings,
    parse_price_text,
)

SAMPLE_FIRESTORE_TICKET_DOC = {
    "document": {
        "name": (
            "projects/optimx-sports/databases/(default)/documents/tickets/lnjlh6od"
        ),
        "fields": {
            "id": {"stringValue": "lnjlh6od"},
            "title": {"stringValue": "ECU vs NC State - Military Appreciation"},
            "eventTitle": {
                "stringValue": "ECU vs NC State - Military Appreciation",
            },
            "timeOfEvent": {"timestampValue": "2026-10-18T23:00:00Z"},
            "eventVenue": {"stringValue": "The Factory Ice House"},
            "shortDescription": {
                "stringValue": "Military Appreciation Night! Discounted tickets.",
            },
            "priceDescription": {"stringValue": "From $5 to $15"},
            "inStock": {"booleanValue": True},
            "published": {"booleanValue": True},
            "deleted": {"booleanValue": False},
            "stripeAccountId": {"stringValue": "acct_test123"},
            "stripeProductId": {"stringValue": "prod_test456"},
            "prices": {
                "arrayValue": {
                    "values": [
                        {
                            "mapValue": {
                                "fields": {
                                    "id": {"stringValue": "t1"},
                                    "title": {
                                        "stringValue": "General Admission",
                                    },
                                    "price": {"integerValue": "500"},
                                    "currency": {"stringValue": "usd"},
                                    "description": {"stringValue": "Standard"},
                                },
                            },
                        },
                        {
                            "mapValue": {
                                "fields": {
                                    "id": {"stringValue": "t2"},
                                    "title": {"stringValue": "VIP Balcony"},
                                    "price": {"integerValue": "1500"},
                                    "currency": {"stringValue": "usd"},
                                    "description": {"stringValue": "Balcony"},
                                },
                            },
                        },
                    ],
                },
            },
        },
    },
}

SAMPLE_HTML_TICKETS = """
<div class="tickets-container">
    <div class="ticket-card" id="card-1">
        <h3 class="ticket-name">ECU vs Duke - Teddy Bear Toss</h3>
        <time class="event-date">Oct 24, 2026 7:00 PM</time>
        <span class="location">Wake Forest Rink</span>
        <div class="cost">$10.00</div>
        <a class="checkout" href="https://www.etix.com/ticket/p/12345">Buy Tickets</a>
    </div>
    <div class="ticket-card" id="card-2">
        <h3 class="ticket-name">ECU vs Charlotte - Pink in the Rink</h3>
        <time class="event-date">Nov 14, 2026 8:00 PM</time>
        <span class="location">Pineville Ice House</span>
        <div class="cost">From $8 to $20</div>
        <a class="checkout" href="/tickets/charlotte-tix">Buy Tickets</a>
    </div>
    <div class="ticket-card" id="card-3">
        <h3 class="ticket-name">Community Raffle Drawing</h3>
        <time class="event-date">Nov 15, 2026 12:00 PM</time>
        <span class="location">Greenville, NC</span>
        <div class="cost">Free</div>
        <a class="checkout" href="/tickets/raffle">Enter Raffle</a>
    </div>
</div>
"""


def test_extract_promotional_theme_all_variants() -> None:
    """Verify promotional theme extraction across all predefined patterns."""
    assert (
        extract_promotional_theme("Military Appreciation Night Game")
        == "Military Appreciation Night"
    )
    assert extract_promotional_theme("Annual Teddy Bear Toss!") == "Teddy Bear Toss"
    assert (
        extract_promotional_theme("Bring your dog to Pucks & Paws!") == "Pucks & Paws"
    )
    assert extract_promotional_theme("Pups at the Rink Night") == "Pucks & Paws"
    assert (
        extract_promotional_theme("Pink in the Rink for Breast Cancer")
        == "Pink in the Rink"
    )
    assert extract_promotional_theme("Senior Night 2026") == "Senior Night"
    assert extract_promotional_theme("Alumni Weekend Matchup") == "Alumni Weekend"
    assert (
        extract_promotional_theme("Youth Hockey Night & Kids Day")
        == "Youth Hockey Night"
    )
    assert extract_promotional_theme("Star Wars Night") == "Star Wars Night"
    assert extract_promotional_theme("80s Retro Night") == "Retro Night"
    assert extract_promotional_theme("St. Patrick's Day") == "St. Patrick's Day"
    assert (
        extract_promotional_theme("Give Back to Greenville Day")
        == "Give Back to Greenville Day"
    )
    assert (
        extract_promotional_theme("ACCHL Outdoor Classic in Raleigh")
        == "ACCHL Outdoor Classic"
    )
    assert (
        extract_promotional_theme("Playoff Championship Game")
        == "Playoffs / Tournament"
    )
    assert extract_promotional_theme("Wear white for Whiteout") == "Whiteout"
    assert extract_promotional_theme("Blackout the arena") == "Blackout"
    assert extract_promotional_theme("Gold Rush Friday") == "Gold Rush"
    assert extract_promotional_theme("Hawaiian Beach Night") == "Hawaiian Night"
    assert extract_promotional_theme("Raffle Drawing Ticket") == "Raffle Drawing"
    assert extract_promotional_theme("Regular Season Matchup") is None
    assert extract_promotional_theme(None) is None
    assert extract_promotional_theme("") is None


def test_parse_price_text() -> None:
    """Verify numeric and textual price parsing."""
    assert parse_price_text("$10") == (10.0, 10.0)
    assert parse_price_text("$12.50") == (12.5, 12.5)
    assert parse_price_text("$5 - $15") == (5.0, 15.0)
    assert parse_price_text("From $1 USD to $15 USD") == (1.0, 15.0)
    assert parse_price_text("Free") == (0.0, 0.0)
    assert parse_price_text("Free Admission") == (0.0, 0.0)
    assert parse_price_text("TBD") == (None, None)
    assert parse_price_text("N/A") == (None, None)
    assert parse_price_text("") == (None, None)
    assert parse_price_text(None) == (None, None)
    assert parse_price_text("No price information available") == (None, None)


def test_identify_ticketing_vendor() -> None:
    """Verify vendor recognition from URLs."""
    assert identify_ticketing_vendor("https://www.etix.com/ticket/p/12345") == "etix"
    assert (
        identify_ticketing_vendor("https://www.eventbrite.com/e/12345") == "eventbrite"
    )
    assert (
        identify_ticketing_vendor(
            "https://www.ticketmaster.com/event/12345",
        )
        == "ticketmaster"
    )
    assert identify_ticketing_vendor("https://seatgeek.com/event/123") == "seatgeek"
    assert identify_ticketing_vendor("https://www.axs.com/events/123") == "axs"
    assert identify_ticketing_vendor("https://gofan.co/event/123") == "gofan"
    assert (
        identify_ticketing_vendor(
            "https://www.ecuhockey.com/tickets/123",
        )
        == "optimx"
    )
    assert identify_ticketing_vendor("https://rinkside-tickets.org/cart") == "external"
    assert identify_ticketing_vendor("") == "unknown"
    assert identify_ticketing_vendor(None) == "unknown"


def test_extract_opponent_from_title() -> None:
    """Verify home/away and opponent parsing from titles."""
    # ECU vs Opponent -> Home
    opp, is_home = extract_opponent_from_title(
        "ECU vs NC State - Military Night",
    )
    assert opp == "NC State University"
    assert is_home

    # ECU vs. Duke
    opp2, is_home2 = extract_opponent_from_title("ECU vs. Duke")
    assert opp2 == "Duke University"
    assert is_home2

    # ECU @ UNC -> Away
    opp3, is_home3 = extract_opponent_from_title("ECU @ UNC")
    assert opp3 == "UNC Chapel Hill"
    assert not is_home3

    # UNC vs ECU -> Away
    opp4, is_home4 = extract_opponent_from_title("UNC vs ECU")
    assert opp4 == "UNC Chapel Hill"
    assert not is_home4

    # Game vs Charlotte on 09-16-2022 -> Home
    opp5, is_home5 = extract_opponent_from_title(
        "Game vs Charlotte on 09-16-2022",
    )
    assert opp5 == "UNC Charlotte"
    assert is_home5

    # Non-game event
    opp6, is_home6 = extract_opponent_from_title("Community Raffle Drawing")
    assert opp6 is None
    assert is_home6

    # None and empty
    assert extract_opponent_from_title(None) == (None, True)
    assert extract_opponent_from_title("") == (None, True)


def test_ticket_price_tier_and_parsed_record() -> None:
    """Verify TicketPriceTier properties and conversion to ParsedGameRecord."""
    tier = TicketPriceTier(name="GA", price_cents=1250, description="General")
    assert tier.price_dollars == 12.5

    now_utc = datetime(2026, 10, 24, 23, 0, tzinfo=UTC)
    rec = ParsedTicketRecord(
        ticket_id="t-100",
        title="ECU vs Duke",
        opponent_name="Duke University",
        start_time=now_utc,
        venue="The Factory",
        promotion="Senior Night",
        ticket_url="https://www.ecuhockey.com/tickets/t-100",
        price_min=10.0,
        price_max=20.0,
        prices=(tier,),
    )
    game = rec.to_parsed_game_record(season="2026-2027")
    assert game is not None
    assert game.opponent_name == "Duke University"
    assert game.is_home
    assert game.start_time == now_utc
    assert game.venue == "The Factory"
    assert game.metadata is not None
    assert game.metadata["ticket_id"] == "t-100"
    assert game.metadata["promotion"] == "Senior Night"

    # Non-game ticket (missing opponent or start_time) returns None
    rec_no_opp = ParsedTicketRecord(
        ticket_id="t-200",
        title="Raffle",
        start_time=now_utc,
    )
    assert rec_no_opp.to_parsed_game_record() is None


def test_parse_firestore_ticket_doc() -> None:
    """Verify parsing Firestore ticket documents."""
    rec = parse_firestore_ticket_doc(SAMPLE_FIRESTORE_TICKET_DOC["document"])
    assert rec is not None
    assert rec.ticket_id == "lnjlh6od"
    assert rec.opponent_name == "NC State University"
    assert rec.is_home_game
    assert rec.venue == "The Factory Ice House"
    assert rec.price_min == 5.0
    assert rec.price_max == 15.0
    assert len(rec.prices) == 2
    assert rec.promotion == "Military Appreciation Night"
    assert rec.ticket_url == "https://www.ecuhockey.com/tickets/lnjlh6od"

    # Deleted document returns None
    del_doc = {
        "fields": {
            "deleted": {"booleanValue": True},
            "title": {"stringValue": "Test"},
        },
    }
    assert parse_firestore_ticket_doc(del_doc) is None

    # Missing fields or title returns None
    assert parse_firestore_ticket_doc({}) is None
    assert (
        parse_firestore_ticket_doc({"fields": {"title": {"stringValue": ""}}}) is None
    )

    # Out-of-stock document with missing id field falls back to name attribute
    out_of_stock_doc = {
        "fields": {
            "title": {"stringValue": "ECU vs Duke"},
            "inStock": {"booleanValue": False},
        },
        "name": "projects/optimx/databases/(default)/documents/tickets/t-oos",
    }
    rec_oos = parse_firestore_ticket_doc(out_of_stock_doc)
    assert rec_oos is not None
    assert rec_oos.ticket_id == "t-oos"
    assert rec_oos.in_stock is False


def test_parse_firestore_tickets_response() -> None:
    """Verify parsing list of Firestore document query results."""
    records = parse_firestore_tickets_response([SAMPLE_FIRESTORE_TICKET_DOC])
    assert len(records) == 1
    assert records[0].ticket_id == "lnjlh6od"

    # Single dictionary response rather than sequence
    recs_single = parse_firestore_tickets_response(SAMPLE_FIRESTORE_TICKET_DOC)
    assert len(recs_single) == 1
    assert recs_single[0].ticket_id == "lnjlh6od"

    # Empty or non-dict items
    assert not parse_firestore_tickets_response([])
    assert not parse_firestore_tickets_response([{}])  # type: ignore[list-item]


def test_parse_html_ticket_listings() -> None:
    """Verify parsing HTML ticket cards and listings."""
    records = parse_html_ticket_listings(
        SAMPLE_HTML_TICKETS,
        season="2026-2027",
    )
    assert len(records) == 3

    r1 = records[0]
    assert r1.ticket_id == "card-1"
    assert r1.opponent_name == "Duke University"
    assert r1.promotion == "Teddy Bear Toss"
    assert r1.venue == "Wake Forest Rink"
    assert r1.price_min == 10.0
    assert r1.ticket_url == "https://www.etix.com/ticket/p/12345"

    r2 = records[1]
    assert r2.ticket_id == "card-2"
    assert r2.opponent_name == "UNC Charlotte"
    assert r2.promotion == "Pink in the Rink"
    assert r2.price_min == 8.0
    assert r2.price_max == 20.0
    assert "https://www.ecuhockey.com/tickets/charlotte-tix" in r2.ticket_url

    r3 = records[2]
    assert r3.ticket_id == "card-3"
    assert r3.opponent_name is None
    assert r3.promotion == "Raffle Drawing"
    assert r3.price_min == 0.0


def test_cross_reference_tickets_with_games() -> None:
    """Verify enriching existing games and appending newly discovered ticket games."""
    dt_duke = datetime(2026, 10, 24, 23, 0, tzinfo=UTC)
    dt_ncsu = datetime(2026, 10, 18, 23, 0, tzinfo=UTC)
    dt_charlotte = datetime(2026, 11, 14, 23, 0, tzinfo=UTC)

    game_duke = ParsedGameRecord(
        game_id="game-duke-1",
        opponent_name="Duke University",
        is_home=True,
        start_time=dt_duke,
        venue="TBD",
    )
    ticket_duke = ParsedTicketRecord(
        ticket_id="t-duke",
        title="ECU vs Duke",
        opponent_name="Duke University",
        start_time=dt_duke,
        venue="Wake Forest Rink",
        promotion="Teddy Bear Toss",
        ticket_url="https://www.etix.com/ticket/p/123",
        price_min=10.0,
        price_max=15.0,
    )
    # Ticket for game not in schedule (NC State)
    ticket_ncsu = ParsedTicketRecord(
        ticket_id="t-ncsu",
        title="ECU vs NC State",
        opponent_name="NC State University",
        start_time=dt_ncsu,
        venue="The Factory",
        promotion="Military Appreciation Night",
        ticket_url="https://www.ecuhockey.com/tickets/ncsu",
        price_min=5.0,
    )
    # Raffle ticket (non-game)
    ticket_raffle = ParsedTicketRecord(
        ticket_id="t-raffle",
        title="Raffle Ticket",
        start_time=dt_charlotte,
        promotion="Raffle Drawing",
    )

    enriched = cross_reference_tickets_with_games(
        [ticket_duke, ticket_ncsu, ticket_raffle],
        [game_duke],
    )

    assert len(enriched) == 2
    duke_res = enriched[0]
    assert duke_res.venue == "Wake Forest Rink"  # Updated from TBD
    assert duke_res.metadata is not None
    assert duke_res.metadata["ticket_id"] == "t-duke"
    assert duke_res.metadata["promotion"] == "Teddy Bear Toss"
    assert duke_res.metadata["ticketing_vendor"] == "etix"

    ncsu_res = enriched[1]
    assert ncsu_res.opponent_name == "NC State University"
    assert ncsu_res.metadata is not None
    assert ncsu_res.metadata["promotion"] == "Military Appreciation Night"


def test_parser_edge_branches() -> None:
    """Verify internal edge cases and helpers for complete branch coverage."""
    # _clean_opponent_text regex branches
    text1 = "Elon on Oct 4th - Theme"
    assert _clean_opponent_text(text1) == "Elon"

    # _matches_game_and_ticket with start_time None
    g = ParsedGameRecord(
        game_id="g1",
        opponent_name="Duke",
        is_home=True,
        start_time=datetime(2026, 10, 24, 23, 0, tzinfo=UTC),
        venue="TBD",
    )
    t_no_time = ParsedTicketRecord(ticket_id="t1", title="Title")
    assert not _matches_game_and_ticket(g, t_no_time)

    # _matches_game_and_ticket different day
    t_diff_day = ParsedTicketRecord(
        ticket_id="t2",
        title="ECU vs Duke",
        opponent_name="Duke",
        start_time=datetime(2026, 10, 25, 23, 0, tzinfo=UTC),
    )
    assert not _matches_game_and_ticket(g, t_diff_day)

    # _matches_game_and_ticket same day, opponent_name None
    t_no_opp = ParsedTicketRecord(
        ticket_id="t3",
        title="ECU Hockey Game Ticket",
        opponent_name=None,
        start_time=datetime(2026, 10, 24, 23, 0, tzinfo=UTC),
    )
    assert _matches_game_and_ticket(g, t_no_opp)

    # extract_opponent_from_title variations
    opp, is_home = extract_opponent_from_title("UNC @ ECU")
    assert opp == "UNC Chapel Hill"
    assert is_home

    opp_none, is_home_none = extract_opponent_from_title("Duke @ UNC")
    assert opp_none is None
    assert is_home_none

    opp_pref, is_home_pref = extract_opponent_from_title("Game vs UNCW")
    assert opp_pref == "UNC Wilmington"
    assert is_home_pref


def test_firestore_parser_edge_branches() -> None:
    """Verify internal Firestore mapping and event time fallback branches."""
    # Map helpers fallback branches
    assert _get_map_str({}, "missing", "default_val") == "default_val"
    assert _get_map_int({}, "missing", 42) == 42
    assert _get_map_int({"val": {"integerValue": "not-an-int"}}, "val", 99) == 99

    # _parse_firestore_price_values non-dict and invalid structures
    assert _parse_firestore_price_values({}) == ([], None, None)
    assert _parse_firestore_price_values({"arrayValue": "not-a-dict"}) == (
        [],
        None,
        None,
    )
    assert _parse_firestore_price_values(
        {"arrayValue": {"values": "not-a-list"}},
    ) == ([], None, None)
    assert _parse_firestore_price_values(
        {"arrayValue": {"values": ["not-a-dict", 123]}},
    ) == ([], None, None)
    assert _parse_firestore_price_values(
        {"arrayValue": {"values": [{"mapValue": {}}, {"mapValue": {"fields": {}}}]}},
    ) == ([], None, None)

    # _parse_firestore_event_time invalid timestamp and non-timestamp
    assert (
        _parse_firestore_event_time(
            {"timeOfEvent": {"timestampValue": "bad-date"}},
        )
        is None
    )
    assert (
        _parse_firestore_event_time(
            {"timeOfEvent": {"stringValue": "not-a-timestamp"}},
        )
        is None
    )
    assert _parse_firestore_event_time(
        {
            "timeOfEvent": None,
            "validFrom": {"timestampValue": "2026-10-24T20:00:00Z"},
        },
    ) == datetime(2026, 10, 24, 20, 0, tzinfo=UTC)

    # parse_firestore_tickets_response with non-dict items and deleted docs
    bad_items = [
        "not-a-dict",
        123,
        {"document": None},
        {"document": {"fields": {"deleted": {"booleanValue": True}}}},
    ]
    assert not parse_firestore_tickets_response(bad_items)


def test_card_parser_edge_branches() -> None:
    """Verify HTML card title, date, and link extraction edge branches."""
    soup_link_only = BeautifulSoup(
        '<div><a href="/tickets/link-only">ECU vs Richmond</a></div>',
        "html.parser",
    ).find("div")
    assert isinstance(soup_link_only, Tag)
    t_text, link_url = _extract_card_title_and_link(
        soup_link_only,
        "https://www.ecuhockey.com",
    )
    assert t_text == "ECU vs Richmond"
    assert link_url == "https://www.ecuhockey.com/tickets/link-only"

    # _extract_card_title_and_link without title or link
    soup_empty = BeautifulSoup("<div></div>", "html.parser").find("div")
    assert soup_empty is not None
    assert _extract_card_title_and_link(
        soup_empty,
        "https://www.ecuhockey.com",
    ) == ("", "")

    # _extract_card_datetime missing tag and empty date text
    soup_no_date = BeautifulSoup(
        "<div><h3>ECU vs Duke</h3></div>",
        "html.parser",
    ).find("div")
    assert isinstance(soup_no_date, Tag)
    assert _extract_card_datetime(soup_no_date, "2026-2027") is None

    soup_empty_time = BeautifulSoup(
        "<div><time>   </time></div>",
        "html.parser",
    ).find("div")
    assert isinstance(soup_empty_time, Tag)
    assert _extract_card_datetime(soup_empty_time, "2026-2027") is None

    soup_bad_dt = BeautifulSoup(
        "<div><time>InvalidDate</time></div>",
        "html.parser",
    ).find("div")
    assert soup_bad_dt is not None
    assert _extract_card_datetime(soup_bad_dt, "2026-2027") is None

    # _parse_single_ticket_card card with no title/link returns None
    soup_no_title = BeautifulSoup(
        '<div class="ticket-card"><span class="price">$10</span></div>',
        "html.parser",
    ).find("div")
    assert isinstance(soup_no_title, Tag)
    assert (
        _parse_single_ticket_card(
            soup_no_title,
            1,
            "https://www.ecuhockey.com",
            "2026-2027",
        )
        is None
    )


def test_html_parsing_fallbacks_and_empty_elements() -> None:
    """Verify fallback HTML selector branches and element skipping."""
    # Fallback 1: event-item class
    html_fallback_item = """
    <section>
        <div class="event-item">
            <h3>ECU vs Duke</h3>
            <time>Oct 24, 2026 7:00 PM</time>
        </div>
    </section>
    """
    recs1 = parse_html_ticket_listings(html_fallback_item, season="2026-2027")
    assert len(recs1) == 1
    assert recs1[0].opponent_name == "Duke University"

    # Fallback 2: event class without child ticket/event
    html_fallback_event = """
    <section>
        <article class="event">
            <h3>ECU vs NC State</h3>
            <time>Oct 18, 2026 7:00 PM</time>
        </article>
    </section>
    """
    recs2 = parse_html_ticket_listings(html_fallback_event, season="2026-2027")
    assert len(recs2) == 1
    assert recs2[0].opponent_name == "NC State University"

    # Empty cards list / non-tag items
    html_with_empty_card = """
    <div>
        <div class="ticket-card"></div>
    </div>
    """
    assert not parse_html_ticket_listings(
        html_with_empty_card,
        season="2026-2027",
    )


def test_enrich_game_branches_and_cross_reference() -> None:
    """Verify branches in _enrich_game_with_ticket and
    cross_reference_tickets_with_games.
    """
    dt = datetime(2026, 10, 24, 23, 0, tzinfo=UTC)
    game_known_venue = ParsedGameRecord(
        game_id="game-1",
        opponent_name="Duke University",
        is_home=True,
        start_time=dt,
        venue="The Factory Ice House",
    )
    # Ticket without promotion or prices
    ticket_minimal = ParsedTicketRecord(
        ticket_id="t-min",
        title="ECU vs Duke",
        opponent_name="Duke University",
        start_time=dt,
        venue="Wake Forest Ice",
        promotion=None,
        price_min=None,
        price_max=None,
    )

    enriched_game = _enrich_game_with_ticket(game_known_venue, ticket_minimal)
    # Venue was already known, should NOT be overwritten by ticket venue
    assert enriched_game.venue == "The Factory Ice House"
    assert "promotion" not in (enriched_game.metadata or {})
    assert "ticket_price_min" not in (enriched_game.metadata or {})
    assert "ticket_price_max" not in (enriched_game.metadata or {})

    # Unmatched game in cross_reference_tickets_with_games
    game_unmatched = ParsedGameRecord(
        game_id="game-2",
        opponent_name="UNC Chapel Hill",
        is_home=False,
        start_time=datetime(2026, 11, 1, 23, 0, tzinfo=UTC),
        venue="Orange County Sportsplex",
    )

    # First ticket doesn't match game-2, second ticket also doesn't match game-2
    # game_known_venue matches ticket_minimal
    results = cross_reference_tickets_with_games(
        [ticket_minimal],
        [game_unmatched, game_known_venue],
    )
    assert len(results) == 2
    assert results[0].game_id == "game-2"
    assert results[1].game_id == "game-1"

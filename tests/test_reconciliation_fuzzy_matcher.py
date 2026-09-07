"""Unit tests for opponent and venue fuzzy matching algorithms."""

import pytest

from ecu_hockey_calendar.reconciliation.fuzzy_matcher import (
    DEFAULT_OPPONENT_MATCH_THRESHOLD,
    DEFAULT_VENUE_MATCH_THRESHOLD,
    _evaluate_stripped_match,
    _score_exact_canonical,
    _score_sequence_ratio,
    _score_stripped_mascot,
    _score_token_overlap,
    compute_opponent_similarity,
    compute_venue_similarity,
    extract_significant_tokens,
    is_opponent_match,
    is_venue_match,
    is_venue_unspecified,
    strip_mascot_terms,
)


def test_strip_mascot_terms() -> None:
    """Verify mascot and generic token stripping for opponent names."""
    assert strip_mascot_terms("") == ""
    assert strip_mascot_terms("   ") == ""
    assert strip_mascot_terms("NC State University Icepack") == "nc state university"
    assert strip_mascot_terms("UNC Chapel Hill Tar Heels") == "unc chapel hill"
    assert strip_mascot_terms("Duke Blue Devils Hockey Club") == "duke"
    assert strip_mascot_terms("Virginia Tech Hokies Hockey Club") == "virginia tech"
    # When all tokens are removed, fall back to cleaned string
    assert strip_mascot_terms("Club Ice Hockey") == "club ice hockey"


@pytest.mark.parametrize(
    ("venue", "expected"),
    [
        (None, True),
        ("", True),
        ("   ", True),
        ("TBD", True),
        ("tba", True),
        ("Unknown", True),
        ("To Be Determined", True),
        ("N/A", True),
        ("Rink TBD", True),
        ("Various", True),
        ("The Factory Ice House", False),
        ("Invisalign Arena", False),
        ("Orange County Sportsplex", False),
    ],
)
def test_is_venue_unspecified(venue: str | None, *, expected: bool) -> None:
    """Verify identification of unspecified, placeholder, or missing venues."""
    assert is_venue_unspecified(venue) is expected


def test_compute_opponent_similarity_exact_and_empty() -> None:
    """Verify boundary cases for empty strings and identical opponent names."""
    assert compute_opponent_similarity("", "UNC") == 0.0
    assert compute_opponent_similarity("Duke", "") == 0.0
    assert compute_opponent_similarity("UNC Chapel Hill", "unc chapel hill") == 1.0


def test_compute_opponent_similarity_mascot_variants() -> None:
    """Verify opponent matching across mascot differences and monikers."""
    sim = compute_opponent_similarity("NC State University", "NC State Icepack")
    assert sim >= 0.85
    assert is_opponent_match("NC State University", "NC State Icepack")

    sim2 = compute_opponent_similarity("UNC Wilmington", "UNCW Seahawks")
    assert sim2 >= 0.70
    assert is_opponent_match("UNC Wilmington", "UNCW Seahawks")

    sim3 = compute_opponent_similarity("Duke University", "Duke Blue Devils")
    assert sim3 >= 0.85
    assert is_opponent_match("Duke University", "Duke Blue Devils")


def test_compute_opponent_similarity_non_matches() -> None:
    """Verify distinct opponents do not match."""
    sim = compute_opponent_similarity("NC State", "Virginia Tech")
    assert sim < DEFAULT_OPPONENT_MATCH_THRESHOLD
    assert not is_opponent_match("NC State", "Virginia Tech")

    assert not is_opponent_match(
        "Wake Forest",
        "UNC Charlotte",
        threshold=DEFAULT_OPPONENT_MATCH_THRESHOLD,
    )


def test_compute_venue_similarity_unspecified_and_exact() -> None:
    """Verify neutral scores for unspecified venues and 1.0 for exact matches."""
    assert compute_venue_similarity("TBD", "The Factory Ice House") == 0.5
    assert compute_venue_similarity("Invisalign Arena", "") == 0.5
    assert compute_venue_similarity(None, None) == 0.5

    assert (
        compute_venue_similarity("The Factory Ice House", "The Factory Ice House")
        == 1.0
    )


def test_compute_venue_similarity_aliases() -> None:
    """Verify canonical arena aliases resolve with high similarity."""
    sim1 = compute_venue_similarity("The Factory", "Factory Ice House Wake Forest")
    assert sim1 >= 0.90
    assert is_venue_match("The Factory", "Factory Ice House Wake Forest")

    sim2 = compute_venue_similarity("Invisalign Arena", "Polar Ice House Morrisville")
    assert sim2 >= 0.90
    assert is_venue_match("Invisalign Arena", "Polar Ice House Morrisville")

    sim3 = compute_venue_similarity("Orange County Sportsplex", "OC Sportsplex")
    assert sim3 >= 0.80
    assert is_venue_match("Orange County Sportsplex", "OC Sportsplex")


def test_is_venue_match_logic() -> None:
    """Verify is_venue_match thresholding and fallback logic."""
    # When one is unspecified, it matches (non-contradictory)
    assert is_venue_match("TBD", "The Factory Ice House")
    assert is_venue_match("The Factory Ice House", None)

    # Discrepant venues
    assert not is_venue_match(
        "The Factory Ice House",
        "Orange County Sportsplex",
        threshold=DEFAULT_VENUE_MATCH_THRESHOLD,
    )


def test_fuzzy_matcher_internal_scorers() -> None:
    """Verify internal scoring functions and branch conditions."""
    # _score_exact_canonical with clean string match when norm doesn't match
    score1 = _score_exact_canonical("Unknown School!!", "Unknown School")
    assert score1 == 1.0

    # _evaluate_stripped_match
    assert _evaluate_stripped_match("elon", "elon") == 0.98
    # normalized match on stripped names
    assert _evaluate_stripped_match("elon", "elon university") == 0.98
    assert _evaluate_stripped_match("duke", "wake forest") == 0.0

    # _score_stripped_mascot with empty stripped string
    assert _score_stripped_mascot("", "UNC") == 0.0
    assert _score_stripped_mascot("UNC", "") == 0.0

    # _score_token_overlap
    assert _score_token_overlap(set(), {"unc"}) == 0.0
    assert _score_token_overlap({"unc"}, set()) == 0.0
    assert _score_token_overlap({"nc", "state"}, {"state"}) == 0.95
    assert (
        0.0
        < _score_token_overlap({"nc", "state", "club"}, {"nc", "state", "mens"})
        < 0.95
    )

    # _score_sequence_ratio with empty clean strings
    assert _score_sequence_ratio("", "Duke") == 0.0
    assert _score_sequence_ratio("Duke", "") == 0.0

    # extract_significant_tokens
    toks = extract_significant_tokens("University of North Carolina at Chapel Hill")
    assert "university" not in toks
    assert "of" not in toks
    assert "carolina" in toks


def test_compute_venue_similarity_substring_non_alias() -> None:
    """Verify venue substring match when not defined in VENUE_ALIASES."""
    sim = compute_venue_similarity("Apex Ice Center East", "Apex Ice Center")
    assert sim == 1.0

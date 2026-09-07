"""Deterministic and fuzzy string matching for opponents and venues.

This module implements algorithms to match opponent institutions across
different naming conventions, abbreviations, and collegiate club monikers
(e.g., 'NC State University' vs 'NC State Icepack'), as well as fuzzy venue
matching.
"""

from __future__ import annotations

import difflib
import re

from ecu_hockey_calendar.ingestion.normalizer import normalize_team_name

DEFAULT_OPPONENT_MATCH_THRESHOLD = 0.80
DEFAULT_VENUE_MATCH_THRESHOLD = 0.70
PERFECT_MATCH_SCORE = 1.0
STRIPPED_MASCOT_MATCH_SCORE = 0.98
TOKEN_SUBSET_MATCH_SCORE = 0.95
NEUTRAL_VENUE_SCORE = 0.50

# Collegiate hockey club nicknames and monikers
KNOWN_MASCOTS: tuple[str, ...] = (
    "icepack",
    "ice pack",
    "tar heels",
    "tarheels",
    "hokies",
    "demon deacons",
    "deacons",
    "blue devils",
    "seahawks",
    "mountaineers",
    "panthers",
    "phoenix",
    "49ers",
    "dukes",
    "spiders",
    "cavaliers",
    "hoyas",
    "pirates",
    "yellow jackets",
    "tigers",
    "crimson tide",
    "hawks",
    "profs",
    "bobcats",
)

# Generic collegiate athletics terms to strip for core token matching
GENERIC_COLLEGE_TERMS: tuple[str, ...] = (
    "ice hockey club",
    "mens ice hockey",
    "mens hockey",
    "ice hockey",
    "hockey club",
    "hockey",
    "club",
    "team",
    "university",
    "univ",
    "college",
)

# Known arena and venue aliases
VENUE_ALIASES: dict[str, str] = {
    "factory": "The Factory Ice House",
    "factory ice house": "The Factory Ice House",
    "the factory": "The Factory Ice House",
    "the factory ice house": "The Factory Ice House",
    "factory ice house wake forest": "The Factory Ice House",
    "orange county sportsplex": "Orange County Sportsplex",
    "oc sportsplex": "Orange County Sportsplex",
    "sportsplex": "Orange County Sportsplex",
    "wake competition center": "Wake Competition Center",
    "wake comp center": "Wake Competition Center",
    "wcc": "Wake Competition Center",
    "winston-salem fairgrounds annex": "Winston-Salem Fairgrounds Annex",
    "fairgrounds annex": "Winston-Salem Fairgrounds Annex",
    "annex": "Winston-Salem Fairgrounds Annex",
    "invisalign arena": "Invisalign Arena",
    "invisalign": "Invisalign Arena",
    "polar ice house": "Invisalign Arena",
    "polar ice house morrisville": "Invisalign Arena",
    "lancerlot": "Lancerlot Sports Complex",
    "lancerlot sports complex": "Lancerlot Sports Complex",
    "wilmington ice house": "Wilmington Ice House",
    "appstate rink": "AppState Rink",
    "greensboro ice house": "Greensboro Ice House",
    "pineville icehouse": "Pineville IceHouse",
    "haymarket iceplex": "Haymarket Iceplex",
    "richmond ice zone": "Richmond Ice Zone",
    "main street arena": "Main Street Arena",
    "fort dupont ice arena": "Fort Dupont Ice Arena",
}


def clean_string_for_matching(text: str | None) -> str:
    """Normalize whitespace and strip punctuation for matching.

    Args:
        text: Input string or None.

    Returns:
        Lowercased, stripped string with single spaces.
    """
    if not text:
        return ""

    no_punct = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", no_punct).strip().lower()


def strip_mascot_terms(text: str) -> str:
    """Remove known collegiate mascots and club suffixes from name.

    Args:
        text: Raw or normalized opponent name.

    Returns:
        String stripped of mascot names and sport suffixes.
    """
    cleaned = clean_string_for_matching(text)
    for mascot in KNOWN_MASCOTS:
        pattern = rf"\b{re.escape(mascot)}\b"
        cleaned = re.sub(pattern, " ", cleaned)

    for term in ("ice hockey", "hockey club", "hockey", "club", "team"):
        pattern = rf"\b{re.escape(term)}\b"
        cleaned = re.sub(pattern, " ", cleaned)

    res = re.sub(r"\s+", " ", cleaned).strip()
    if not res:
        return clean_string_for_matching(text)

    return res


def extract_significant_tokens(text: str) -> set[str]:
    """Extract significant lowercase tokens excluding generic terms.

    Args:
        text: Input name string.

    Returns:
        Set of significant token strings.
    """
    stripped = strip_mascot_terms(text)
    raw_tokens = stripped.split()
    generic_words = {"university", "univ", "college", "the", "of", "and", "at"}
    return {t for t in raw_tokens if t not in generic_words and len(t) > 1}


def _score_exact_canonical(name_a: str, name_b: str) -> float:
    """Score exact canonical name equivalence."""
    norm_a = normalize_team_name(name_a).lower()
    norm_b = normalize_team_name(name_b).lower()
    if norm_a == norm_b and bool(norm_a):
        return PERFECT_MATCH_SCORE

    clean_a = clean_string_for_matching(name_a)
    clean_b = clean_string_for_matching(name_b)
    if clean_a == clean_b and bool(clean_a):
        return PERFECT_MATCH_SCORE

    return 0.0


def _evaluate_stripped_match(s_a: str, s_b: str) -> float:
    """Evaluate equality of stripped opponent names."""
    if s_a == s_b:
        return STRIPPED_MASCOT_MATCH_SCORE

    norm_a = normalize_team_name(s_a).lower()
    norm_b = normalize_team_name(s_b).lower()
    if norm_a == norm_b and bool(norm_a):
        return STRIPPED_MASCOT_MATCH_SCORE

    return 0.0


def _score_stripped_mascot(name_a: str, name_b: str) -> float:
    """Score matching after stripping club and mascot suffixes."""
    s_a = strip_mascot_terms(name_a)
    s_b = strip_mascot_terms(name_b)
    if not s_a or not s_b:
        return 0.0

    return _evaluate_stripped_match(s_a, s_b)


def _is_subset_overlap(tokens_a: set[str], tokens_b: set[str]) -> bool:
    """Check if either token set is a subset of the other."""
    return tokens_a.issubset(tokens_b) or tokens_b.issubset(tokens_a)


def _score_token_overlap(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Score token overlap between significant token sets."""
    if not tokens_a or not tokens_b:
        return 0.0

    if _is_subset_overlap(tokens_a, tokens_b):
        return TOKEN_SUBSET_MATCH_SCORE

    union = tokens_a | tokens_b
    return float(len(tokens_a & tokens_b) / len(union)) if union else 0.0


def _score_sequence_ratio(name_a: str, name_b: str) -> float:
    """Score string similarity using SequenceMatcher."""
    clean_a = clean_string_for_matching(name_a)
    clean_b = clean_string_for_matching(name_b)
    if not clean_a or not clean_b:
        return 0.0

    ratio_full = difflib.SequenceMatcher(None, clean_a, clean_b).ratio()
    strip_a = strip_mascot_terms(name_a)
    strip_b = strip_mascot_terms(name_b)
    ratio_strip = (
        difflib.SequenceMatcher(None, strip_a, strip_b).ratio()
        if strip_a and strip_b
        else 0.0
    )
    return max(ratio_full, ratio_strip)


def compute_opponent_similarity(name_a: str, name_b: str) -> float:
    """Calculate composite similarity score between two opponent team names.

    Evaluates exact canonical matching, mascot-stripped normalization,
    token set overlap, and character sequence similarity.

    Args:
        name_a: First opponent name string.
        name_b: Second opponent name string.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    if not name_a.strip() or not name_b.strip():
        return 0.0

    exact_sc = _score_exact_canonical(name_a, name_b)
    if exact_sc >= PERFECT_MATCH_SCORE:
        return PERFECT_MATCH_SCORE

    stripped_sc = _score_stripped_mascot(name_a, name_b)
    if stripped_sc >= STRIPPED_MASCOT_MATCH_SCORE:
        return STRIPPED_MASCOT_MATCH_SCORE

    toks_a = extract_significant_tokens(name_a)
    toks_b = extract_significant_tokens(name_b)
    token_sc = _score_token_overlap(toks_a, toks_b)
    seq_sc = _score_sequence_ratio(name_a, name_b)

    return max(exact_sc, stripped_sc, token_sc, seq_sc)


def is_opponent_match(
    name_a: str,
    name_b: str,
    threshold: float = DEFAULT_OPPONENT_MATCH_THRESHOLD,
) -> bool:
    """Determine whether two names refer to the same opponent.

    Args:
        name_a: First opponent name.
        name_b: Second opponent name.
        threshold: Minimum similarity threshold (default 0.80).

    Returns:
        True if similarity score meets or exceeds threshold.
    """
    return compute_opponent_similarity(name_a, name_b) >= threshold


def is_venue_unspecified(venue: str | None) -> bool:
    """Check if venue string denotes an unspecified, placeholder, or TBD venue.

    Args:
        venue: Venue text string or None.

    Returns:
        True if venue is TBD, TBA, blank, or None.
    """
    if not venue:
        return True

    clean = clean_string_for_matching(venue)
    return clean in {
        "",
        "tbd",
        "tba",
        "unknown",
        "none",
        "n a",
        "to be determined",
        "rink tbd",
        "various",
    }


def _resolve_canonical_venue(venue: str | None) -> str:
    """Resolve venue alias to canonical arena name if known."""
    clean = clean_string_for_matching(venue)
    return VENUE_ALIASES.get(clean, (venue or "").strip())


def _is_substring_match(str_a: str, str_b: str) -> bool:
    """Check if either non-empty string is contained within the other."""
    return str_a in str_b or str_b in str_a


def compute_venue_similarity(venue_a: str | None, venue_b: str | None) -> float:
    """Calculate similarity score between two venue names.

    Args:
        venue_a: First venue string or None.
        venue_b: Second venue string or None.

    Returns:
        Similarity score between 0.0 and 1.0. Neutral venues return 0.50.
    """
    if is_venue_unspecified(venue_a) or is_venue_unspecified(venue_b):
        return NEUTRAL_VENUE_SCORE

    canon_a = _resolve_canonical_venue(venue_a)
    canon_b = _resolve_canonical_venue(venue_b)
    if clean_string_for_matching(canon_a) == clean_string_for_matching(canon_b):
        return PERFECT_MATCH_SCORE

    clean_a = clean_string_for_matching(venue_a)
    clean_b = clean_string_for_matching(venue_b)
    if _is_substring_match(clean_a, clean_b):
        return PERFECT_MATCH_SCORE

    return difflib.SequenceMatcher(None, clean_a, clean_b).ratio()


def is_venue_match(
    venue_a: str | None,
    venue_b: str | None,
    threshold: float = DEFAULT_VENUE_MATCH_THRESHOLD,
) -> bool:
    """Determine whether two venue strings match or are mutually compatible.

    Args:
        venue_a: First venue string or None.
        venue_b: Second venue string or None.
        threshold: Minimum similarity threshold (default 0.70).

    Returns:
        True if venues match or at least one is unspecified/TBD.
    """
    if is_venue_unspecified(venue_a) or is_venue_unspecified(venue_b):
        return True

    return compute_venue_similarity(venue_a, venue_b) >= threshold


__all__ = [
    "DEFAULT_OPPONENT_MATCH_THRESHOLD",
    "DEFAULT_VENUE_MATCH_THRESHOLD",
    "GENERIC_COLLEGE_TERMS",
    "KNOWN_MASCOTS",
    "NEUTRAL_VENUE_SCORE",
    "PERFECT_MATCH_SCORE",
    "STRIPPED_MASCOT_MATCH_SCORE",
    "TOKEN_SUBSET_MATCH_SCORE",
    "VENUE_ALIASES",
    "clean_string_for_matching",
    "compute_opponent_similarity",
    "compute_venue_similarity",
    "extract_significant_tokens",
    "is_opponent_match",
    "is_venue_match",
    "is_venue_unspecified",
    "strip_mascot_terms",
]

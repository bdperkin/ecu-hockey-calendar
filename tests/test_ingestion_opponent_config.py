"""Unit tests for opponent YAML configuration loader and schema validation."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from ecu_hockey_calendar.ingestion.opponent_config import (
    OpponentConfigError,
    OpponentDirectory,
    OpponentEndpointConfig,
    OpponentFeedType,
    get_default_opponent_directory,
)

SAMPLE_YAML = """
opponents:
    -
        canonical_name: "UNC Chapel Hill"
        feed_url: "https://tarheelhockey.com/schedule.ics"
        feed_type: "ical"
        home_venue: "Orange County Sportsplex"
        division: "ACHA M2"
        conference: "ACCHL"
        aliases:
            - "unc"
            - "north carolina"
            - "tar heels"
        website: "https://tarheelhockey.com"
        enabled: true
    -
        canonical_name: "NC State University"
        feed_url: "https://ncstatehockey.com/feed.json"
        feed_type: "json"
        home_venue: "Wake Competition Center"
        division: "ACHA M2"
        conference: "ACCHL"
        aliases:
            - "nc state"
            - "icepack"
        website: "https://ncstatehockey.com"
        enabled: false
"""


def test_opponent_config_error_hierarchy() -> None:
    """Verify OpponentConfigError inherits from ValueError."""
    err = OpponentConfigError("Malformed configuration")
    assert isinstance(err, ValueError)


def test_opponent_feed_type_values() -> None:
    """Verify supported feed type enum members."""
    assert OpponentFeedType.ICAL == "ical"
    assert OpponentFeedType.JSON == "json"
    assert OpponentFeedType.HTML == "html"
    assert OpponentFeedType.SPORTENGINE == "sportengine"


def test_endpoint_config_defaults_and_serialization() -> None:
    """Verify OpponentEndpointConfig defaults and to_dict serialization."""
    cfg = OpponentEndpointConfig(
        canonical_name="Duke University",
        feed_url="https://dukehockey.org/schedule.ics",
    )
    assert cfg.feed_type == OpponentFeedType.ICAL
    assert cfg.home_venue == "TBD"
    assert cfg.division == "ACHA M2"
    assert cfg.conference == "ACCHL"
    assert not cfg.aliases
    assert cfg.website is None
    assert cfg.enabled is True

    serialized = cfg.to_dict()
    assert serialized["canonical_name"] == "Duke University"
    assert serialized["feed_url"] == "https://dukehockey.org/schedule.ics"
    assert serialized["feed_type"] == "ical"
    assert serialized["home_venue"] == "TBD"
    assert serialized["division"] == "ACHA M2"
    assert serialized["conference"] == "ACCHL"
    assert not serialized["aliases"]
    assert serialized["website"] is None
    assert serialized["enabled"] is True


def test_endpoint_config_from_dict_complete() -> None:
    """Verify construction from a fully populated dictionary."""
    data = {
        "canonical_name": "Elon University",
        "feed_url": "https://elonhockey.com/schedule.html",
        "feed_type": "html",
        "home_venue": "Orange County Sportsplex",
        "division": "ACHA M2",
        "conference": "ACCHL",
        "aliases": ["elon", "phoenix"],
        "website": "https://elonhockey.com",
        "enabled": False,
    }
    cfg = OpponentEndpointConfig.from_dict(data)
    assert cfg.canonical_name == "Elon University"
    assert cfg.feed_url == "https://elonhockey.com/schedule.html"
    assert cfg.feed_type == OpponentFeedType.HTML
    assert cfg.home_venue == "Orange County Sportsplex"
    assert cfg.division == "ACHA M2"
    assert cfg.conference == "ACCHL"
    assert cfg.aliases == ("elon", "phoenix")
    assert cfg.website == "https://elonhockey.com"
    assert cfg.enabled is False


def test_endpoint_config_from_dict_minimal() -> None:
    """Verify construction with minimal fields falls back to defaults."""
    data = {
        "canonical_name": "Wake Forest University",
        "feed_url": "https://wakeforesthockey.com/events.ics",
        "feed_type": "ICAL",
    }
    cfg = OpponentEndpointConfig.from_dict(data)
    assert cfg.canonical_name == "Wake Forest University"
    assert cfg.feed_type == OpponentFeedType.ICAL
    assert cfg.home_venue == "TBD"
    assert cfg.division == "ACHA M2"
    assert cfg.conference == "ACCHL"
    assert not cfg.aliases
    assert cfg.website is None
    assert cfg.enabled is True


def test_endpoint_config_from_dict_aliases_variants() -> None:
    """Verify alias handling for string, tuple, and None."""
    base = {
        "canonical_name": "Team",
        "feed_url": "https://example.com/feed.ics",
        "feed_type": "ical",
    }
    cfg_none = OpponentEndpointConfig.from_dict(base | {"aliases": None})
    assert not cfg_none.aliases

    cfg_str = OpponentEndpointConfig.from_dict(base | {"aliases": "single-alias"})
    assert cfg_str.aliases == ("single-alias",)

    cfg_empty_str = OpponentEndpointConfig.from_dict(base | {"aliases": "   "})
    assert not cfg_empty_str.aliases

    cfg_tuple = OpponentEndpointConfig.from_dict(base | {"aliases": ("a1", "a2")})
    assert cfg_tuple.aliases == ("a1", "a2")

    cfg_enum_feed = OpponentEndpointConfig.from_dict(
        base | {"feed_type": OpponentFeedType.SPORTENGINE},
    )
    assert cfg_enum_feed.feed_type == OpponentFeedType.SPORTENGINE


def test_endpoint_config_from_dict_validation_failures() -> None:
    """Verify informative validation errors for invalid dictionary data."""
    raw_bad_dict: Any = "not-a-dict"
    with pytest.raises(OpponentConfigError, match="must be a dictionary"):
        OpponentEndpointConfig.from_dict(raw_bad_dict)

    with pytest.raises(
        OpponentConfigError,
        match="missing required field: 'canonical_name'",
    ):
        OpponentEndpointConfig.from_dict(
            {"feed_url": "https://ex.com", "feed_type": "ical"},
        )

    with pytest.raises(
        OpponentConfigError,
        match="missing required field: 'canonical_name'",
    ):
        OpponentEndpointConfig.from_dict(
            {"canonical_name": "  ", "feed_url": "https://ex.com"},
        )

    with pytest.raises(
        OpponentConfigError,
        match="missing required field: 'feed_url'",
    ):
        OpponentEndpointConfig.from_dict(
            {"canonical_name": "Team", "feed_type": "ical"},
        )

    with pytest.raises(OpponentConfigError, match="missing required field: 'feed_url'"):
        OpponentEndpointConfig.from_dict(
            {"canonical_name": "Team", "feed_url": "", "feed_type": "ical"},
        )

    with pytest.raises(
        OpponentConfigError,
        match="missing required field: 'feed_type'",
    ):
        OpponentEndpointConfig.from_dict(
            {
                "canonical_name": "Team",
                "feed_url": "https://ex.com",
            },
        )

    with pytest.raises(OpponentConfigError, match="feed_type must be a string"):
        OpponentEndpointConfig.from_dict(
            {
                "canonical_name": "Team",
                "feed_url": "https://ex.com",
                "feed_type": 123,
            },
        )

    with pytest.raises(OpponentConfigError, match="unrecognized feed_type: 'csv'"):
        OpponentEndpointConfig.from_dict(
            {
                "canonical_name": "Team",
                "feed_url": "https://ex.com",
                "feed_type": "csv",
            },
        )

    with pytest.raises(OpponentConfigError, match="aliases must be a list of strings"):
        OpponentEndpointConfig.from_dict(
            {
                "canonical_name": "Team",
                "feed_url": "https://ex.com",
                "feed_type": "ical",
                "aliases": 999,
            },
        )


def test_directory_registration_and_queries() -> None:
    """Verify registration, lookup, length, and enabled filtering."""
    dir_inst = OpponentDirectory()
    assert len(dir_inst) == 0

    cfg1 = OpponentEndpointConfig(
        canonical_name="UNC Chapel Hill",
        feed_url="https://tarheelhockey.com/schedule.ics",
        aliases=("unc", "tar heels"),
        enabled=True,
    )
    cfg2 = OpponentEndpointConfig(
        canonical_name="NC State University",
        feed_url="https://ncstatehockey.com/feed.json",
        feed_type=OpponentFeedType.JSON,
        aliases=("nc state", "pack"),
        enabled=False,
    )
    dir_inst.register(cfg1)
    dir_inst.register(cfg2)

    assert len(dir_inst) == 2
    assert "UNC Chapel Hill" in dir_inst
    assert "unc" in dir_inst
    assert "tar heels" in dir_inst
    assert "Unknown School" not in dir_inst

    assert dir_inst.get("unc") == cfg1
    assert dir_inst.get("NC State") == cfg2
    assert dir_inst.get("pack") == cfg2
    assert dir_inst.get("nonexistent") is None

    all_endpoints = dir_inst.list_endpoints(enabled_only=False)
    assert len(all_endpoints) == 2

    enabled_endpoints = dir_inst.list_endpoints(enabled_only=True)
    assert len(enabled_endpoints) == 1
    assert enabled_endpoints[0] == cfg1


def test_directory_to_yaml_roundtrip() -> None:
    """Verify serialization to YAML and reloading produces identical state."""
    dir_inst = OpponentDirectory()
    dir_inst.register(
        OpponentEndpointConfig(
            canonical_name="Duke University",
            feed_url="https://dukehockey.org/schedule.ics",
            home_venue="Orange County Sportsplex",
            aliases=("duke", "blue devils"),
            website="https://dukehockey.org",
            enabled=True,
        ),
    )
    yaml_text = dir_inst.to_yaml()
    assert "Duke University" in yaml_text
    assert "https://dukehockey.org/schedule.ics" in yaml_text

    loaded_dir = OpponentDirectory.from_yaml(yaml_text)
    assert len(loaded_dir) == 1
    retrieved = loaded_dir.get("duke")
    assert retrieved is not None
    assert retrieved.canonical_name == "Duke University"
    assert retrieved.home_venue == "Orange County Sportsplex"
    assert retrieved.website == "https://dukehockey.org"
    assert retrieved.enabled is True


def test_directory_from_yaml_sources(tmp_path: Path) -> None:
    """Verify from_yaml loading across str path, Path, TextIO, and raw YAML."""
    # 1. Raw YAML string
    dir_raw = OpponentDirectory.from_yaml(SAMPLE_YAML)
    assert len(dir_raw) == 2
    assert "unc" in dir_raw
    assert "nc state" in dir_raw

    # 2. Path object
    yaml_file = tmp_path / "opponents.yaml"
    yaml_file.write_text(SAMPLE_YAML, encoding="utf-8")
    dir_path = OpponentDirectory.from_yaml(yaml_file)
    assert len(dir_path) == 2

    # 3. String path
    dir_str_path = OpponentDirectory.from_yaml(str(yaml_file))
    assert len(dir_str_path) == 2

    # 4. TextIO stream
    stream = io.StringIO(SAMPLE_YAML)
    dir_stream = OpponentDirectory.from_yaml(stream)
    assert len(dir_stream) == 2


def test_directory_from_yaml_edge_cases(tmp_path: Path) -> None:
    """Verify handling of empty files, missing files, and malformed inputs."""
    # Empty string or comments only
    assert len(OpponentDirectory.from_yaml("")) == 0
    assert len(OpponentDirectory.from_yaml("# Comment only\n")) == 0

    # Explicit empty list
    dir_empty_list = OpponentDirectory.from_yaml("opponents: []")
    assert len(dir_empty_list) == 0

    # Explicit null list
    dir_null_list = OpponentDirectory.from_yaml("opponents: null")
    assert len(dir_null_list) == 0

    # Non-existent Path
    non_existent = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError, match="configuration file not found"):
        OpponentDirectory.from_yaml(non_existent)

    # Non-existent str path ending in .yaml
    with pytest.raises(FileNotFoundError, match="configuration file not found"):
        OpponentDirectory.from_yaml(str(non_existent))

    # Invalid source type
    raw_bad_source: Any = 12345
    with pytest.raises(TypeError, match="Expected str, Path, or TextIO"):
        OpponentDirectory.from_yaml(raw_bad_source)

    # Invalid YAML syntax
    with pytest.raises(OpponentConfigError, match="Invalid YAML syntax"):
        OpponentDirectory.from_yaml("opponents: [unbalanced")

    # YAML root is not a mapping
    with pytest.raises(OpponentConfigError, match="YAML root must be a mapping"):
        OpponentDirectory.from_yaml("- item 1\n- item 2")

    # Missing opponents key
    with pytest.raises(
        OpponentConfigError,
        match="Missing required top-level key: 'opponents'",
    ):
        OpponentDirectory.from_yaml("teams:\n  - name: UNC")

    # Opponents is not a list
    with pytest.raises(OpponentConfigError, match="'opponents' must be a list"):
        OpponentDirectory.from_yaml("opponents: 'not-a-list'")

    # Opponent entry is not a dict
    with pytest.raises(
        OpponentConfigError,
        match="Opponent entry must be a dictionary",
    ):
        OpponentDirectory.from_yaml("opponents:\n  - 'just-a-string'")


def test_default_opponent_directory_bundled_yaml() -> None:
    """Verify get_default_opponent_directory loads all 14 bundled opponents."""
    dir_inst = get_default_opponent_directory()
    assert len(dir_inst) == 14

    expected_opponents = {
        "UNC Chapel Hill": ("Orange County Sportsplex", OpponentFeedType.HTML),
        "NC State University": (
            "Invisalign Arena at Wake Competition Center",
            OpponentFeedType.ICAL,
        ),
        "Virginia Tech": ("Lancerlot Sports Complex", OpponentFeedType.HTML),
        "Wake Forest University": (
            "Winston-Salem Fairgrounds Annex",
            OpponentFeedType.HTML,
        ),
        "Duke University": ("Orange County Sportsplex", OpponentFeedType.HTML),
        "UNC Wilmington": ("Wilmington Ice House", OpponentFeedType.HTML),
        "Appalachian State University": (
            "Greensboro Ice House",
            OpponentFeedType.HTML,
        ),
        "High Point University": ("Greensboro Ice House", OpponentFeedType.HTML),
        "Elon University": ("Orange County Sportsplex", OpponentFeedType.HTML),
        "UNC Charlotte": ("Pineville IceHouse", OpponentFeedType.HTML),
        "James Madison University": ("Haymarket Iceplex", OpponentFeedType.HTML),
        "University of Richmond": ("Richmond Ice Zone", OpponentFeedType.HTML),
        "University of Virginia": ("Main Street Arena", OpponentFeedType.HTML),
        "Georgetown University": ("Fort Dupont Ice Arena", OpponentFeedType.HTML),
    }

    for name, (venue, feed_type) in expected_opponents.items():
        assert name in dir_inst
        endpoint = dir_inst.get(name)
        assert endpoint is not None
        assert endpoint.canonical_name == name
        assert endpoint.home_venue == venue
        assert endpoint.feed_type == feed_type
        assert endpoint.feed_url.startswith(("http://", "https://"))
        assert endpoint.website is not None
        assert endpoint.website.startswith("https://")
        assert endpoint.enabled is True
        assert endpoint.division == "ACHA M2"
        assert endpoint.conference == "ACCHL"
        assert len(endpoint.aliases) > 0
        for alias in endpoint.aliases:
            assert alias in dir_inst
            assert dir_inst.get(alias) is endpoint

"""Configuration loader, models, and schema validation for opponent schedule feeds."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, TextIO

import yaml

from ecu_hockey_calendar.ingestion.normalizer import normalize_team_name


class OpponentConfigError(ValueError):
    """Exception raised when opponent configuration YAML or schema validation fails."""


class OpponentFeedType(StrEnum):
    """Supported opponent schedule feed data formats."""

    ICAL = "ical"
    JSON = "json"
    HTML = "html"
    SPORTENGINE = "sportengine"


def _validate_required_string(
    data: dict[str, Any],
    field_name: str,
    opponent_name: str | None = None,
) -> str:
    """Validate and return a non-empty stripped string from dictionary."""
    val: object = data.get(field_name)
    prefix = f"Opponent '{opponent_name}'" if opponent_name else "Opponent entry"
    if not isinstance(val, str) or not val.strip():
        msg = f"{prefix} missing required field: '{field_name}'"
        raise OpponentConfigError(msg)

    return val.strip()


def _parse_feed_type(
    raw_type: object,
    canonical_name: str,
) -> OpponentFeedType:
    """Validate and convert raw feed type into OpponentFeedType enum."""
    if isinstance(raw_type, OpponentFeedType):
        return raw_type

    if not isinstance(raw_type, str):
        msg = f"Opponent '{canonical_name}' feed_type must be a string"
        raise OpponentConfigError(msg)

    cleaned = raw_type.strip().lower()
    try:
        return OpponentFeedType(cleaned)
    except ValueError as exc:
        valid = ", ".join(f"'{t.value}'" for t in OpponentFeedType)
        msg = (
            f"Opponent '{canonical_name}' has unrecognized feed_type: '{raw_type}'. "
            f"Supported types: {valid}"
        )
        raise OpponentConfigError(msg) from exc


def _clean_alias_sequence(seq: list[object] | tuple[object, ...]) -> tuple[str, ...]:
    """Extract non-empty stripped strings from sequence of alias objects."""
    result: list[str] = []
    for item in seq:
        stripped = str(item).strip()
        if stripped:
            result.append(stripped)

    return tuple(result)


def _parse_aliases(raw_aliases: object, canonical_name: str) -> tuple[str, ...]:
    """Validate and convert raw aliases into a tuple of non-empty strings."""
    if raw_aliases is None:
        return ()

    if isinstance(raw_aliases, (list, tuple)):
        return _clean_alias_sequence(raw_aliases)

    if isinstance(raw_aliases, str):
        cleaned = raw_aliases.strip()
        return (cleaned,) if cleaned else ()

    msg = f"Opponent '{canonical_name}' aliases must be a list of strings"
    raise OpponentConfigError(msg)


def _extract_str_field(data: dict[str, Any], key: str, default: str) -> str:
    """Extract string field from data with fallback default."""
    val = data.get(key)
    if val is None:
        return default

    cleaned = str(val).strip()
    return cleaned or default


def _extract_website(data: dict[str, Any]) -> str | None:
    """Extract optional website URL from data dictionary."""
    val = data.get("website")
    if not val:
        return None

    cleaned = str(val).strip()
    return cleaned or None


@dataclass(frozen=True)
class OpponentEndpointConfig:
    """Configuration representing an opposing institution's schedule feed."""

    canonical_name: str
    feed_url: str
    feed_type: OpponentFeedType = OpponentFeedType.ICAL
    home_venue: str = "TBD"
    division: str = "ACHA M2"
    conference: str = "ACCHL"
    aliases: tuple[str, ...] = ()
    website: str | None = None
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize opponent endpoint configuration to dictionary.

        Returns:
            Dictionary representation compatible with YAML schema.
        """
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
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpponentEndpointConfig:
        """Validate and construct an OpponentEndpointConfig from dictionary data.

        Args:
            data: Dictionary containing opponent configuration fields.

        Returns:
            OpponentEndpointConfig instance.

        Raises:
            OpponentConfigError: If required fields are missing or invalid.
        """
        if not isinstance(data, dict):
            msg = f"Opponent entry must be a dictionary, got {type(data).__name__}"
            raise OpponentConfigError(msg)

        name = _validate_required_string(data, "canonical_name")
        feed_url = _validate_required_string(data, "feed_url", opponent_name=name)
        raw_feed_type = data.get("feed_type")
        if raw_feed_type is None:
            msg = f"Opponent '{name}' missing required field: 'feed_type'"
            raise OpponentConfigError(msg)

        return cls(
            canonical_name=name,
            feed_url=feed_url,
            feed_type=_parse_feed_type(raw_feed_type, name),
            home_venue=_extract_str_field(data, "home_venue", "TBD"),
            division=_extract_str_field(data, "division", "ACHA M2"),
            conference=_extract_str_field(data, "conference", "ACCHL"),
            aliases=_parse_aliases(data.get("aliases"), name),
            website=_extract_website(data),
            enabled=bool(data.get("enabled", True)),
        )


def _read_path_file(path: Path) -> str:
    """Read UTF-8 text from file path or raise FileNotFoundError."""
    if not path.is_file():
        msg = f"Opponent configuration file not found: {path}"
        raise FileNotFoundError(msg)

    return path.read_text(encoding="utf-8")


def _is_file_path_string(val: str) -> bool:
    """Determine whether a string represents a file path rather than YAML markup."""
    if "\n" in val:
        return False

    return val.endswith((".yaml", ".yml")) or Path(val).is_file()


def _read_str_source(val: str) -> str:
    """Read YAML markup from file path string or raw YAML string."""
    if _is_file_path_string(val):
        return _read_path_file(Path(val))

    return val


def _read_yaml_source(source: str | Path | TextIO) -> str:
    """Read raw YAML text from file path, stream, or string."""
    if isinstance(source, Path):
        return _read_path_file(source)

    if isinstance(source, str):
        return _read_str_source(source)

    reader = getattr(source, "read", None)
    if callable(reader):
        return str(reader())

    msg = f"Expected str, Path, or TextIO, got {type(source).__name__}"
    raise TypeError(msg)


def _parse_yaml_content(content: str) -> dict[str, Any]:
    """Parse raw YAML string into dictionary structure."""
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML syntax: {exc}"
        raise OpponentConfigError(msg) from exc

    if parsed is None:
        return {"opponents": []}

    if not isinstance(parsed, dict):
        msg = f"YAML root must be a mapping, got {type(parsed).__name__}"
        raise OpponentConfigError(msg)

    return parsed


def _build_directory_from_data(data: dict[str, Any]) -> OpponentDirectory:
    """Construct OpponentDirectory from parsed configuration dictionary."""
    if "opponents" not in data:
        msg = "Missing required top-level key: 'opponents'"
        raise OpponentConfigError(msg)

    opponents_list = data["opponents"]
    if opponents_list is None:
        opponents_list = []

    if not isinstance(opponents_list, list):
        msg = f"'opponents' must be a list, got {type(opponents_list).__name__}"
        raise OpponentConfigError(msg)

    directory = OpponentDirectory()
    for entry in opponents_list:
        config = OpponentEndpointConfig.from_dict(entry)
        directory.register(config)

    return directory


class OpponentDirectory:
    """Registry and query directory for opponent schedule feeds."""

    def __init__(self) -> None:
        """Initialize an empty opponent directory."""
        self._endpoints: dict[str, OpponentEndpointConfig] = {}
        self._alias_map: dict[str, str] = {}

    def register(self, config: OpponentEndpointConfig) -> None:
        """Register an opponent endpoint configuration.

        Args:
            config: OpponentEndpointConfig instance to register.
        """
        canonical = normalize_team_name(config.canonical_name)
        self._endpoints[canonical.lower()] = config
        self._alias_map[canonical.lower()] = canonical.lower()
        for alias in config.aliases:
            norm_alias = normalize_team_name(alias).lower()
            self._alias_map[norm_alias] = canonical.lower()

    def get(self, name: str) -> OpponentEndpointConfig | None:
        """Lookup opponent configuration by institution name or alias.

        Args:
            name: Raw or normalized opponent institution name.

        Returns:
            OpponentEndpointConfig instance or None.
        """
        normalized = normalize_team_name(name).lower()
        canonical_key = self._alias_map.get(normalized, normalized)
        return self._endpoints.get(canonical_key)

    def list_endpoints(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[OpponentEndpointConfig]:
        """List all unique registered opponent endpoint configurations.

        Args:
            enabled_only: When True, return only enabled endpoint configurations.

        Returns:
            List of OpponentEndpointConfig objects.
        """
        if enabled_only:
            return [c for c in self._endpoints.values() if c.enabled]

        return list(self._endpoints.values())

    def to_yaml(self) -> str:
        """Serialize registered opponent endpoints to YAML markup.

        Returns:
            Formatted YAML string adhering to opponent configuration schema.
        """
        payload = {
            "opponents": [cfg.to_dict() for cfg in self.list_endpoints()],
        }
        dumped = yaml.safe_dump(payload, sort_keys=False)
        return str(dumped)

    @classmethod
    def from_yaml(cls, source: str | Path | TextIO) -> OpponentDirectory:
        """Load and parse opponent endpoint configurations from YAML source.

        Args:
            source: YAML file path (Path or str), file-like stream, or raw YAML string.

        Returns:
            Populated OpponentDirectory instance.

        Raises:
            FileNotFoundError: If a provided file path does not exist.
            OpponentConfigError: If YAML syntax is invalid or schema validation fails.
            TypeError: If source is not str, Path, or TextIO.
        """
        content = _read_yaml_source(source)
        data = _parse_yaml_content(content)
        return _build_directory_from_data(data)

    def __contains__(self, name: str) -> bool:
        """Check if opponent name or alias is registered."""
        return self.get(name) is not None

    def __len__(self) -> int:
        """Return total count of unique registered opponents."""
        return len(self._endpoints)


_ICAL = OpponentFeedType.ICAL

_DEFAULT_OPPONENTS: tuple[
    tuple[str, str, str, tuple[str, ...]],
    ...,
] = (
    (
        "UNC Chapel Hill",
        "tarheel",
        "Orange County Sportsplex",
        ("unc", "north carolina"),
    ),
    ("NC State University", "ncstate", "Wake Competition Center", ("nc state", "pack")),
    ("Virginia Tech", "hokies", "Lancerlot Sports Complex", ("vt", "hokies")),
    (
        "Wake Forest University",
        "wakeforest",
        "Winston-Salem Fairgrounds Annex",
        ("wake forest", "demon deacons"),
    ),
    ("Duke University", "duke", "Orange County Sportsplex", ("duke", "blue devils")),
    ("UNC Wilmington", "uncw", "Wilmington Ice House", ("uncw", "seahawks")),
    (
        "Appalachian State University",
        "appstate",
        "AppState Rink",
        ("app state", "mountaineers"),
    ),
    (
        "High Point University",
        "highpoint",
        "Greensboro Ice House",
        ("high point", "panthers"),
    ),
    ("Elon University", "elon", "Orange County Sportsplex", ("elon", "phoenix")),
    ("UNC Charlotte", "charlotte", "Pineville IceHouse", ("charlotte", "49ers")),
    ("James Madison University", "jmu", "Haymarket Iceplex", ("jmu", "dukes")),
    (
        "University of Richmond",
        "richmond",
        "Richmond Ice Zone",
        ("richmond", "spiders"),
    ),
    ("University of Virginia", "virginia", "Main Street Arena", ("uva", "cavaliers")),
    (
        "Georgetown University",
        "georgetown",
        "Fort Dupont Ice Arena",
        ("georgetown", "hoyas"),
    ),
)

DEFAULT_OPPONENT_SPECS: tuple[
    tuple[str, str, OpponentFeedType, str, tuple[str, ...]],
    ...,
] = tuple(
    (
        name,
        f"https://{slug}hockey.{'org' if slug == 'duke' else 'com'}/schedule.ics",
        _ICAL,
        venue,
        aliases,
    )
    for name, slug, venue, aliases in _DEFAULT_OPPONENTS
)


def get_default_opponent_directory() -> OpponentDirectory:
    """Construct and return default directory of known opponent endpoints.

    Returns:
        Populated OpponentDirectory instance.
    """
    directory = OpponentDirectory()
    for name, url, ftype, venue, aliases in DEFAULT_OPPONENT_SPECS:
        directory.register(
            OpponentEndpointConfig(
                canonical_name=name,
                feed_url=url,
                feed_type=ftype,
                home_venue=venue,
                aliases=aliases,
            ),
        )

    return directory


__all__ = [
    "DEFAULT_OPPONENT_SPECS",
    "OpponentConfigError",
    "OpponentDirectory",
    "OpponentEndpointConfig",
    "OpponentFeedType",
    "get_default_opponent_directory",
]

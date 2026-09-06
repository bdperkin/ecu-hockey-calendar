"""Crawler and ingestion manager for the primary ECU Hockey schedule site."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select

from ecu_hockey_calendar.ingestion.client import ResilientHttpClient
from ecu_hockey_calendar.ingestion.html_parser import (
    ParsedGameRecord,
    parse_schedule_html,
)
from ecu_hockey_calendar.ingestion.normalizer import (
    normalize_team_name,
    parse_game_score,
    parse_game_status,
)
from ecu_hockey_calendar.storage.models import (
    DataSourceModel,
    DataSourceType,
    GameModel,
    RawSnapshotModel,
    SyncAuditModel,
    SyncStatus,
    TeamModel,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.orm import Session

DEFAULT_TEAM_ID = "bH8QZkvU64QPqm88Qx8QdjL0O4c2"
DEFAULT_FIRESTORE_URL = (
    "https://firestore.googleapis.com/v1/projects/optimx-sports/"
    "databases/(default)/documents:runQuery"
)
DEFAULT_UPCOMING_HTML_URL = "https://www.ecuhockey.com/schedule/upcoming"
DEFAULT_RESULTS_HTML_URL = "https://www.ecuhockey.com/schedule/results"


def _extract_str_value(field_dict: dict[str, object]) -> str | None:
    """Extract string or timestamp string value from Firestore field dictionary."""
    for key in ("stringValue", "timestampValue"):
        if key in field_dict:
            return str(field_dict[key])

    return None


def _extract_firestore_value(
    field_dict: object | None,
) -> str | bool | int | None:
    """Extract native Python value from a Firestore field dictionary."""
    if not isinstance(field_dict, dict):
        return None

    if "booleanValue" in field_dict:
        return bool(field_dict["booleanValue"])

    if "integerValue" in field_dict:
        return int(str(field_dict["integerValue"]))

    return _extract_str_value(field_dict)


def _clean_title_opponent(title: str) -> str:
    """Extract opponent name from game title strings like 'Game vs Alabama'."""
    match = re.search(
        r"(?:Game\s+)?(?:vs\.?|@)\s*(.+?)(?:\s+on\s+.*)?$",
        title,
        re.IGNORECASE,
    )
    if match:
        return str(match.group(1)).strip()

    return title.strip()


def _parse_firestore_datetime(time_str: str | None) -> datetime | None:
    """Parse ISO Firestore timestamp string into datetime."""
    if not time_str:
        return None

    try:
        return datetime.fromisoformat(time_str)
    except ValueError:
        return None


def _extract_opponent_and_home(
    fields: Mapping[str, object],
) -> tuple[str, bool]:
    """Extract normalized opponent name and home game status."""
    home_game = _extract_firestore_value(fields.get("homeGame"))
    is_home = bool(home_game) if home_game is not None else True
    title_val = _extract_firestore_value(fields.get("title"))
    opp_raw = _clean_title_opponent(str(title_val)) if title_val else ""
    opponent_name = normalize_team_name(opp_raw) if opp_raw else "Opponent"
    return opponent_name, is_home


def _compute_team_scores(
    raw_score: str | None,
    *,
    is_home: bool,
) -> tuple[int | None, int | None, str | None]:
    """Compute home score, away score, and overtime note from raw score string."""
    s1, s2, ot_note = parse_game_score(raw_score)
    home_score = s1 if is_home else s2
    away_score = s2 if is_home else s1
    return home_score, away_score, ot_note


def _build_firestore_game_record(
    game_id: str,
    opponent_name: str,
    *,
    is_home: bool,
    start_time: datetime,
    fields: Mapping[str, object],
    doc: Mapping[str, object],
) -> ParsedGameRecord:
    """Build ParsedGameRecord from validated Firestore components."""
    score_val = _extract_firestore_value(fields.get("gameScore"))
    raw_score = str(score_val) if score_val is not None else None
    home_score, away_score, ot_note = _compute_team_scores(raw_score, is_home=is_home)
    venue_val = _extract_firestore_value(fields.get("venue"))
    venue = str(venue_val) if venue_val else "Carolina Ice Zone"
    status_val = _extract_firestore_value(fields.get("status"))
    raw_status = str(status_val) if status_val is not None else None
    return ParsedGameRecord(
        game_id=game_id,
        opponent_name=opponent_name,
        is_home=is_home,
        start_time=start_time,
        venue=venue,
        status=parse_game_status(raw_status, has_score=home_score is not None),
        home_score=home_score,
        away_score=away_score,
        overtime_note=ot_note,
        raw_text=json.dumps(dict(doc)),
    )


def _extract_game_id_and_start_time(
    fields: Mapping[str, object],
) -> tuple[str, datetime] | None:
    """Extract and validate game identifier and start timestamp."""
    id_val = _extract_firestore_value(fields.get("id"))
    time_val = _extract_firestore_value(fields.get("timeOfGame"))
    if not id_val or not time_val:
        return None

    start_time = _parse_firestore_datetime(str(time_val))
    if not start_time:
        return None

    return str(id_val), start_time


def parse_firestore_game_document(
    doc: Mapping[str, object],
) -> ParsedGameRecord | None:
    """Transform a Firestore game document into a ParsedGameRecord.

    Args:
        doc: Raw Firestore document dictionary containing 'fields'.

    Returns:
        ParsedGameRecord instance or None if invalid.
    """
    fields = doc.get("fields")
    if not isinstance(fields, dict):
        return None

    parsed_keys = _extract_game_id_and_start_time(fields)
    if not parsed_keys:
        return None

    game_id, start_time = parsed_keys
    opponent_name, is_home = _extract_opponent_and_home(fields)
    return _build_firestore_game_record(
        game_id,
        opponent_name,
        is_home=is_home,
        start_time=start_time,
        fields=fields,
        doc=doc,
    )


def _parse_api_item(item: object) -> ParsedGameRecord | None:
    """Parse a single Firestore query response item."""
    if (
        isinstance(item, dict)
        and "document" in item
        and isinstance(item["document"], dict)
    ):
        return parse_firestore_game_document(item["document"])

    return None


def _parse_api_records(data: object) -> list[ParsedGameRecord]:
    """Parse list of document wrappers from Firestore response."""
    if not isinstance(data, list):
        return []

    records: list[ParsedGameRecord] = []
    for item in data:
        parsed = _parse_api_item(item)
        if parsed:
            records.append(parsed)

    return records


class ECUHockeyCrawler:
    """Crawler for ECU Hockey primary schedule source of truth."""

    def __init__(
        self,
        *,
        client: ResilientHttpClient | None = None,
        team_id: str = DEFAULT_TEAM_ID,
        firestore_url: str = DEFAULT_FIRESTORE_URL,
    ) -> None:
        """Initialize crawler instance.

        Args:
            client: Optional ResilientHttpClient instance.
            team_id: Firestore team identifier for ECU Hockey.
            firestore_url: Firestore runQuery endpoint URL.
        """
        self.client = client or ResilientHttpClient()
        self.team_id = team_id
        self.firestore_url = firestore_url

    async def fetch_api_games(self) -> tuple[list[ParsedGameRecord], str, str]:
        """Fetch all games directly from the primary SOT Firestore API.

        Returns:
            Tuple of (parsed_records, raw_json_string, content_hash).
        """
        query_payload = {
            "structuredQuery": {
                "from": [{"collectionId": "games"}],
                "where": {
                    "fieldFilter": {
                        "field": {"fieldPath": "teamId"},
                        "op": "EQUAL",
                        "value": {"stringValue": self.team_id},
                    },
                },
            },
        }
        data, content_hash = await self.client.post_json(
            self.firestore_url,
            json_data=query_payload,
        )
        return _parse_api_records(data), json.dumps(data), content_hash

    async def fetch_html_games(
        self,
        url: str = DEFAULT_UPCOMING_HTML_URL,
    ) -> tuple[list[ParsedGameRecord], str, str]:
        """Fetch and parse games from an HTML schedule page.

        Args:
            url: Target schedule page URL.

        Returns:
            Tuple of (parsed_records, raw_html_string, content_hash).
        """
        html, content_hash = await self.client.fetch_text(url)
        records = parse_schedule_html(html)
        return records, html, content_hash

    async def crawl(
        self,
        *,
        prefer_api: bool = True,
    ) -> tuple[list[ParsedGameRecord], str, str, str]:
        """Crawl games using primary API with HTML fallback.

        Args:
            prefer_api: Whether to try the direct Firestore API first.

        Returns:
            Tuple of (records, raw_payload, content_hash, content_type).
        """
        if prefer_api:
            try:
                records, raw_text, content_hash = await self.fetch_api_games()
                if records:
                    return records, raw_text, content_hash, "application/json"
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                pass

        records, raw_text, content_hash = await self.fetch_html_games()
        return records, raw_text, content_hash, "text/html"

    @staticmethod
    def _finalize_audit(
        audit: SyncAuditModel,
        started_at: datetime,
        status: SyncStatus,
        error_message: str | None = None,
    ) -> None:
        """Update audit completion timestamps, duration, and status."""
        now = datetime.now(UTC)
        audit.completed_at = now
        audit.duration_ms = int((now - started_at).total_seconds() * 1000)
        audit.status = status.value
        audit.error_message = error_message

    def _get_or_create_source(
        self,
        session: Session,
        source_code: str,
    ) -> DataSourceModel:
        """Find or create data source record."""
        source = session.scalar(
            select(DataSourceModel).where(DataSourceModel.source_code == source_code),
        )
        if not source:
            source = DataSourceModel(
                source_code=source_code,
                name="ECU Hockey Official Website",
                source_url=DEFAULT_UPCOMING_HTML_URL,
                source_type=DataSourceType.PRIMARY_SOT.value,
                priority_order=1,
                is_active=True,
            )
            session.add(source)
            session.flush()

        return source

    def _get_or_create_team(
        self,
        session: Session,
        name: str,
        city: str = "Unknown",
        state: str = "NC",
    ) -> TeamModel:
        """Find or create team record by normalized name."""
        team = session.scalar(select(TeamModel).where(TeamModel.name == name))
        if not team:
            team = TeamModel(name=name, city=city, state=state)
            session.add(team)
            session.flush()

        return team

    def _persist_game_record(
        self,
        session: Session,
        record: ParsedGameRecord,
        ecu_id: int,
    ) -> bool:
        """Upsert a single game record. Returns True if created, False if updated."""
        opp_team = self._get_or_create_team(session, record.opponent_name)
        home_id = ecu_id if record.is_home else opp_team.id
        away_id = opp_team.id if record.is_home else ecu_id

        game = session.scalar(
            select(GameModel).where(GameModel.game_id == record.game_id),
        )
        created = False
        if not game:
            game = GameModel(
                game_id=record.game_id,
                home_team_id=home_id,
                away_team_id=away_id,
                start_time=record.start_time,
                venue=record.venue,
                status=record.status.value,
                home_score=record.home_score,
                away_score=record.away_score,
                result=record.calculate_result().value,
            )
            session.add(game)
            created = True
        else:
            game.home_team_id = home_id
            game.away_team_id = away_id
            game.start_time = record.start_time
            game.venue = record.venue
            game.status = record.status.value
            game.home_score = record.home_score
            game.away_score = record.away_score
            game.result = record.calculate_result().value

        session.flush()
        return created

    def _persist_records(
        self,
        session: Session,
        records: list[ParsedGameRecord],
        ecu_id: int,
    ) -> tuple[int, int]:
        """Persist parsed game records, returning counts of (created, updated)."""
        created = 0
        updated = 0
        for rec in records:
            if self._persist_game_record(session, rec, ecu_id):
                created += 1
            else:
                updated += 1

        return created, updated

    async def crawl_and_sync(
        self,
        session: Session,
        *,
        source_code: str = "primary_sot",
    ) -> SyncAuditModel:
        """Execute full crawl cycle and persist snapshot and game entities.

        Args:
            session: Active SQLAlchemy database session.
            source_code: Unique code for registered DataSource.

        Returns:
            Persisted SyncAuditModel tracking results.
        """
        started_at = datetime.now(UTC)
        source = self._get_or_create_source(session, source_code)
        audit = SyncAuditModel(
            source_id=source.id,
            sync_cycle_id=f"sync-{uuid.uuid4().hex[:16]}",
            started_at=started_at,
            status=SyncStatus.RUNNING.value,
        )
        session.add(audit)
        session.flush()

        try:
            records, raw_payload, content_hash, content_type = await self.crawl()

            # Record snapshot
            session.add(
                RawSnapshotModel(
                    source_id=source.id,
                    url=DEFAULT_UPCOMING_HTML_URL,
                    content_hash=content_hash,
                    content_type=content_type,
                    payload=raw_payload,
                    captured_at=datetime.now(UTC),
                ),
            )

            # Ensure ECU team exists
            ecu_team = self._get_or_create_team(
                session,
                "East Carolina University",
                city="Greenville",
                state="NC",
            )

            created, updated = self._persist_records(session, records, ecu_team.id)

            source.last_scraped_at = datetime.now(UTC)
            self._finalize_audit(audit, started_at, SyncStatus.SUCCESS)
            audit.games_created = created
            audit.games_updated = updated
            session.commit()
        except Exception as exc:
            self._finalize_audit(
                audit,
                started_at,
                SyncStatus.FAILURE,
                error_message=str(exc),
            )
            session.commit()
            raise

        return audit


__all__ = [
    "DEFAULT_FIRESTORE_URL",
    "DEFAULT_RESULTS_HTML_URL",
    "DEFAULT_TEAM_ID",
    "DEFAULT_UPCOMING_HTML_URL",
    "ECUHockeyCrawler",
    "parse_firestore_game_document",
]

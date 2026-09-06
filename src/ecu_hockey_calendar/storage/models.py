"""Relational persistence models for ECU Hockey Calendar storage.

This module defines normalized SQLAlchemy 2.0 ORM entities representing
teams, games, registered ingestion data sources, raw scraped snapshots,
and synchronization audits.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ecu_hockey_calendar.models import Game, GameResult, Team
from ecu_hockey_calendar.storage.base import Base


class DataSourceType(StrEnum):
    """Enumeration of ingestion data source types."""

    PRIMARY_SOT = "primary_sot"
    LEAGUE = "league"
    TICKETS = "tickets"
    SOCIAL = "social"
    OPPONENT = "opponent"


class SyncStatus(StrEnum):
    """Enumeration of synchronization audit statuses."""

    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PARTIAL = "PARTIAL"


class GameStatus(StrEnum):
    """Enumeration of game operational lifecycle states."""

    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINAL = "FINAL"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"


class TeamModel(Base):
    """Relational model for collegiate ice hockey teams."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        index=True,
        nullable=False,
    )
    city: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    division: Mapped[str] = mapped_column(
        String(32),
        default="ACHA M2",
        nullable=False,
    )
    conference: Mapped[str] = mapped_column(
        String(64),
        default="ACCHL",
        nullable=False,
    )
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    website: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    home_games: Mapped[list[GameModel]] = relationship(
        "GameModel",
        foreign_keys="[GameModel.home_team_id]",
        back_populates="home_team",
        cascade="all, delete-orphan",
    )
    away_games: Mapped[list[GameModel]] = relationship(
        "GameModel",
        foreign_keys="[GameModel.away_team_id]",
        back_populates="away_team",
        cascade="all, delete-orphan",
    )

    def to_domain(self) -> Team:
        """Convert ORM model to domain Team dataclass.

        Returns:
            The equivalent immutable domain Team instance.
        """
        return Team(
            name=self.name,
            city=self.city,
            state=self.state,
            division=self.division,
            conference=self.conference,
        )

    @classmethod
    def from_domain(
        cls,
        team: Team,
        logo_url: str | None = None,
        website: str | None = None,
    ) -> TeamModel:
        """Construct an ORM instance from a domain Team object.

        Args:
            team: Domain Team instance.
            logo_url: Optional team logo URL.
            website: Optional team website URL.

        Returns:
            New TeamModel instance.
        """
        return cls(
            name=team.name,
            city=team.city,
            state=team.state,
            division=team.division,
            conference=team.conference,
            logo_url=logo_url,
            website=website,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize team model to dictionary.

        Returns:
            Dictionary representation of the team entity.
        """
        return {
            "id": self.id,
            "name": self.name,
            "city": self.city,
            "state": self.state,
            "division": self.division,
            "conference": self.conference,
            "logo_url": self.logo_url,
            "website": self.website,
            "created_at": (self.created_at.isoformat() if self.created_at else None),
            "updated_at": (self.updated_at.isoformat() if self.updated_at else None),
        }


class GameModel(Base):
    """Relational model for scheduled or completed hockey games."""

    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        index=True,
        nullable=False,
    )
    home_team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    away_team_id: Mapped[int] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    venue: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default=GameStatus.SCHEDULED.value,
        nullable=False,
    )
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    season: Mapped[str] = mapped_column(
        String(32),
        default="2026-2027",
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    home_team: Mapped[TeamModel] = relationship(
        "TeamModel",
        foreign_keys=[home_team_id],
        back_populates="home_games",
    )
    away_team: Mapped[TeamModel] = relationship(
        "TeamModel",
        foreign_keys=[away_team_id],
        back_populates="away_games",
    )

    def to_domain(self) -> Game:
        """Convert ORM model to domain Game dataclass.

        Returns:
            The equivalent domain Game instance.
        """
        outcome: GameResult
        try:
            outcome = GameResult(self.result) if self.result else GameResult.SCHEDULED
        except ValueError:
            outcome = GameResult.SCHEDULED

        return Game(
            game_id=self.game_id,
            home_team=self.home_team.to_domain(),
            away_team=self.away_team.to_domain(),
            start_time=self.start_time,
            venue=self.venue,
            result=outcome,
            home_score=self.home_score,
            away_score=self.away_score,
        )

    @classmethod
    def from_domain(
        cls,
        game: Game,
        home_team_id: int,
        away_team_id: int,
        *,
        season: str = "2026-2027",
        status: str = GameStatus.SCHEDULED.value,
        end_time: datetime | None = None,
    ) -> GameModel:
        """Construct an ORM instance from a domain Game object.

        Args:
            game: Domain Game instance.
            home_team_id: Database identifier of the home team.
            away_team_id: Database identifier of the away team.
            season: Athletic competition season label.
            status: Lifecycle status of the game event.
            end_time: Optional end timestamp.

        Returns:
            New GameModel instance.
        """
        return cls(
            game_id=game.game_id,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            start_time=game.start_time,
            end_time=end_time,
            venue=game.venue,
            status=status,
            result=game.result.value if game.result else None,
            home_score=game.home_score,
            away_score=game.away_score,
            season=season,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize game model to dictionary.

        Returns:
            Dictionary representation of the game entity.
        """
        return {
            "id": self.id,
            "game_id": self.game_id,
            "home_team_id": self.home_team_id,
            "away_team_id": self.away_team_id,
            "start_time": (self.start_time.isoformat() if self.start_time else None),
            "end_time": (self.end_time.isoformat() if self.end_time else None),
            "venue": self.venue,
            "status": self.status,
            "result": self.result,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "season": self.season,
            "created_at": (self.created_at.isoformat() if self.created_at else None),
            "updated_at": (self.updated_at.isoformat() if self.updated_at else None),
        }


class DataSourceModel(Base):
    """Relational model for registered ingestion data sources."""

    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_code: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    priority_order: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    last_scraped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    snapshots: Mapped[list[RawSnapshotModel]] = relationship(
        "RawSnapshotModel",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    sync_audits: Mapped[list[SyncAuditModel]] = relationship(
        "SyncAuditModel",
        back_populates="source",
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize data source model to dictionary.

        Returns:
            Dictionary representation of the data source entity.
        """
        return {
            "id": self.id,
            "source_code": self.source_code,
            "name": self.name,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "priority_order": self.priority_order,
            "is_active": self.is_active,
            "last_scraped_at": (
                self.last_scraped_at.isoformat() if self.last_scraped_at else None
            ),
            "created_at": (self.created_at.isoformat() if self.created_at else None),
            "updated_at": (self.updated_at.isoformat() if self.updated_at else None),
        }


class RawSnapshotModel(Base):
    """Relational model for immutable archives of raw scraped HTML/JSON payloads."""

    __tablename__ = "raw_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    source: Mapped[DataSourceModel] = relationship(
        "DataSourceModel",
        back_populates="snapshots",
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize raw snapshot model to dictionary.

        Returns:
            Dictionary representation of the raw snapshot entity.
        """
        return {
            "id": self.id,
            "source_id": self.source_id,
            "url": self.url,
            "content_hash": self.content_hash,
            "content_type": self.content_type,
            "payload": self.payload,
            "captured_at": (self.captured_at.isoformat() if self.captured_at else None),
        }


class SyncAuditModel(Base):
    """Relational model for crawl cycles, duration, outcomes, and transitions."""

    __tablename__ = "sync_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sync_cycle_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=SyncStatus.RUNNING.value,
        nullable=False,
    )
    games_created: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    games_updated: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    games_deleted: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    conflicts_detected: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    source: Mapped[DataSourceModel | None] = relationship(
        "DataSourceModel",
        back_populates="sync_audits",
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize sync audit model to dictionary.

        Returns:
            Dictionary representation of the sync audit entity.
        """
        return {
            "id": self.id,
            "source_id": self.source_id,
            "sync_cycle_id": self.sync_cycle_id,
            "started_at": (self.started_at.isoformat() if self.started_at else None),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "duration_ms": self.duration_ms,
            "status": self.status,
            "games_created": self.games_created,
            "games_updated": self.games_updated,
            "games_deleted": self.games_deleted,
            "conflicts_detected": self.conflicts_detected,
            "error_message": self.error_message,
            "details": self.details,
        }


# Model aliases for convenience
TeamORM = TeamModel
GameORM = GameModel
DataSourceORM = DataSourceModel
RawSnapshotORM = RawSnapshotModel
SyncAuditORM = SyncAuditModel

__all__ = [
    "DataSourceModel",
    "DataSourceORM",
    "DataSourceType",
    "GameModel",
    "GameORM",
    "GameStatus",
    "RawSnapshotModel",
    "RawSnapshotORM",
    "SyncAuditModel",
    "SyncAuditORM",
    "SyncStatus",
    "TeamModel",
    "TeamORM",
]

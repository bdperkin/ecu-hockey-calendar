"""Unit tests for team logo asset manager, caching, and storage synchronization."""

# pylint: disable=protected-access,too-many-locals

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ecu_hockey_calendar.ingestion.client import ResilientHttpClient
from ecu_hockey_calendar.ingestion.logo_manager import (
    LogoAssetManager,
    LogoSyncResult,
    _extract_logo_extension,
    _find_team_by_name_or_aliases,
    _get_http_mtime_header,
    _resolve_root_logos_dir,
    _save_logo_bytes,
    _update_discovered_team_model,
    _update_team_model_logos,
    team_name_to_slug,
)
from ecu_hockey_calendar.ingestion.opponent_config import (
    OpponentDirectory,
    OpponentEndpointConfig,
    OpponentFeedType,
)
from ecu_hockey_calendar.storage.base import Base
from ecu_hockey_calendar.storage.models import TeamModel


def test_team_name_to_slug() -> None:
    """Test normalized slug creation across diverse team names."""
    assert team_name_to_slug("UNC Chapel Hill") == "unc-chapel-hill"
    assert team_name_to_slug("NC State University") == "nc-state-university"
    assert team_name_to_slug("St. Louis (MO)") == "st-louis-mo"
    assert team_name_to_slug("   ") == "team"
    assert team_name_to_slug("---") == "team"


def test_extract_logo_extension() -> None:
    """Test file extension extraction and fallback validation."""
    assert _extract_logo_extension("https://example.com/logo.png") == ".png"
    assert _extract_logo_extension("https://example.com/vector.svg") == ".svg"
    assert _extract_logo_extension("https://example.com/photo.JPG") == ".jpg"
    assert _extract_logo_extension("https://example.com/image.webp") == ".webp"
    assert _extract_logo_extension("https://example.com/unknown.gif") == ".png"
    assert (
        _extract_logo_extension("https://example.com/unknown", default=".svg") == ".svg"
    )


def test_get_http_mtime_header(tmp_path: Path) -> None:
    """Test conditional HTTP request header generation."""
    non_existent = tmp_path / "missing.png"
    assert not _get_http_mtime_header(non_existent)

    existing = tmp_path / "existing.png"
    existing.write_bytes(b"sample data")
    headers = _get_http_mtime_header(existing)
    assert "If-Modified-Since" in headers
    assert headers["If-Modified-Since"].endswith("GMT")


def test_save_logo_bytes(tmp_path: Path) -> None:
    """Test saving binary data creates directories and writes content."""
    p1 = tmp_path / "dir1" / "test1.png"
    p2 = tmp_path / "dir2" / "sub" / "test2.png"
    content = b"sample image bytes"

    _save_logo_bytes([p1, p2], content)
    assert p1.is_file()
    assert p2.is_file()
    assert p1.read_bytes() == content
    assert p2.read_bytes() == content


def test_find_team_by_name_or_aliases(tmp_path: Path) -> None:
    """Test finding team model by canonical name or configured aliases."""
    engine = create_engine(f"sqlite:///{tmp_path}/test_find.db")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        team1 = TeamModel(name="NC State University", city="Raleigh", state="NC")
        team2 = TeamModel(name="Appalachian State", city="Boone", state="NC")
        session.add_all([team1, team2])
        session.commit()

        # Canonical match
        opp_exact = OpponentEndpointConfig(
            canonical_name="NC State University",
            feed_url="https://example.com/ncstate",
            feed_type=OpponentFeedType.JSON,
            aliases=("nc state", "pack"),
        )
        found1 = _find_team_by_name_or_aliases(session, opp_exact)
        assert found1 is not None
        assert found1.id == team1.id

        # Alias match
        opp_alias = OpponentEndpointConfig(
            canonical_name="Appalachian State University",
            feed_url="https://example.com/appstate",
            feed_type=OpponentFeedType.JSON,
            aliases=("appalachian state", "app state"),
        )
        found2 = _find_team_by_name_or_aliases(session, opp_alias)
        assert found2 is not None
        assert found2.id == team2.id

        # Missing team
        opp_missing = OpponentEndpointConfig(
            canonical_name="Nonexistent University",
            feed_url="https://example.com/missing",
            feed_type=OpponentFeedType.JSON,
        )
        assert _find_team_by_name_or_aliases(session, opp_missing) is None


def test_update_team_model_logos(tmp_path: Path) -> None:
    """Test updating existing or inserting missing team model logo fields."""
    engine = create_engine(f"sqlite:///{tmp_path}/test_update.db")
    Base.metadata.create_all(engine)

    opp = OpponentEndpointConfig(
        canonical_name="Virginia Tech",
        feed_url="https://example.com/vt",
        feed_type=OpponentFeedType.JSON,
        logo_url="https://example.com/vt.png",
    )

    # 1. Team does not exist yet -> should be created
    with Session(engine) as session:
        _update_team_model_logos(session, opp, "/static/logos/virginia-tech.png")
        session.commit()

    with Session(engine) as session:
        team = session.scalar(
            select(TeamModel).where(TeamModel.name == "Virginia Tech"),
        )
        assert team is not None
        assert team.remote_logo_url == "https://example.com/vt.png"
        assert team.local_logo_url == "/static/logos/virginia-tech.png"
        assert team.logo_url == "https://example.com/vt.png"

        # 2. Update when local_web_url is None
        opp_no_local = OpponentEndpointConfig(
            canonical_name="Virginia Tech",
            feed_url="https://example.com/vt",
            feed_type=OpponentFeedType.JSON,
            logo_url="https://example.com/vt_new.png",
        )
        _update_team_model_logos(session, opp_no_local, None)
        session.commit()

    with Session(engine) as session:
        team = session.scalar(
            select(TeamModel).where(TeamModel.name == "Virginia Tech"),
        )
        assert team is not None
        assert team.remote_logo_url == "https://example.com/vt_new.png"
        assert team.local_logo_url == "/static/logos/virginia-tech.png"
        assert team.logo_url == "https://example.com/vt_new.png"


def test_logo_asset_manager_paths(tmp_path: Path) -> None:
    """Test LogoAssetManager URL and file path resolution methods."""
    mgr = LogoAssetManager(static_dir=tmp_path / "static")
    assert (
        mgr.get_local_web_url("unc-chapel-hill", ".png")
        == "/static/logos/unc-chapel-hill.png"
    )
    assert (
        mgr.get_local_file_path(
            "unc-chapel-hill",
            ".png",
        )
        == tmp_path / "static" / "logos" / "unc-chapel-hill.png"
    )


@pytest.mark.anyio
async def test_logo_asset_manager_fetch_304(tmp_path: Path) -> None:
    """Test that HTTP 304 response leaves file unchanged and returns False."""
    mock_client = MagicMock(spec=ResilientHttpClient)
    mock_client.fetch_bytes = AsyncMock(return_value=(b"", "", 304))

    mgr = LogoAssetManager(static_dir=tmp_path, http_client=mock_client)
    res = await mgr.sync_logo("Test Team", "https://example.com/logo.png")

    assert not res.updated
    assert res.error is None
    assert res.slug == "test-team"


@pytest.mark.anyio
async def test_logo_asset_manager_fetch_empty_content(tmp_path: Path) -> None:
    """Test that empty HTTP response payload returns updated=False."""
    mock_client = MagicMock(spec=ResilientHttpClient)
    mock_client.fetch_bytes = AsyncMock(return_value=(b"", "", 200))

    mgr = LogoAssetManager(static_dir=tmp_path, http_client=mock_client)
    res = await mgr.sync_logo("Test Team", "https://example.com/logo.png")

    assert not res.updated
    assert res.error is None


@pytest.mark.anyio
async def test_logo_asset_manager_fetch_identical_hash(tmp_path: Path) -> None:
    """Test that unchanged file hash avoids rewriting and reports updated=False."""
    local_file = tmp_path / "logos" / "test-team.png"
    local_file.parent.mkdir(parents=True, exist_ok=True)
    local_file.write_bytes(b"existing identical data")

    mock_client = MagicMock(spec=ResilientHttpClient)
    mock_client.fetch_bytes = AsyncMock(
        return_value=(b"existing identical data", "", 200),
    )

    mgr = LogoAssetManager(static_dir=tmp_path, http_client=mock_client)
    res = await mgr.sync_logo("Test Team", "https://example.com/logo.png")

    assert not res.updated
    assert res.error is None


@pytest.mark.anyio
async def test_logo_asset_manager_fetch_updated(tmp_path: Path) -> None:
    """Test successful new download caches file and reports updated=True."""
    mock_client = MagicMock(spec=ResilientHttpClient)
    mock_client.fetch_bytes = AsyncMock(return_value=(b"fresh new png bytes", "", 200))

    mgr = LogoAssetManager(static_dir=tmp_path, http_client=mock_client)
    res = await mgr.sync_logo("Test Team", "https://example.com/logo.png")

    assert res.updated
    assert res.error is None
    target_file = tmp_path / "logos" / "test-team.png"
    assert target_file.is_file()
    assert target_file.read_bytes() == b"fresh new png bytes"


@pytest.mark.anyio
async def test_logo_asset_manager_fetch_differing_hash(tmp_path: Path) -> None:
    """Test existing file is updated when hash differs."""
    local_file = tmp_path / "logos" / "test-team.png"
    local_file.parent.mkdir(parents=True, exist_ok=True)
    local_file.write_bytes(b"old outdated logo bytes")

    mock_client = MagicMock(spec=ResilientHttpClient)
    mock_client.fetch_bytes = AsyncMock(
        return_value=(b"new refreshed logo bytes", "", 200),
    )

    mgr = LogoAssetManager(static_dir=tmp_path, http_client=mock_client)
    res = await mgr.sync_logo("Test Team", "https://example.com/logo.png")

    assert res.updated
    assert res.error is None
    assert local_file.read_bytes() == b"new refreshed logo bytes"


def test_resolve_root_logos_dir_scenarios(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test resolution of secondary root logos directory across scenarios."""
    # Explicit root_static_dir provided
    assert (
        _resolve_root_logos_dir(tmp_path / "custom", tmp_path / "root")
        == tmp_path / "root" / "logos"
    )

    # static_dir provided without root_static_dir returns None
    assert _resolve_root_logos_dir(tmp_path / "custom", None) is None

    # static_dir and root_static_dir both None -> check candidate
    monkeypatch.setattr(
        "ecu_hockey_calendar.ingestion.logo_manager.Path.is_dir",
        lambda self: True,
    )
    res_true = _resolve_root_logos_dir(None, None)
    assert res_true is not None
    assert res_true.name == "logos"

    # When candidate is not a directory
    monkeypatch.setattr(
        "ecu_hockey_calendar.ingestion.logo_manager.Path.is_dir",
        lambda self: False,
    )
    res_false = _resolve_root_logos_dir(None, None)
    assert res_false is None


@pytest.mark.anyio
async def test_logo_asset_manager_with_root_static_dir(tmp_path: Path) -> None:
    """Test LogoAssetManager writes to both static_dir and root_static_dir."""
    dir1 = tmp_path / "s1"
    dir2 = tmp_path / "s2"
    mock_client = MagicMock(spec=ResilientHttpClient)
    mock_client.fetch_bytes = AsyncMock(
        return_value=(b"dual static write bytes", "", 200),
    )

    mgr = LogoAssetManager(
        static_dir=dir1,
        root_static_dir=dir2,
        http_client=mock_client,
    )
    assert mgr.root_logos_dir == dir2 / "logos"
    assert mgr.root_logos_dir.is_dir()
    assert len(mgr._resolve_target_paths("test.png")) == 2

    res = await mgr.sync_logo("Dual Team", "https://example.com/dual.png")
    assert res.updated
    assert (dir1 / "logos" / "dual-team.png").read_bytes() == b"dual static write bytes"
    assert (dir2 / "logos" / "dual-team.png").read_bytes() == b"dual static write bytes"


@pytest.mark.anyio
async def test_logo_asset_manager_fetch_exception(tmp_path: Path) -> None:
    """Test exception during sync records error in result without crashing."""
    mock_client = MagicMock(spec=ResilientHttpClient)
    mock_client.fetch_bytes = AsyncMock(
        side_effect=RuntimeError("Connection dropped"),
    )

    mgr = LogoAssetManager(static_dir=tmp_path, http_client=mock_client)
    res = await mgr.sync_logo("Test Team", "https://example.com/logo.png")

    assert not res.updated
    assert res.error == "Connection dropped"


@pytest.mark.anyio
async def test_sync_directory_logos(tmp_path: Path) -> None:
    """Test full directory synchronization loop across configured opponents."""
    engine = create_engine(f"sqlite:///{tmp_path}/test_dir.db")
    Base.metadata.create_all(engine)

    directory = OpponentDirectory()
    directory.register(
        OpponentEndpointConfig(
            canonical_name="UNC Chapel Hill",
            feed_url="https://example.com/unc",
            feed_type=OpponentFeedType.ICAL,
            logo_url="https://example.com/unc.png",
            aliases=("UNC",),
        ),
    )
    directory.register(
        OpponentEndpointConfig(
            canonical_name="Opponent Without Logo",
            feed_url="https://example.com/nologo",
            feed_type=OpponentFeedType.JSON,
            logo_url=None,
        ),
    )

    mock_client = MagicMock(spec=ResilientHttpClient)
    mock_client.fetch_bytes = AsyncMock(return_value=(b"unc logo bytes", "", 200))

    mgr = LogoAssetManager(static_dir=tmp_path, http_client=mock_client)

    with Session(engine) as session:
        session.add(
            TeamModel(
                name="Discovered Opponent",
                city="Greenville",
                state="NC",
                remote_logo_url="https://example.com/disc.png",
            ),
        )
        session.commit()

    with Session(engine) as session:
        results = await mgr.sync_directory_logos(directory, session)
        session.commit()

    assert len(results) == 2
    assert results[0].team_name == "UNC Chapel Hill"
    assert results[0].updated
    assert results[1].team_name == "Discovered Opponent"

    with Session(engine) as session:
        team = session.scalar(
            select(TeamModel).where(TeamModel.name == "UNC Chapel Hill"),
        )
        assert team is not None
        assert team.remote_logo_url == "https://example.com/unc.png"
        assert team.local_logo_url == "/static/logos/unc-chapel-hill.png"
        assert team.logo_url == "https://example.com/unc.png"

        disc_team = session.scalar(
            select(TeamModel).where(TeamModel.name == "Discovered Opponent"),
        )
        assert disc_team is not None
        assert disc_team.local_logo_url == "/static/logos/discovered-opponent.png"


def test_update_discovered_team_model() -> None:
    """Test updating discovered team model when local_web_url is None vs provided."""
    team = TeamModel(
        name="Discovered Team",
        city="Greenville",
        state="NC",
        remote_logo_url="https://example.com/logo.png",
    )
    res_none = LogoSyncResult(
        team_name="Discovered Team",
        slug="discovered-team",
        remote_url="https://example.com/logo.png",
        local_path=None,
        local_web_url=None,
        updated=False,
    )
    _update_discovered_team_model(team, res_none)
    assert team.local_logo_url is None
    assert team.logo_url == "https://example.com/logo.png"

    res_with_local = LogoSyncResult(
        team_name="Discovered Team",
        slug="discovered-team",
        remote_url="https://example.com/logo.png",
        local_path=Path("/var/data/logos/discovered-team.png"),
        local_web_url="/static/logos/discovered-team.png",
        updated=True,
    )
    _update_discovered_team_model(team, res_with_local)
    assert team.local_logo_url == "/static/logos/discovered-team.png"
    assert team.logo_url == "https://example.com/logo.png"

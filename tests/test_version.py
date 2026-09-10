"""Tests for package version resolution, VCS stamping, and fallback handling."""

from __future__ import annotations

import importlib.metadata
import types
from unittest.mock import patch

from click.testing import CliRunner
from fastapi.testclient import TestClient

from ecu_hockey_calendar.api.app import create_app
from ecu_hockey_calendar.cli.main import cli
from ecu_hockey_calendar.version import (
    FALLBACK_VERSION,
    __version__,
    get_version,
)


class _MockVersionModule(types.ModuleType):
    """Mock module type exposing a typed __version__ attribute."""

    __version__: str


def test_version_not_fallback_when_vcs_present() -> None:
    """Verify that resolved version is not the fallback sentinel in VCS workspace."""
    resolved = get_version()
    assert resolved != FALLBACK_VERSION
    assert resolved != "0.1.0.dev0"
    assert resolved != "0.4.0.dev0"
    assert __version__ == resolved


def test_get_version_vcs_module_present() -> None:
    """Verify get_version returns VCS version when _version module is importable."""
    mock_mod = _MockVersionModule("ecu_hockey_calendar._version")
    mock_mod.__version__ = "0.5.0"

    with patch.dict("sys.modules", {"ecu_hockey_calendar._version": mock_mod}):
        assert get_version() == "0.5.0"


def test_get_version_fallback_to_metadata() -> None:
    """Verify get_version falls back to importlib.metadata when _version is absent."""
    with (
        patch.dict("sys.modules", {"ecu_hockey_calendar._version": None}),
        patch(
            "importlib.metadata.version",
            return_value="0.5.1",
        ),
    ):
        assert get_version() == "0.5.1"


def test_get_version_fallback_sentinel_when_all_absent() -> None:
    """Verify get_version returns FALLBACK_VERSION when VCS and metadata are
    absent.
    """
    with (
        patch.dict("sys.modules", {"ecu_hockey_calendar._version": None}),
        patch(
            "importlib.metadata.version",
            side_effect=importlib.metadata.PackageNotFoundError,
        ),
    ):
        assert get_version() == FALLBACK_VERSION


def test_get_version_vcs_has_fallback_and_metadata_missing() -> None:
    """Verify get_version returns FALLBACK_VERSION when _version has fallback
    sentinel.
    """
    mock_mod = _MockVersionModule("ecu_hockey_calendar._version")
    mock_mod.__version__ = FALLBACK_VERSION

    with (
        patch.dict("sys.modules", {"ecu_hockey_calendar._version": mock_mod}),
        patch(
            "importlib.metadata.version",
            side_effect=importlib.metadata.PackageNotFoundError,
        ),
    ):
        assert get_version() == FALLBACK_VERSION


def test_get_version_metadata_has_legacy_dev_fallback() -> None:
    """Verify get_version skips legacy 0.1.0.dev0 and returns FALLBACK_VERSION."""
    with (
        patch.dict("sys.modules", {"ecu_hockey_calendar._version": None}),
        patch(
            "importlib.metadata.version",
            return_value="0.1.0.dev0",
        ),
    ):
        assert get_version() == FALLBACK_VERSION


def test_api_reports_resolved_version() -> None:
    """Verify that FastAPI app and endpoints report the resolved package version."""
    current_ver = get_version()
    app = create_app()
    assert app.version == current_ver

    client = TestClient(app)
    root_res = client.get("/")
    assert root_res.status_code == 200
    assert root_res.json()["version"] == current_ver

    openapi_res = client.get("/openapi.json")
    assert openapi_res.status_code == 200
    assert openapi_res.json()["info"]["version"] == current_ver


def test_cli_version_flag_reports_version() -> None:
    """Verify that ecu-hockey --version reports the package version."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert get_version() in result.output

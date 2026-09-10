"""Package version resolution utilities for ECU Hockey Calendar.

Provides a single source of truth for resolving the installed,
VCS-generated, or development fallback version of the package.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from typing import Final

FALLBACK_VERSION: Final[str] = "0.0.0+unknown"


def _resolve_vcs_version() -> str | None:
    """Resolve VCS version from generated ``_version`` module.

    Returns:
        Resolved VCS version string if available and valid, else None.
    """
    try:
        mod = importlib.import_module("ecu_hockey_calendar._version")
        vcs_version = getattr(mod, "__version__", None)
        if vcs_version and vcs_version != FALLBACK_VERSION:
            return str(vcs_version)
    except (ImportError, LookupError, TypeError):
        # The generated _version module is absent or incomplete in non-VCS builds.
        pass

    return None


def _resolve_metadata_version() -> str | None:
    """Resolve package version from installed distribution metadata.

    Returns:
        Resolved distribution version string if available and valid, else None.
    """
    try:
        pkg_version = importlib.metadata.version("ecu-hockey-calendar")
        if pkg_version and pkg_version not in (FALLBACK_VERSION, "0.1.0.dev0"):
            return pkg_version
    except (importlib.metadata.PackageNotFoundError, ValueError):
        # Package metadata may be unavailable when uninstalled or running standalone.
        pass

    return None


def get_version() -> str:
    """Resolve the package version string.

    Tries the following resolution strategy in order:

    * Prefer generated VCS version from ``ecu_hockey_calendar._version``.
    * Fall back to ``importlib.metadata.version("ecu-hockey-calendar")``.
    * Return non-release sentinel ``FALLBACK_VERSION`` (``0.0.0+unknown``).

    Returns:
        The resolved package version string.
    """
    vcs_version = _resolve_vcs_version()
    if vcs_version is not None:
        return vcs_version

    pkg_version = _resolve_metadata_version()
    if pkg_version is not None:
        return pkg_version

    return FALLBACK_VERSION


__version__: Final[str] = get_version()

__all__ = [
    "FALLBACK_VERSION",
    "__version__",
    "get_version",
]

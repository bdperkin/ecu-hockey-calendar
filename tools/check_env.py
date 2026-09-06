"""Development environment sanity and prerequisite check script.

Verifies Python version, virtual environment state, and presence of core
CLI developer tooling including uv, ty, and git.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def check_python_version() -> bool:
    """Verify that Python is at least version 3.12.

    Returns:
        True if Python version requirement is satisfied.
    """
    major, minor = sys.version_info[:2]
    print(f"Python version: {major}.{minor}.{sys.version_info.micro}")
    if (major, minor) < (3, 12):
        print("ERROR: Python 3.12 or newer is required.", file=sys.stderr)
        return False
    return True


def check_command(command: str) -> bool:
    """Verify that a command is executable and discoverable in PATH.

    Args:
        command: The executable name to verify.

    Returns:
        True if the command exists in PATH.
    """
    path = shutil.which(command)
    if path:
        print(f"✓ Found '{command}' at {path}")
        return True
    print(f"✗ Command '{command}' not found in PATH", file=sys.stderr)
    return False


def main() -> int:
    """Execute all development environment health checks.

    Returns:
        0 if all checks pass, otherwise 1.
    """
    print("Checking ecu-hockey-calendar development environment...\n")
    success = True

    if not check_python_version():
        success = False

    tools = ["git", "uv", "ty"]
    for tool in tools:
        if not check_command(tool):
            success = False

    venv_dir = Path(__file__).resolve().parent.parent / ".venv"
    if venv_dir.is_dir():
        print(f"✓ Found virtual environment at {venv_dir}")
    else:
        print(f"! Virtual environment missing at {venv_dir} (run `make sync`)")

    if success:
        print("\nAll development environment checks passed successfully!")
        return 0

    print("\nSome environment checks failed. Please address the errors above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

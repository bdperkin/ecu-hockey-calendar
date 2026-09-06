#!/usr/bin/env python3
"""Development script to update Table of Contents across markdown files.

This script invokes markdown-toc-creator on project documentation and root
markdown files to ensure tables of contents remain synchronized.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Run markdown-toc-creator on project markdown files.

    Returns:
        Exit code from the execution (0 for success).
    """
    root = Path(__file__).resolve().parent.parent
    target_files = [
        root / "README.md",
        root / "CONTRIBUTING.md",
        root / "SECURITY.md",
        root / "TODO.md",
    ]

    cmd = [
        "markdown-toc-creator",
        "--in-place",
        "True",
        "--add-toc-title",
        "True",
        "--add-horizontal-rules",
        "True",
        "--horizontal-rule-style",
        "mdformat",
        *[str(p) for p in target_files if p.exists()],
    ]

    try:
        result = subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as err:
        print(f"Error updating markdown table of contents: {err}", file=sys.stderr)
        return err.returncode
    else:
        return result.returncode


if __name__ == "__main__":
    sys.exit(main())

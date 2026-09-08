"""Module execution entrypoint for python -m ecu_hockey_calendar.cli."""

from __future__ import annotations

import sys

from ecu_hockey_calendar.cli.main import main

if __name__ == "__main__":
    sys.exit(main())

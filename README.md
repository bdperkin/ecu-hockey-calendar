# ecu-hockey-calendar

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [Table of Contents](#table-of-contents)
- [Features](#features)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Development and Contributing](#development-and-contributing)
  - [Quick Setup](#quick-setup)
- [Security](#security)
- [License](#license)

______________________________________________________________________

<!--TOC-->

[![CI](https://github.com/bdperkin/ecu-hockey-calendar/actions/workflows/ci.yml/badge.svg)](https://github.com/bdperkin/ecu-hockey-calendar/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/bdperkin/ecu-hockey-calendar/graph/badge.svg?token=)](https://codecov.io/gh/bdperkin/ecu-hockey-calendar)
[![Python Version](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Type Checked with ty](https://img.shields.io/badge/type_checker-ty-blueviolet)](https://github.com/astral-sh/ty)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Documentation](https://img.shields.io/badge/docs-Sphinx-blue)](https://bdperkin.github.io/ecu-hockey-calendar/)

East Carolina University - Men's Ice Hockey Team - Calendar.

A modern, robust Python package for managing collegiate ice hockey schedules, tracking team fixtures, and exporting calendars to standard iCalendar (RFC 5545), JSON, and CSV formats.

<!-- toc -->

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Development and Contributing](#development-and-contributing)
- [Security](#security)
- [License](#license)

<!-- tocstop -->

## Features

- **Standardized Domain Models**: Fully typed and validated `Team`, `Game`, `GameResult`, and `Schedule` models.
- **RFC 5545 iCalendar Export**: Generates `.ics` calendar files seamlessly importable into Apple Calendar, Google Calendar, and Microsoft Outlook.
- **Interoperable Data Exports**: Built-in support for CSV and formatted JSON schedule outputs.
- **Modern Python Architecture**: Managed natively with `uv`, dynamic VCS versioning, strict `ty` static typing, and comprehensive `ruff` linting.
- **Strict Quality**: 100% line and branch test coverage enforced at all times.

## Installation

Install using `uv`:

```bash
uv add ecu-hockey-calendar
```

Or install with standard `pip`:

```bash
pip install ecu-hockey-calendar
```

## Quickstart

```python
from datetime import UTC, datetime
from ecu_hockey_calendar import ECUHockeyCalendar, Team

# Initialize calendar for 2026-2027 season
calendar = ECUHockeyCalendar(season="2026-2027")

# Define opponent
unc = Team(
    name="UNC Chapel Hill",
    city="Chapel Hill",
    state="NC",
    division="ACHA M2",
    conference="ACCHL",
)

# Add a match
game = calendar.add_match(
    opponent=unc,
    start_time=datetime(2026, 10, 15, 19, 0, tzinfo=UTC),
    venue="The Factory Ice House",
    is_home=True,
)

# Export RFC 5545 iCalendar string
ics_data = calendar.export_ics()
with open("ecu_hockey_schedule.ics", "w", encoding="utf-8") as f:
    f.write(ics_data)

# Export to JSON or CSV
json_data = calendar.export_json()
csv_data = calendar.export_csv()
```

## Development and Contributing

Contributions are welcome! Please review our [Contributing Guide](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md).

### Quick Setup

```bash
# Clone the repository
git clone git@github.com:bdperkin/ecu-hockey-calendar.git
cd ecu-hockey-calendar

# Setup virtual environment and pre-commit hooks
make setup

# Run tests and linters
make check
```

## Security

Please report vulnerabilities confidentially through GitHub Private Vulnerability Reporting or refer to our [Security Policy](SECURITY.md).

## License

This project is licensed under the terms of the [MIT License](LICENSE).

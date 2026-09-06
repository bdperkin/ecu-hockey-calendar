# Quickstart

This guide illustrates how to use `ecu-hockey-calendar` to manage fixtures and export calendars.

## 1. Basic Usage

```python
from datetime import datetime, UTC
from ecu_hockey_calendar import ECUHockeyCalendar, Team

# Initialize calendar for 2026-2027 season
calendar = ECUHockeyCalendar(season="2026-2027")

# Define an opponent
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

# Export to RFC 5545 iCalendar (ICS)
ics_data = calendar.export_ics()
with open("ecu_schedule.ics", "w", encoding="utf-8") as f:
    f.write(ics_data)

# Export to JSON
json_data = calendar.export_json()

# Export to CSV
csv_data = calendar.export_csv()
```

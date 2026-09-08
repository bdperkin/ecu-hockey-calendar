# Multi-Channel Webhook Notifications & Alerts

The `ecu_hockey_calendar.notifications` package provides multi-platform webhook alerting to notify team staff, club leadership, and fans whenever schedule updates, cancellations, or data conflicts occur.

## 1. Architecture Overview

When the `ChangeDetector` detects state transitions (`CREATED`, `UPDATED`, `DELETED`, `CONFLICT_DETECTED`), the `NotificationDispatcher` formats and broadcasts alerts across configured communication channels:

```text
┌────────────────────────┐
│ ChangeDetectionResult  │ (Atomic transitions & field diffs)
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│ NotificationDispatcher │ (Queue & resilient retry dispatcher)
└───────────┬────────────┘
            │
    ┌───────┼───────┐
    ▼       ▼       ▼
┌───────┐┌───────┐┌──────────┐
│Discord││ Slack ││ Telegram │
│Webhook││Webhook││ Bot API  │
└───────┘└───────┘└──────────┘
```

## 2. Supported Platforms & Formats

- **Discord**: Formats rich embed cards with color-coded sidebars, match metadata fields, and timestamp footers.
- **Slack**: Renders Block Kit payloads with header blocks, field sections, and formatted markdown details.
- **Telegram**: Sends HTML-formatted messages with bold labels, status tags, and venue links.

### 2.1. Severity & State Colors

Embeds use visual color coding to highlight urgency:

- `CREATED`: Green (`#2ECC71`)
- `UPDATED`: Amber (`#F39C12`)
- `DELETED` / Cancelled: Red (`#E74C3C`)
- `CONFLICT_DETECTED`: Purple (`#9B59B6`)

## 3. Webhook Dispatcher Example

The following example configures endpoints and dispatches a notification payload:

```python
import asyncio
from datetime import datetime, UTC
from ecu_hockey_calendar.notifications import (
    NotificationChannel,
    NotificationConfig,
    NotificationDispatcher,
    NotificationField,
    NotificationMessage,
    NotificationSeverity,
)


async def send_schedule_alert() -> None:
    # Configure notification targets
    configs = [
        NotificationConfig(
            channel=NotificationChannel.DISCORD,
            webhook_url="https://discord.com/api/webhooks/example/token",
            enabled=True,
        ),
        NotificationConfig(
            channel=NotificationChannel.SLACK,
            webhook_url="https://hooks.slack.com/services/example/token",
            enabled=True,
        ),
    ]

    dispatcher = NotificationDispatcher(configs=configs)

    message = NotificationMessage(
        title="Schedule Update: ECU vs UNC Chapel Hill",
        description="Puck drop time has been updated to 7:30 PM EDT.",
        severity=NotificationSeverity.INFO,
        fields=[
            NotificationField(name="Date", value="Friday, Oct 15, 2026", inline=True),
            NotificationField(name="Venue", value="The Factory Ice House", inline=True),
            NotificationField(name="Status", value="Updated", inline=True),
        ],
        timestamp=datetime.now(UTC),
    )

    summary = await dispatcher.dispatch(message)
    print(
        f"Dispatched alerts: {summary.successful_count} succeeded, {summary.failed_count} failed."
    )


asyncio.run(send_schedule_alert())
```

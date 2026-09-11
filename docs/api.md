# API Reference

Complete API documentation for `ecu-hockey-calendar`.

## 1. Calendar Service

```{eval-rst}
.. automodule:: ecu_hockey_calendar.calendar
   :members:
   :show-inheritance:
```

## 2. Data Models

```{eval-rst}
.. automodule:: ecu_hockey_calendar.models
   :members:
   :show-inheritance:
```

## 3. Storage & Relational Persistence Models

```{eval-rst}
.. automodule:: ecu_hockey_calendar.storage.models
   :members:
   :show-inheritance:
```

## 4. Storage Engine & Session Management

```{eval-rst}
.. automodule:: ecu_hockey_calendar.storage.engine
   :members:
   :show-inheritance:
```

## 5. Database Schema Migrations

```{eval-rst}
.. automodule:: ecu_hockey_calendar.storage.migrations
   :members:
   :show-inheritance:
```

## 6. HTTP Ingestion Client

```{eval-rst}
.. automodule:: ecu_hockey_calendar.ingestion.client
   :members:
   :show-inheritance:
```

## 7. Ingestion Normalizer

```{eval-rst}
.. automodule:: ecu_hockey_calendar.ingestion.normalizer
   :members:
   :show-inheritance:
```

## 8. HTML Schedule Parser

```{eval-rst}
.. automodule:: ecu_hockey_calendar.ingestion.html_parser
   :members:
   :show-inheritance:
```

## 9. Primary Schedule Crawler

```{eval-rst}
.. automodule:: ecu_hockey_calendar.ingestion.ecuhockey_crawler
   :members:
   :show-inheritance:
```

## 10. ACCHL Schedule Parser

```{eval-rst}
.. automodule:: ecu_hockey_calendar.ingestion.acchockey_parser
   :members:
   :show-inheritance:
```

## 11. ACCHL League Crawler

```{eval-rst}
.. automodule:: ecu_hockey_calendar.ingestion.acchockey_crawler
   :members:
   :show-inheritance:
```

## 12. Ticketing & Promotional Theme Parser

```{eval-rst}
.. automodule:: ecu_hockey_calendar.ingestion.tickets_parser
   :members:
   :show-inheritance:
```

## 13. Ticketing Crawler

```{eval-rst}
.. automodule:: ecu_hockey_calendar.ingestion.tickets_crawler
   :members:
   :show-inheritance:
```

## 14. Instagram Feed & Announcement Parser

```{eval-rst}
.. automodule:: ecu_hockey_calendar.ingestion.instagram_parser
   :members:
   :show-inheritance:
```

## 15. Instagram Crawler & Session Cache

```{eval-rst}
.. automodule:: ecu_hockey_calendar.ingestion.instagram_crawler
   :members:
   :show-inheritance:
```

## 16. Opponent Schedule Feed & Verification Parser

```{eval-rst}
.. automodule:: ecu_hockey_calendar.ingestion.opponent_parser
   :members:
   :show-inheritance:
```

## 17. Opponent Schedule Crawler & Reverse Verification

```{eval-rst}
.. automodule:: ecu_hockey_calendar.ingestion.opponent_crawler
   :members:
   :show-inheritance:
```

## 18. Reconciliation Models & Priority Configuration

```{eval-rst}
.. automodule:: ecu_hockey_calendar.reconciliation.models
   :members:
   :show-inheritance:
```

## 19. Opponent & Venue Fuzzy Matching Engine

```{eval-rst}
.. automodule:: ecu_hockey_calendar.reconciliation.fuzzy_matcher
   :members:
   :show-inheritance:
```

## 20. Timezone & Schedule Date Aligner

```{eval-rst}
.. automodule:: ecu_hockey_calendar.reconciliation.date_aligner
   :members:
   :show-inheritance:
```

## 21. Multi-Source Reconciliation & Conflict Engine

```{eval-rst}
.. automodule:: ecu_hockey_calendar.reconciliation.engine
   :members:
   :show-inheritance:
```

## 22. Reconciliation Change Detector

```{eval-rst}
.. automodule:: ecu_hockey_calendar.reconciliation.change_detector
   :members:
   :show-inheritance:
```

## 23. Storage Change Audit Service

```{eval-rst}
.. automodule:: ecu_hockey_calendar.storage.service
   :members:
   :show-inheritance:
```

## 24. Notification Models & Configuration

```{eval-rst}
.. automodule:: ecu_hockey_calendar.notifications.models
   :members:
   :show-inheritance:
```

## 25. Webhook Embed & Message Formatters

```{eval-rst}
.. automodule:: ecu_hockey_calendar.notifications.formatters
   :members:
   :show-inheritance:
```

## 26. Multi-Platform Webhook Dispatcher

```{eval-rst}
.. automodule:: ecu_hockey_calendar.notifications.dispatcher
   :members:
   :show-inheritance:
```

## 27. FastAPI Application Factory

```{eval-rst}
.. automodule:: ecu_hockey_calendar.api.app
   :members:
   :show-inheritance:
```

## 28. Administrative Authentication & Security

```{eval-rst}
.. automodule:: ecu_hockey_calendar.api.auth
   :members:
   :show-inheritance:
```

## 29. Public Schedule Data Service

```{eval-rst}
.. automodule:: ecu_hockey_calendar.api.schedule_service
   :members:
   :show-inheritance:
```

## 30. Calendar Feed & iCalendar Service

```{eval-rst}
.. automodule:: ecu_hockey_calendar.api.service
   :members:
   :show-inheritance:
```

## 31. Server Execution Utility

```{eval-rst}
.. automodule:: ecu_hockey_calendar.api.server
   :members:
   :show-inheritance:
```

## 32. CLI Entry Points & Core Commands

```{eval-rst}
.. automodule:: ecu_hockey_calendar.cli.main
   :members:
   :show-inheritance:
```

## 33. CLI Synchronization Command

```{eval-rst}
.. automodule:: ecu_hockey_calendar.cli.sync
   :members:
   :exclude-members: select
   :show-inheritance:
```

## 34. CLI Status & Telemetry Command

```{eval-rst}
.. automodule:: ecu_hockey_calendar.cli.status
   :members:
   :exclude-members: select
   :show-inheritance:
```

## 35. CLI Schedule Export Command

```{eval-rst}
.. automodule:: ecu_hockey_calendar.cli.export
   :members:
   :exclude-members: select
   :show-inheritance:
```

## 36. CLI Conflict Inspection Command

```{eval-rst}
.. automodule:: ecu_hockey_calendar.cli.conflicts
   :members:
   :exclude-members: select
   :show-inheritance:
```

## 37. CLI API Server Command

```{eval-rst}
.. automodule:: ecu_hockey_calendar.cli.serve
   :members:
   :show-inheritance:
```

## 38. CLI Notification Dispatch Command

```{eval-rst}
.. automodule:: ecu_hockey_calendar.cli.notify
   :members:
   :show-inheritance:
```

## 39. CLI Console & Rich Utilities

```{eval-rst}
.. automodule:: ecu_hockey_calendar.cli.console
   :members:
   :show-inheritance:
```

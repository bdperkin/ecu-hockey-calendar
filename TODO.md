# Roadmap and TODO List

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Milestones](#1-milestones)
  - [1.1. Phase 1: Environment and Core Foundation (Complete)](#11-phase-1-environment-and-core-foundation-complete)
  - [1.2. Phase 2: Calendar Integration & Data Ingestion](#12-phase-2-calendar-integration--data-ingestion)
  - [1.3. Phase 3: CLI and Automation](#13-phase-3-cli-and-automation)

______________________________________________________________________

<!--TOC-->

This document tracks upcoming features, enhancements, and planned milestones for `ecu-hockey-calendar`.

## 1. Milestones

### 1.1. Phase 1: Environment and Core Foundation (Complete)

- [x] Configure native `uv` project with dynamic versioning (`hatchling` + `hatch-vcs`).
- [x] Implement strict `ruff` and `ty` type checking configurations.
- [x] Establish comprehensive test suite with 100% test and branch coverage.
- [x] Set up Sphinx documentation with markdown (`myst-parser`) and Furo theme.
- [x] Implement quality linters: Pylint, Codespell, Interrogate, Deptry, Vulture, Radon/Xenon.
- [x] Configure pre-commit and pre-commit.ci.
- [x] Configure GitHub Actions CI, CodeQL, and Dependabot.
- [x] Configure repository settings (disable Projects & Wiki, enable auto-merge, branch protection, security alerts).

### 1.2. Phase 2: Calendar Integration & Data Ingestion

- [ ] Implement web scraper for official ECU Club Hockey schedule site.
- [ ] Implement automated iCalendar subscription endpoint generator.
- [ ] Add support for Google Calendar API synchronization.
- [ ] Support live score updates and game status fetching.

### 1.3. Phase 3: CLI and Automation

- [ ] Add rich CLI interface via `typer` or `click` for command line schedule inspection.
- [ ] Add GitHub Actions scheduled cron to fetch new game announcements and publish updated ICS releases.
- [ ] Build automated calendar notifications (email or Discord/Slack webhook integration).

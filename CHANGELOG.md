# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Releases and changelog entries are managed automatically by [Python Semantic Release](https://python-semantic-release.readthedocs.io/).

<!-- version list -->

## v0.2.4 (2026-09-08)

### Documentation

- Update README.md and Sphinx documentation to reflect current project capabilities (closes #46)
  ([#65](https://github.com/bdperkin/ecu-hockey-calendar/pull/65),
  [`7d1480f`](https://github.com/bdperkin/ecu-hockey-calendar/commit/7d1480fd5f063984babff62b9cdb0bff2cbe145c))

- **roadmap**: Mark issue #15 complete in TODO.md
  ([#61](https://github.com/bdperkin/ecu-hockey-calendar/pull/61),
  [`0c32e6d`](https://github.com/bdperkin/ecu-hockey-calendar/commit/0c32e6db0e9dc57a5010d9dfe57c338dfc1898ae))

- **roadmap**: Track documentation alignment issues #62 and #63 in TODO.md
  ([#64](https://github.com/bdperkin/ecu-hockey-calendar/pull/64),
  [`387094b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/387094b6843fc71888ac97c601047fd651f45037))

### Features

- **api**: RFC 5545 iCalendar (.ics) subscription endpoint and webcal support (closes #10)
  ([#66](https://github.com/bdperkin/ecu-hockey-calendar/pull/66),
  [`aeca113`](https://github.com/bdperkin/ecu-hockey-calendar/commit/aeca1130a254fd6c9503fdae05318bfc0817f0a9))


## v0.2.3 (2026-09-08)

### Documentation

- **roadmap**: Mark issues #48 and #9 complete in TODO.md
  ([#59](https://github.com/bdperkin/ecu-hockey-calendar/pull/59),
  [`1a193e5`](https://github.com/bdperkin/ecu-hockey-calendar/commit/1a193e5ad3c0cc6a69e850c84ffff7cd58964e2e))

### Features

- **notifications**: Multi-platform webhook alerting for schedule updates and conflicts (#15)
  ([#60](https://github.com/bdperkin/ecu-hockey-calendar/pull/60),
  [`5bc7c39`](https://github.com/bdperkin/ecu-hockey-calendar/commit/5bc7c39beab73874f8fcb3214f368fd347992113))


## v0.2.2 (2026-09-08)

### Features

- **reconciliation**: Change detection and sync state tracking engine
  ([#9](https://github.com/bdperkin/ecu-hockey-calendar/pull/9),
  [`2665436`](https://github.com/bdperkin/ecu-hockey-calendar/commit/2665436d9fbcc8766d3af609b8fd6ee7e7c9af83))


## v0.2.1 (2026-09-08)

### Bug Fixes

- **ci**: Configure Python Semantic Release changelog automation (#45)
  ([#54](https://github.com/bdperkin/ecu-hockey-calendar/pull/54),
  [`14f47c8`](https://github.com/bdperkin/ecu-hockey-calendar/commit/14f47c844e4a324ba1b5dbf3673098ba918793c5))

- **ci**: Exclude CHANGELOG.md from pymarkdown pre-commit hook
  ([#56](https://github.com/bdperkin/ecu-hockey-calendar/pull/56),
  [`7227ad0`](https://github.com/bdperkin/ecu-hockey-calendar/commit/7227ad0158f8cfbc434c2c388ee21c99db820372))

- **release**: Align release versioning with project milestones and configure 0.x commit parser
  (#48) ([#57](https://github.com/bdperkin/ecu-hockey-calendar/pull/57),
  [`d5ff5ea`](https://github.com/bdperkin/ecu-hockey-calendar/commit/d5ff5eaf9ddecd9e98003aca9a32fec80d4d643f))

- **security**: Resolve CodeQL alert 12 for unused global variable in fuzzy_matcher (#39)
  ([#40](https://github.com/bdperkin/ecu-hockey-calendar/pull/40),
  [`4e96abd`](https://github.com/bdperkin/ecu-hockey-calendar/commit/4e96abd7d5417e07ef7d7e6d81dbc68842c111b0))

- **security**: Resolve CodeQL alert 13 for import and import-from in
  test_reconciliation_fuzzy_matcher (#41)
  ([#42](https://github.com/bdperkin/ecu-hockey-calendar/pull/42),
  [`58a3d3a`](https://github.com/bdperkin/ecu-hockey-calendar/commit/58a3d3abd1db16f90a036a51888e34de9c8aa1b8))

- **types**: Resolve ty 0.0.79 redundant condition diagnostics in acchockey_parser
  ([#55](https://github.com/bdperkin/ecu-hockey-calendar/pull/55),
  [`107ce03`](https://github.com/bdperkin/ecu-hockey-calendar/commit/107ce033fca762528ba3693a15ba024ea57b62ae))

### Chores

- **deps**: Update pre-commit-hooks to v6.0.0 and validate-pyproject to 0.26
  ([#53](https://github.com/bdperkin/ecu-hockey-calendar/pull/53),
  [`6484f6b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/6484f6bc983e7018d602be634e55887cd30cf123))

- **roadmap**: Remove ecu_hockey_scraper_prompt.md and audit TODO.md (#47)
  ([#49](https://github.com/bdperkin/ecu-hockey-calendar/pull/49),
  [`fa6f121`](https://github.com/bdperkin/ecu-hockey-calendar/commit/fa6f1215ce0976e102d8fe90eaf41aa49cdd3204))

- **tooling**: Migrate PyMarkdown configuration from .pymarkdown.json into pyproject.toml (#44)
  ([#52](https://github.com/bdperkin/ecu-hockey-calendar/pull/52),
  [`86aee53`](https://github.com/bdperkin/ecu-hockey-calendar/commit/86aee53b0220b721a6274a9f8f490efc02e92c94))

### Documentation

- **roadmap**: Mark issue #47 complete in TODO.md
  ([#50](https://github.com/bdperkin/ecu-hockey-calendar/pull/50),
  [`39d13c8`](https://github.com/bdperkin/ecu-hockey-calendar/commit/39d13c8459d9d30e3b49346b74f7f8dc8727225a))

- **roadmap**: Track CodeQL alert resolutions #39 and #41 in TODO.md
  ([#43](https://github.com/bdperkin/ecu-hockey-calendar/pull/43),
  [`0f5a0e2`](https://github.com/bdperkin/ecu-hockey-calendar/commit/0f5a0e2e9b749d72eb3d9f43d8b2ef1ec31bf5e3))

### Features

- **reconciliation**: Implement fuzzy-matching and multi-source conflict resolution engine (#8)
  ([#38](https://github.com/bdperkin/ecu-hockey-calendar/pull/38),
  [`7185a3a`](https://github.com/bdperkin/ecu-hockey-calendar/commit/7185a3aed6a704ad74e4deb725032df884d96f17))


## v0.2.0 (2026-09-06)

### Features

- **ingestion**: Automated opponent schedule reverse lookup and cross-check (#7)
  ([#37](https://github.com/bdperkin/ecu-hockey-calendar/pull/37),
  [`a4c885c`](https://github.com/bdperkin/ecu-hockey-calendar/commit/a4c885cc6eabd4077c05b5383582e4612f4ad7ef))

- **ingestion**: Create resilient Instagram feed parser for game announcements (#6)
  ([#36](https://github.com/bdperkin/ecu-hockey-calendar/pull/36),
  [`5c48232`](https://github.com/bdperkin/ecu-hockey-calendar/commit/5c4823209a35b0b6283aa6208291f03e2f1bfa1e))

- **ingestion**: Parse ticket sales page for game schedules and promotions
  ([#34](https://github.com/bdperkin/ecu-hockey-calendar/pull/34),
  [`a278df0`](https://github.com/bdperkin/ecu-hockey-calendar/commit/a278df04cc22396b65744da5a2e82995aef043ec))

- **ingestion**: Implement ACC Hockey league schedule page parser (#4)
  ([#33](https://github.com/bdperkin/ecu-hockey-calendar/pull/33),
  [`146a83f`](https://github.com/bdperkin/ecu-hockey-calendar/commit/146a83f7321b042bbbd8a83f7ba42f6b76039a4e))

- **ingestion**: Build resilient crawler for primary ECU Hockey schedule site (#3)
  ([#32](https://github.com/bdperkin/ecu-hockey-calendar/pull/32),
  [`2cb464c`](https://github.com/bdperkin/ecu-hockey-calendar/commit/2cb464cc01b2c5ca1a7c25a20e58c22d6d8bb27b))

- **storage**: Implement SQLAlchemy models and Alembic migration pipeline (#2)
  ([#24](https://github.com/bdperkin/ecu-hockey-calendar/pull/24),
  [`32047ba`](https://github.com/bdperkin/ecu-hockey-calendar/commit/32047baf847ea1aa9021cc752fda737ed8df1c25))

### Bug Fixes

- **ingestion**: Add explanatory comments to fallback except blocks to resolve CodeQL alerts
  ([#35](https://github.com/bdperkin/ecu-hockey-calendar/pull/35),
  [`131079b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/131079b65bbb38610ae6ab0a0578c8f0256d4bc8))

- **security**: Resolve CodeQL security and quality code scanning alerts (#25)
  ([#26](https://github.com/bdperkin/ecu-hockey-calendar/pull/26),
  [`3e2ab86`](https://github.com/bdperkin/ecu-hockey-calendar/commit/3e2ab86edae6cab7caf6bd16fa3447e8107f9b51))

### Chores

- **deps**: Bump actions and codecov actions
  ([#27](https://github.com/bdperkin/ecu-hockey-calendar/pull/27),
  [#28](https://github.com/bdperkin/ecu-hockey-calendar/pull/28),
  [#29](https://github.com/bdperkin/ecu-hockey-calendar/pull/29),
  [#30](https://github.com/bdperkin/ecu-hockey-calendar/pull/30),
  [#31](https://github.com/bdperkin/ecu-hockey-calendar/pull/31))


## v0.1.2 (2026-09-06)

### Bug Fixes

- **ci**: Install all extras in pages workflow
  ([#23](https://github.com/bdperkin/ecu-hockey-calendar/pull/23),
  [`30cc8b2`](https://github.com/bdperkin/ecu-hockey-calendar/commit/30cc8b22ff52a7fd236726e36a6f0368c19c73f9))

### Continuous Integration

- **codecov**: Configure JUnit XML test results and test analytics upload
  ([#21](https://github.com/bdperkin/ecu-hockey-calendar/pull/21),
  [`c623dde`](https://github.com/bdperkin/ecu-hockey-calendar/commit/c623dde5ec9d2d648cbf196f1ef272f1b3563f06))

- **pages**: Automated GitHub Pages deployment for Sphinx documentation (#18)
  ([#22](https://github.com/bdperkin/ecu-hockey-calendar/pull/22),
  [`12e68c5`](https://github.com/bdperkin/ecu-hockey-calendar/commit/12e68c57c6acd55fe5111c61e92732f354f5d175))

## v0.1.1 (2026-09-06)

### Bug Fixes

- **release**: Enable zero-version mode and disable major bump on zero
  ([#20](https://github.com/bdperkin/ecu-hockey-calendar/pull/20),
  [`02ca7f3`](https://github.com/bdperkin/ecu-hockey-calendar/commit/02ca7f3927a3dfdf16a6bacc56be23238f79ab99))

### Documentation

- **roadmap**: Integrate scraper specification and roadmap into TODO.md
  ([#17](https://github.com/bdperkin/ecu-hockey-calendar/pull/17),
  [`3254385`](https://github.com/bdperkin/ecu-hockey-calendar/commit/3254385ceccd97362cf457c4b8cf2d6104731ef9))

- **roadmap**: Track GitHub Pages deployment issue #18 in TODO roadmap
  ([#19](https://github.com/bdperkin/ecu-hockey-calendar/pull/19),
  [`6320ded`](https://github.com/bdperkin/ecu-hockey-calendar/commit/6320dedebee2e8b0bfa0c0aabc8b7dac1bf845cc))

## v0.1.0 (2026-09-05)

- Initial Release

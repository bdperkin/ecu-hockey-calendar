# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Releases and changelog entries are managed automatically by [Python Semantic Release](https://python-semantic-release.readthedocs.io/).

<!-- version list -->

## v0.8.2 (2026-09-07)

### Bug Fixes

- **security**: Resolve CodeQL alert 13 for import and import-from in
  test_reconciliation_fuzzy_matcher (#41)
  ([#42](https://github.com/bdperkin/ecu-hockey-calendar/pull/42),
  [`58a3d3a`](https://github.com/bdperkin/ecu-hockey-calendar/commit/58a3d3abd1db16f90a036a51888e34de9c8aa1b8))

## v0.8.1 (2026-09-07)

### Bug Fixes

- **security**: Resolve CodeQL alert 12 for unused global variable in fuzzy_matcher (#39)
  ([#40](https://github.com/bdperkin/ecu-hockey-calendar/pull/40),
  [`4e96abd`](https://github.com/bdperkin/ecu-hockey-calendar/commit/4e96abd7d5417e07ef7d7e6d81dbc68842c111b0))

## v0.8.0 (2026-09-07)

### Features

- **reconciliation**: Implement fuzzy-matching and multi-source conflict resolution engine (#8)
  ([#38](https://github.com/bdperkin/ecu-hockey-calendar/pull/38),
  [`7185a3a`](https://github.com/bdperkin/ecu-hockey-calendar/commit/7185a3aed6a704ad74e4deb725032df884d96f17))

## v0.7.0 (2026-09-06)

### Features

- **ingestion**: Automated opponent schedule reverse lookup and cross-check (#7)
  ([#37](https://github.com/bdperkin/ecu-hockey-calendar/pull/37),
  [`a4c885c`](https://github.com/bdperkin/ecu-hockey-calendar/commit/a4c885cc6eabd4077c05b5383582e4612f4ad7ef))

## v0.6.0 (2026-09-06)

### Features

- **ingestion**: Create resilient Instagram feed parser for game announcements (#6)
  ([#36](https://github.com/bdperkin/ecu-hockey-calendar/pull/36),
  [`5c48232`](https://github.com/bdperkin/ecu-hockey-calendar/commit/5c4823209a35b0b6283aa6208291f03e2f1bfa1e))

## v0.5.1 (2026-09-06)

### Bug Fixes

- **ingestion**: Add explanatory comments to fallback except blocks to resolve CodeQL alerts
  ([#35](https://github.com/bdperkin/ecu-hockey-calendar/pull/35),
  [`131079b`](https://github.com/bdperkin/ecu-hockey-calendar/commit/131079b65bbb38610ae6ab0a0578c8f0256d4bc8))

## v0.5.0 (2026-09-06)

### Chores

- **deps**: Bump actions/checkout from 4 to 7
  ([#31](https://github.com/bdperkin/ecu-hockey-calendar/pull/31),
  [`169c744`](https://github.com/bdperkin/ecu-hockey-calendar/commit/169c7445bc0c579d5ec3a660e1008ef2b64872a4))

- **deps**: Bump actions/dependency-review-action from 4 to 5
  ([#28](https://github.com/bdperkin/ecu-hockey-calendar/pull/28),
  [`f7b47a3`](https://github.com/bdperkin/ecu-hockey-calendar/commit/f7b47a3e467ee89a70471a9e22539ff468412069))

- **deps**: Bump actions/setup-python from 5 to 7
  ([#30](https://github.com/bdperkin/ecu-hockey-calendar/pull/30),
  [`6b19d3a`](https://github.com/bdperkin/ecu-hockey-calendar/commit/6b19d3ab02f7d8e80ccbd6c239e3a7c49a96a002))

- **deps**: Bump codecov/codecov-action from 5 to 7
  ([#29](https://github.com/bdperkin/ecu-hockey-calendar/pull/29),
  [`65cff03`](https://github.com/bdperkin/ecu-hockey-calendar/commit/65cff03eb17aae2ccf229dd3ce0a74ec44d2457d))

- **deps**: Bump github/codeql-action from 3 to 4
  ([#27](https://github.com/bdperkin/ecu-hockey-calendar/pull/27),
  [`3bc6a04`](https://github.com/bdperkin/ecu-hockey-calendar/commit/3bc6a046d136821844c8e553d90da9e899e2f84b))

### Features

- **ingestion**: Parse ticket sales page for game schedules and promotions
  ([#34](https://github.com/bdperkin/ecu-hockey-calendar/pull/34),
  [`a278df0`](https://github.com/bdperkin/ecu-hockey-calendar/commit/a278df04cc22396b65744da5a2e82995aef043ec))

## v0.4.0 (2026-09-06)

### Features

- **ingestion**: Implement ACC Hockey league schedule page parser (#4)
  ([#33](https://github.com/bdperkin/ecu-hockey-calendar/pull/33),
  [`146a83f`](https://github.com/bdperkin/ecu-hockey-calendar/commit/146a83f7321b042bbbd8a83f7ba42f6b76039a4e))

## v0.3.0 (2026-09-06)

### Features

- **ingestion**: Build resilient crawler for primary ECU Hockey schedule site (#3)
  ([#32](https://github.com/bdperkin/ecu-hockey-calendar/pull/32),
  [`2cb464c`](https://github.com/bdperkin/ecu-hockey-calendar/commit/2cb464cc01b2c5ca1a7c25a20e58c22d6d8bb27b))

## v0.2.1 (2026-09-06)

### Bug Fixes

- **security**: Resolve CodeQL security and quality code scanning alerts (#25)
  ([#26](https://github.com/bdperkin/ecu-hockey-calendar/pull/26),
  [`3e2ab86`](https://github.com/bdperkin/ecu-hockey-calendar/commit/3e2ab86edae6cab7caf6bd16fa3447e8107f9b51))

## v0.2.0 (2026-09-06)

### Features

- **storage**: Implement SQLAlchemy models and Alembic migration pipeline (#2)
  ([#24](https://github.com/bdperkin/ecu-hockey-calendar/pull/24),
  [`32047ba`](https://github.com/bdperkin/ecu-hockey-calendar/commit/32047baf847ea1aa9021cc752fda737ed8df1c25))

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

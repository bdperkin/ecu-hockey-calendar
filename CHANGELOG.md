# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Releases and changelog entries are managed automatically by [Python Semantic Release](https://python-semantic-release.readthedocs.io/).

## [Unreleased]

### Added

- Initial project environment setup with native `uv` packaging.
- Strict `ruff` and `ty` configurations.
- Comprehensive `pre-commit` and `pre-commit.ci` configurations.
- Core domain models: `Team`, `Game`, `GameResult`, and `Schedule`.
- `ECUHockeyCalendar` service with RFC 5545 iCalendar, CSV, and JSON export.
- 100% test coverage with pytest and pytest-cov.
- Sphinx documentation configuration with markdown (`myst-parser`) and Furo theme.
- GitHub Actions CI matrix, CodeQL security scanning, and Dependabot automation.

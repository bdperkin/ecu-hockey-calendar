# Contributing to ecu-hockey-calendar

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Branching and Pull Request Workflow](#1-branching-and-pull-request-workflow)
- [2. Environment Setup with `uv`](#2-environment-setup-with-uv)
- [3. Development and Make Targets](#3-development-and-make-targets)
- [4. Quality Standards](#4-quality-standards)

______________________________________________________________________

<!--TOC-->

Thank you for your interest in contributing to `ecu-hockey-calendar`!
We welcome contributions from the community. To ensure high code quality, security, and maintainability, please adhere to the guidelines below.

## 1. Branching and Pull Request Workflow

1. **Branches and PRs**:

   - Commits must **never** be made directly to `main`.

   - Always create a descriptive topic branch from `main`:

     ```bash
     git checkout -b feat/my-new-feature
     # or
     git checkout -b fix/issue-description
     ```

   - Submit all changes via a Pull Request (PR) targeted at `main`.

   - Branch protection requires linear history, all status checks to pass, and conversations to be resolved before merging.

2. **Conventional Commits**:

   - All commit messages must follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:
     - `feat:` Introduces a new feature (triggers a MINOR release).
     - `fix:` Patches a bug (triggers a PATCH release).
     - `docs:` Documentation-only changes.
     - `style:` Formatting changes that do not affect code logic.
     - `refactor:` Code changes that neither fix bugs nor add features.
     - `test:` Adding or correcting tests.
     - `chore:` Maintenance, tool updates, build changes.
     - `ci:` Continuous integration changes.
     - Append `!` (e.g., `feat!:`) for breaking changes (triggers a MAJOR release).

## 2. Environment Setup with `uv`

This project natively uses [`uv`](https://docs.astral.sh/uv/) for Python version and package management:

1. **Clone the repository**:

   ```bash
   git clone git@github.com:bdperkin/ecu-hockey-calendar.git
   cd ecu-hockey-calendar
   ```

2. **Sync the environment**:

   ```bash
   uv sync --all-extras --dev
   ```

3. **Install pre-commit hooks**:

   ```bash
   uv run pre-commit install
   ```

## 3. Development and Make Targets

We provide a `Makefile` to streamline local developer tasks:

- `make help`: Display available targets and descriptions.
- `make setup`: Complete developer setup (`uv sync` + `pre-commit install`).
- `make sync`: Sync dependencies and virtual environment.
- `make format`: Auto-format Python, Markdown, YAML, and TOML files.
- `make lint`: Run all linters (Ruff, Pylint, Codespell, Interrogate, Deptry, Vulture, Radon, Xenon, Mdformat, Pymarkdown, Yamlfix).
- `make typecheck`: Run strict `ty check` static type analysis.
- `make test`: Run `pytest` with coverage (enforces 100% test coverage).
- `make coverage`: Generate and view the HTML coverage report.
- `make docs`: Build Sphinx documentation with markdown (`myst-parser`) and Furo theme.
- `make docs-serve`: Serve built documentation locally on port 8000.
- `make audit`: Audit project dependencies for known vulnerabilities with `uv audit`.
- `make check`: Run format verification, linting, security audit, typechecking, and test suite.
- `make clean`: Clean build artifacts, caches, and test logs.

## 4. Quality Standards

- **100% Test Coverage**: Every line and branch must be covered by tests. PRs with coverage under 100% will fail CI.
- **Strict Typing**: Code must pass `ty check` with zero warnings or errors.
- **Google Docstrings**: All public modules, classes, and methods must have docstrings in Google format.
- **Linters**: Ruff, Pylint, Codespell, Interrogate, and Vulture must pass without errors.

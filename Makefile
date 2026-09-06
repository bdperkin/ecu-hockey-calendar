.DEFAULT_GOAL := help

PYTHON ?= python3
UV ?= uv
TY ?= ty

.PHONY: help
help: ## Display this help dialog
	@echo "Usage: make [target]"
	@echo ""
	@echo "Available targets:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: setup
setup: sync ## Setup virtual environment and pre-commit hooks
	$(UV) run pre-commit install

.PHONY: sync
sync: ## Synchronize dependencies using uv
	$(UV) sync --all-extras --dev

.PHONY: lock
lock: ## Update uv lockfile
	$(UV) lock

.PHONY: format
format: ## Auto-format code, markdown, toml, and yaml
	$(UV) run ruff format src tests tools
	$(UV) run ruff check --fix src tests tools
	$(UV) run pyproject-fmt pyproject.toml || true
	$(UV) run mdformat --number README.md CONTRIBUTING.md SECURITY.md SUPPORT.md TODO.md docs/*.md || true
	$(UV) run yamlfix codecov.yml .pre-commit-config.yaml .github/dependabot.yml .github/workflows/*.yml
	$(UV) run python tools/update_toc.py || true

.PHONY: lint-ruff
lint-ruff: ## Run ruff linter
	$(UV) run ruff check src tests tools

.PHONY: lint-pylint
lint-pylint: ## Run pylint
	$(UV) run pylint src tests

.PHONY: lint-codespell
lint-codespell: ## Check spelling across repository
	$(UV) run codespell

.PHONY: lint-interrogate
lint-interrogate: ## Verify 100% docstring coverage
	$(UV) run interrogate

.PHONY: lint-deptry
lint-deptry: ## Check dependency issues with deptry
	$(UV) run deptry .

.PHONY: lint-vulture
lint-vulture: ## Detect dead code with vulture
	$(UV) run vulture src tests

.PHONY: lint-complexity
lint-complexity: ## Check code complexity with radon and xenon
	$(UV) run radon cc src
	$(UV) run xenon --max-absolute A --max-modules A --max-average A src

.PHONY: lint-md
lint-md: ## Lint markdown files
	$(UV) run mdformat --check --number README.md CONTRIBUTING.md SECURITY.md SUPPORT.md TODO.md docs/*.md
	$(UV) run pymarkdown -c .pymarkdown.json scan README.md CONTRIBUTING.md SECURITY.md SUPPORT.md TODO.md docs/*.md

.PHONY: lint-yaml
lint-yaml: ## Check yaml format
	$(UV) run yamlfix --check codecov.yml .pre-commit-config.yaml .github/dependabot.yml .github/workflows/*.yml

.PHONY: lint
lint: lint-ruff lint-pylint lint-codespell lint-interrogate lint-deptry lint-vulture lint-complexity lint-md lint-yaml ## Run all linter checks

.PHONY: typecheck
typecheck: ## Run strict ty static type checker
	$(TY) check

.PHONY: test
test: ## Run test suite with pytest and enforce 100% coverage
	$(UV) run pytest

.PHONY: coverage
coverage: ## Display coverage report in terminal and generate HTML
	$(UV) run coverage report
	$(UV) run coverage html
	@echo "HTML coverage report available at htmlcov/index.html"

.PHONY: docs
docs: ## Build Sphinx documentation in HTML
	$(UV) run sphinx-build -W -b html docs docs/_build/html

.PHONY: docs-serve
docs-serve: docs ## Build and serve Sphinx documentation locally on port 8000
	@echo "Serving documentation at http://localhost:8000"
	$(UV) run python -m http.server 8000 --directory docs/_build/html

.PHONY: check
check: lint typecheck test docs ## Run full validation suite (lint, typecheck, test, docs)

.PHONY: clean
clean: ## Remove temporary build files, cache, and test artifacts
	rm -rf .venv build dist htmlcov .coverage .coverage.* coverage.xml docs/_build
	rm -rf .pytest_cache .ruff_cache .ty src/ecu_hockey_calendar/_version.py
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.py[cod]" -delete

.PHONY: all
all: clean sync format check docs ## Run complete lifecycle from clean to doc generation

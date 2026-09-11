# Installation

## 1. Requirements

- Python >= 3.12
- `uv` (recommended) or standard `pip`

## 2. Installing the CLI with `uv tool`

To install the standalone `ecu-hockey` command-line interface globally in an isolated environment:

```bash
uv tool install ecu-hockey-calendar
```

Verify that the CLI is installed and available in your shell:

```bash
ecu-hockey --help
```

## 3. Adding to a Project with `uv`

You can add `ecu-hockey-calendar` as a project dependency using `uv`:

```bash
uv add ecu-hockey-calendar
```

## 4. Installing with `pip`

Install from PyPI using standard pip:

```bash
pip install ecu-hockey-calendar
```

## 5. Development Installation

To install for local development, clone the repository and run:

```bash
git clone git@github.com:bdperkin/ecu-hockey-calendar.git
cd ecu-hockey-calendar
make setup
```

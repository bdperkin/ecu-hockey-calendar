"""Sphinx documentation configuration for ecu-hockey-calendar."""

from __future__ import annotations

import sys
from pathlib import Path

# Add project source root to Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ecu_hockey_calendar.version import get_version

project = "ecu-hockey-calendar"
copyright = "2026, Brandon Perkins"
author = "Brandon Perkins"

release = get_version()
version = ".".join(release.split(".")[:2])

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.githubpages",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_autodoc_typehints",
]

source_suffix = {
    ".md": "markdown",
}

root_doc = "index"

# Napoleon settings for Google-style docstrings
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = True
napoleon_use_ivar = True
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_preprocess_types = True

# MyST parser settings
myst_enable_extensions = [
    "attrs_inline",
    "colon_fence",
    "deflist",
    "fieldlist",
    "tasklist",
]
myst_heading_anchors = 3

# HTML output settings
html_theme = "furo"
html_title = f"{project} v{release}"
html_baseurl = "https://bdperkin.github.io/ecu-hockey-calendar/"
html_static_path = ["_static"]
html_extra_path = ["../static"]
html_logo = "_static/ecu_hockey_logo.svg"
html_favicon = "_static/favicon.ico"

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}

suppress_warnings = [
    "sphinx_autodoc_typehints.guarded_import",
]

# Linkcheck configuration
linkcheck_ignore = [
    r"^webcal://",
    r"^mailto:",
    r"http://localhost(:\d+)?",
    r"http://127\.0\.0\.1(:\d+)?",
    r"https://ecu-hockey-api\.onrender\.com/.*",
    r"https://(www\.)?instagram\.com/.*",
    r"https://(www\.)?twitter\.com/.*",
    r"https://(www\.)?x\.com/.*",
    r"https://github\.com/bdperkin/ecu-hockey-calendar/(blob|commit|pull|issues)/.*",
]
linkcheck_allowed_redirects = {
    r"https://click\.palletsprojects\.com/": r"https://click\.palletsprojects\.com/.*",
    r"https://rich\.readthedocs\.io/": r"https://rich\.readthedocs\.io/.*",
    r"https://calendar\.google\.com/": r"https://workspace\.google\.com/.*",
    r"https://developers\.cloudflare\.com/.*": r"https://developers\.cloudflare\.com/.*",
}
linkcheck_timeout = 15
linkcheck_rate_limit_timeout = 5.0
linkcheck_workers = 10

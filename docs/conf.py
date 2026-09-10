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
html_static_path = []
html_extra_path = ["../static"]

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

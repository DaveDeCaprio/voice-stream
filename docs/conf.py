# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "voice-stream"
copyright = "2024, Dave DeCaprio"
author = "Dave DeCaprio"
release = "0.3.0"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinxext.opengraph",
    "sphinx_copybutton",
    "sphinx.ext.extlinks",
    "sphinx.ext.autosectionlabel",
    "sphinx.ext.napoleon",  # for google style docstrings
]

myst_enable_extensions = [
    "attrs_inline",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "furo"
html_static_path = ["_static"]
html_logo = "logo.png"
html_title = "VoiceStream"
html_theme_options = {
    "navigation_with_keys": True,
}

# -- Links -------------------------------------------------
extlinks = {
    #'fastapi-sec': ('https://fastapi.tiangolo.com/%s', 'FastAPI '),
}

# -- Puts code on the path for API generation -------------------------------------------------
import os
import sys

sys.path.insert(0, os.path.abspath(".."))

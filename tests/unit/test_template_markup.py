"""Contract tests for the rendered site markup.

These read the generated index.html rather than the Jinja source so they
also cover the render step.
"""

import re

import pytest

from bugdb.site_builder import SiteBuilder


@pytest.fixture
def rendered(sample_database, temp_output_dir):
    """Build the site once and return index.html as text."""
    SiteBuilder(temp_output_dir).build(sample_database)
    return (temp_output_dir / "index.html").read_text(encoding="utf-8")


class TestThemeAssets:
    def test_theme_stylesheet_is_linked_after_tailwind(self, rendered):
        """theme.css must override tailwind.css, so it has to come later."""
        tailwind = rendered.index("assets/tailwind.css")
        theme = rendered.index("assets/theme.css")
        assert theme > tailwind

    def test_theme_script_is_loaded_in_head(self, rendered):
        """Must run before paint, or dark-mode users see a white flash."""
        head = rendered.split("</head>", 1)[0]
        assert "assets/theme.js" in head

    def test_no_inline_script_tags(self, rendered):
        """CSP is script-src 'self' — an inline script would be blocked."""
        inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", rendered)
        assert inline == [], f"inline <script> blocked by CSP: {inline}"

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


class TestHeaderControls:
    def test_header_has_theme_toggle(self, rendered):
        header = rendered.split("</header>", 1)[0]
        assert 'id="theme-toggle"' in header
        assert 'role="switch"' in header

    def test_release_notes_is_a_pill_button(self, rendered):
        header = rendered.split("</header>", 1)[0]
        assert 'id="release-notes-link"' in header
        assert "hdr-pill" in header

    def test_release_notes_button_starts_hidden(self, rendered):
        """app.js removes `hidden` once notes load; it must start hidden."""
        header = rendered.split("</header>", 1)[0]
        button = header[header.index('id="release-notes-link"') :]
        button = button[: button.index(">")]
        assert "hidden" in button

    def test_version_and_generated_are_not_in_the_header(self, rendered):
        header = rendered.split("</header>", 1)[0]
        assert "Generated" not in header
        assert "Version" not in header


class TestReleaseNotesModal:
    def test_generated_date_moved_into_the_modal(self, rendered):
        """The id must survive the move — app.js caches it by id at init."""
        assert rendered.count('id="generated-date"') == 1
        modal = rendered[rendered.index('id="release-notes-modal"') :]
        assert 'id="generated-date"' in modal

    def test_modal_shows_the_app_version(self, rendered):
        from bugdb import __version__

        modal = rendered[rendered.index('id="release-notes-modal"') :]
        assert f"Version {__version__}" in modal

    def test_modal_panel_is_widened(self, rendered):
        modal = rendered[rendered.index('id="release-notes-modal"') :]
        assert "rn-wide" in modal
        assert "max-w-2xl" not in modal

    def test_legend_lists_every_change_type(self, rendered):
        modal = rendered[rendered.index('id="release-notes-modal"') :]
        legend = modal[modal.index("rn-legend") :]
        for label in ("Feature", "Enhancement", "Bugfix", "Breaking"):
            assert label in legend
        assert legend.count("rn-legend-item") == 4


class TestChangeTypeRendering:
    """String contracts over the shipped app.js.

    There is no JS test runner in this repo, so these assert on source text.
    They catch regressions in the labels and marker classes; actual rendering
    is verified manually (see the plan's verification task).
    """

    @pytest.fixture
    def app_js(self, sample_database, temp_output_dir):
        SiteBuilder(temp_output_dir).build(sample_database)
        return (temp_output_dir / "assets" / "app.js").read_text(encoding="utf-8")

    def test_labels_are_renamed(self, app_js):
        assert "return 'Enhancement';" in app_js
        assert "return 'Bugfix';" in app_js
        assert "return 'Improvement';" not in app_js
        assert "return 'Fix';" not in app_js

    def test_stored_type_values_are_unchanged(self, app_js):
        """Only labels change — renaming the data would break cached JSON."""
        assert "case 'improvement':" in app_js
        assert "case 'fix':" in app_js

    def test_marker_is_icon_only(self, app_js):
        """No text node appended to the marker."""
        assert "rn-marker" in app_js
        assert "createTextNode(getChangeTypeLabel" not in app_js

    def test_marker_keeps_an_accessible_name(self, app_js):
        """Icon-only must still announce its meaning."""
        assert "aria-label', changeLabel" in app_js

    def test_change_list_uses_the_alignment_grid(self, app_js):
        assert "className: 'rn-list'" in app_js
        assert "className: 'contents'" in app_js


class TestReleaseNotesData:
    def test_latest_release_is_the_current_version(self):
        from bugdb import __version__
        from bugdb.release_notes import get_release_notes

        assert get_release_notes().releases[0].version == __version__

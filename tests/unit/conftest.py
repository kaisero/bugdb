"""Shared fixtures for the unit tier.

``sample_database`` and ``temp_output_dir`` started out module-local in
``test_site_builder.py``; they moved here so the markup contract tests in
``test_template_markup.py`` can build a real site from the same input.
"""

import pytest

from bugdb.models import BugDatabase, Issue, Product, ProductVersion


@pytest.fixture
def sample_database():
    """Create a sample database for testing."""
    issue = Issue(
        bug_id="PAN-12345",
        description="Test issue description",
        symptoms="Test symptoms",
        workaround="Test workaround",
        affected_components=["Component1"],
    )
    version = ProductVersion(
        version="11.1.0",
        release_date="2026-03-01",
        known_issues=[issue],
        addressed_issues=[],
    )
    product = Product(id="pan-os", name="PAN-OS", versions=[version])
    return BugDatabase(products=[product])


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create a temporary output directory."""
    return tmp_path / "dist"

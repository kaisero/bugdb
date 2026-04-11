"""Tests for BugDB site builder."""

import json

import pytest

from bugdb.models import BugDatabase, Issue, Product, ProductVersion
from bugdb.site_builder import SiteBuilder, build_site, build_site_from_database


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


class TestSiteBuilder:
    """Tests for SiteBuilder class."""

    def test_build_creates_output_directory(self, sample_database, temp_output_dir):
        """Test that build creates the output directory."""
        builder = SiteBuilder(temp_output_dir)
        builder.build(sample_database)

        assert temp_output_dir.exists()
        assert temp_output_dir.is_dir()

    def test_build_creates_index_html(self, sample_database, temp_output_dir):
        """Test that build creates index.html."""
        builder = SiteBuilder(temp_output_dir)
        builder.build(sample_database)

        index_file = temp_output_dir / "index.html"
        assert index_file.exists()

        content = index_file.read_text()
        assert "<!DOCTYPE html>" in content
        assert "BugDB" in content

    def test_build_creates_assets_directory(self, sample_database, temp_output_dir):
        """Test that build creates assets directory."""
        builder = SiteBuilder(temp_output_dir)
        builder.build(sample_database)

        assets_dir = temp_output_dir / "assets"
        assert assets_dir.exists()
        assert assets_dir.is_dir()

    def test_build_creates_data_json(self, sample_database, temp_output_dir):
        """Test that build creates data.json with correct content."""
        builder = SiteBuilder(temp_output_dir)
        builder.build(sample_database)

        data_file = temp_output_dir / "assets" / "data.json"
        assert data_file.exists()

        with open(data_file) as f:
            data = json.load(f)

        assert "products" in data
        assert "metadata" in data
        assert len(data["products"]) == 1
        assert data["products"][0]["id"] == "pan-os"

    def test_build_copies_app_js(self, sample_database, temp_output_dir):
        """Test that build copies app.js to assets."""
        builder = SiteBuilder(temp_output_dir)
        builder.build(sample_database)

        js_file = temp_output_dir / "assets" / "app.js"
        assert js_file.exists()

        content = js_file.read_text()
        assert "function" in content


class TestBuildSiteFunctions:
    """Tests for build_site helper functions."""

    def test_build_site_from_database(self, sample_database, temp_output_dir):
        """Test build_site_from_database function."""
        build_site_from_database(sample_database, temp_output_dir)

        assert (temp_output_dir / "index.html").exists()
        assert (temp_output_dir / "assets" / "data.json").exists()
        assert (temp_output_dir / "assets" / "app.js").exists()

    def test_build_site_from_json_file(self, sample_database, tmp_path, temp_output_dir):
        """Test build_site function with JSON file."""
        # Create a JSON file
        data_file = tmp_path / "bugs.json"
        with open(data_file, "w") as f:
            json.dump(sample_database.model_dump(mode="json"), f, default=str)

        # Build site from JSON file
        build_site(data_file, temp_output_dir)

        assert (temp_output_dir / "index.html").exists()
        assert (temp_output_dir / "assets" / "data.json").exists()

    def test_data_json_contains_all_issues(self, sample_database, temp_output_dir):
        """Test that data.json contains all issue data."""
        build_site_from_database(sample_database, temp_output_dir)

        with open(temp_output_dir / "assets" / "data.json") as f:
            data = json.load(f)

        issue = data["products"][0]["versions"][0]["known_issues"][0]
        assert issue["bug_id"] == "PAN-12345"
        assert issue["description"] == "Test issue description"
        assert issue["symptoms"] == "Test symptoms"
        assert issue["workaround"] == "Test workaround"
        assert issue["affected_components"] == ["Component1"]

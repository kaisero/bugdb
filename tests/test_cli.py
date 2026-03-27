"""Tests for BugDB CLI commands."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bugdb.cli import app

runner = CliRunner()


class TestGenerateSample:
    """Tests for generate-sample command."""

    def test_generate_sample_creates_file(self, tmp_path):
        """Test that generate-sample creates a JSON file."""
        output_file = tmp_path / "bugs.json"
        result = runner.invoke(app, ["generate-sample", "-o", str(output_file)])

        assert result.exit_code == 0
        assert output_file.exists()
        assert "Generated sample data" in result.stdout

    def test_generate_sample_creates_valid_json(self, tmp_path):
        """Test that generated file is valid JSON with expected structure."""
        output_file = tmp_path / "bugs.json"
        runner.invoke(app, ["generate-sample", "-o", str(output_file)])

        with open(output_file) as f:
            data = json.load(f)

        assert "metadata" in data
        assert "products" in data
        assert len(data["products"]) > 0

    def test_generate_sample_refuses_overwrite_without_force(self, tmp_path):
        """Test that generate-sample refuses to overwrite without --force."""
        output_file = tmp_path / "bugs.json"
        output_file.write_text("{}")

        result = runner.invoke(app, ["generate-sample", "-o", str(output_file)])

        assert result.exit_code == 1
        assert "already exists" in result.stdout

    def test_generate_sample_overwrites_with_force(self, tmp_path):
        """Test that generate-sample overwrites with --force."""
        output_file = tmp_path / "bugs.json"
        output_file.write_text("{}")

        result = runner.invoke(app, ["generate-sample", "-o", str(output_file), "--force"])

        assert result.exit_code == 0
        assert "Generated sample data" in result.stdout

    def test_generate_sample_creates_parent_directories(self, tmp_path):
        """Test that generate-sample creates parent directories."""
        output_file = tmp_path / "nested" / "dir" / "bugs.json"
        result = runner.invoke(app, ["generate-sample", "-o", str(output_file)])

        assert result.exit_code == 0
        assert output_file.exists()


class TestBuildSite:
    """Tests for build-site command."""

    def test_build_site_creates_output(self, tmp_path):
        """Test that build-site creates output files."""
        # First generate sample data
        data_file = tmp_path / "bugs.json"
        runner.invoke(app, ["generate-sample", "-o", str(data_file)])

        # Then build site
        output_dir = tmp_path / "dist"
        result = runner.invoke(
            app, ["build-site-cmd", "-d", str(data_file), "-o", str(output_dir)]
        )

        assert result.exit_code == 0
        assert (output_dir / "index.html").exists()
        assert (output_dir / "assets" / "data.json").exists()
        assert (output_dir / "assets" / "app.js").exists()

    def test_build_site_missing_data_file(self, tmp_path):
        """Test that build-site fails with missing data file."""
        output_dir = tmp_path / "dist"
        result = runner.invoke(
            app, ["build-site-cmd", "-d", "/nonexistent/file.json", "-o", str(output_dir)]
        )

        assert result.exit_code == 1
        assert "not found" in result.stdout

    def test_build_site_invalid_json(self, tmp_path):
        """Test that build-site fails with invalid JSON."""
        data_file = tmp_path / "bugs.json"
        data_file.write_text("not valid json")

        output_dir = tmp_path / "dist"
        result = runner.invoke(
            app, ["build-site-cmd", "-d", str(data_file), "-o", str(output_dir)]
        )

        assert result.exit_code == 1


class TestValidate:
    """Tests for validate command."""

    def test_validate_valid_file(self, tmp_path):
        """Test that validate passes for valid file."""
        data_file = tmp_path / "bugs.json"
        runner.invoke(app, ["generate-sample", "-o", str(data_file)])

        result = runner.invoke(app, ["validate", str(data_file)])

        assert result.exit_code == 0
        assert "Valid bug database" in result.stdout

    def test_validate_missing_file(self):
        """Test that validate fails for missing file."""
        result = runner.invoke(app, ["validate", "/nonexistent/file.json"])

        assert result.exit_code == 1
        assert "not found" in result.stdout

    def test_validate_invalid_json(self, tmp_path):
        """Test that validate fails for invalid JSON."""
        data_file = tmp_path / "bugs.json"
        data_file.write_text("not valid json")

        result = runner.invoke(app, ["validate", str(data_file)])

        assert result.exit_code == 1
        assert "Invalid JSON" in result.stdout

    def test_validate_invalid_schema(self, tmp_path):
        """Test that validate fails for invalid schema."""
        data_file = tmp_path / "bugs.json"
        # Missing required fields
        data_file.write_text('{"products": [{"id": "test"}]}')

        result = runner.invoke(app, ["validate", str(data_file)])

        assert result.exit_code == 1
        assert "validation failed" in result.stdout

    def test_validate_shows_statistics(self, tmp_path):
        """Test that validate shows database statistics."""
        data_file = tmp_path / "bugs.json"
        runner.invoke(app, ["generate-sample", "-o", str(data_file)])

        result = runner.invoke(app, ["validate", str(data_file)])

        assert "Products:" in result.stdout
        assert "Versions:" in result.stdout
        assert "Known issues:" in result.stdout
        assert "Addressed issues:" in result.stdout


class TestVersion:
    """Tests for version flag."""

    def test_version_flag(self):
        """Test that --version shows version."""
        result = runner.invoke(app, ["--version"])

        assert result.exit_code == 0
        assert "BugDB version" in result.stdout

    def test_version_short_flag(self):
        """Test that -v shows version."""
        result = runner.invoke(app, ["-v"])

        assert result.exit_code == 0
        assert "BugDB version" in result.stdout

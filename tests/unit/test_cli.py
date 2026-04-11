"""Tests for BugDB CLI commands."""

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from bugdb.cli import app
from bugdb.crawlers.models import FailedFetch, FetchResult
from bugdb.models import (
    BugDatabase,
    FailedFetchEntry,
    FetchReport,
    Issue,
    Metadata,
    Product,
    ProductStats,
    ProductVersion,
)

runner = CliRunner()


def _flat(text: str) -> str:
    """Collapse whitespace in Rich-rendered output for substring matching.

    Rich wraps long paths at the CliRunner's terminal width (default 80),
    which can split asserted substrings like "not found" across a newline
    ("not \\nfound"). This helper normalises all whitespace to single
    spaces so assertions are robust to tmpdir path length and terminal
    width changes.
    """
    return " ".join(text.split())


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
        assert "already exists" in _flat(result.stdout)

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
        result = runner.invoke(app, ["build-site-cmd", "-d", str(data_file), "-o", str(output_dir)])

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
        assert "not found" in _flat(result.stdout)

    def test_build_site_invalid_json(self, tmp_path):
        """Test that build-site fails with invalid JSON."""
        data_file = tmp_path / "bugs.json"
        data_file.write_text("not valid json")

        output_dir = tmp_path / "dist"
        result = runner.invoke(app, ["build-site-cmd", "-d", str(data_file), "-o", str(output_dir)])

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
        assert "not found" in _flat(result.stdout)

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


def _make_fetch_result(
    product_id="panos",
    product_name="PAN-OS",
    versions=None,
    failed_fetches=None,
):
    """Helper to create a FetchResult for mocking crawlers."""
    if versions is None:
        versions = [
            ProductVersion(
                version="12.1.5",
                known_issues=[Issue(bug_id="PAN-1", description="Test known")],
                addressed_issues=[Issue(bug_id="PAN-2", description="Test fixed")],
            ),
        ]
    return FetchResult(
        database=BugDatabase(
            metadata=Metadata(),
            products=[Product(id=product_id, name=product_name, versions=versions)],
        ),
        failed_fetches=failed_fetches or [],
    )


class TestFetchWithReport:
    """Tests for fetch --report flag."""

    def test_report_creates_report_file(self, tmp_path):
        """Test that --report creates a .report.json file."""
        output_file = tmp_path / "data.json"
        mock_result = _make_fetch_result()

        with patch.dict(
            "bugdb.crawlers.registry.PRODUCT_WRAPPERS",
            {"panos": MagicMock(return_value=mock_result)},
        ):
            result = runner.invoke(app, ["fetch", "panos", "-o", str(output_file), "--report"])

        assert result.exit_code == 0
        report_file = tmp_path / "data.report.json"
        assert report_file.exists()

        report = json.loads(report_file.read_text())
        assert report["total_products"] == 1
        assert report["total_known_issues"] == 1
        assert report["total_addressed_issues"] == 1
        assert report["data_file"] == str(output_file)

    def test_report_contains_product_stats(self, tmp_path):
        """Test that report contains per-product statistics."""
        output_file = tmp_path / "data.json"
        mock_result = _make_fetch_result()

        with patch.dict(
            "bugdb.crawlers.registry.PRODUCT_WRAPPERS",
            {"panos": MagicMock(return_value=mock_result)},
        ):
            result = runner.invoke(app, ["fetch", "panos", "-o", str(output_file), "--report"])

        assert result.exit_code == 0
        report = json.loads((tmp_path / "data.report.json").read_text())
        assert len(report["product_stats"]) == 1
        stats = report["product_stats"][0]
        assert stats["product_id"] == "panos"
        assert stats["product_name"] == "PAN-OS"
        assert stats["versions_fetched"] == 1
        assert stats["known_issues_count"] == 1
        assert stats["addressed_issues_count"] == 1
        assert stats["failed_fetch_count"] == 0

    def test_report_contains_failed_fetches(self, tmp_path):
        """Test that report captures failed fetches."""
        output_file = tmp_path / "data.json"
        mock_result = _make_fetch_result(
            failed_fetches=[
                FailedFetch(
                    url="https://example.com/page",
                    error="Timeout",
                    product="panos",
                    version="12.1.5",
                    issue_type="known",
                ),
            ],
        )

        with patch.dict(
            "bugdb.crawlers.registry.PRODUCT_WRAPPERS",
            {"panos": MagicMock(return_value=mock_result)},
        ):
            result = runner.invoke(app, ["fetch", "panos", "-o", str(output_file), "--report"])

        assert result.exit_code == 0
        report = json.loads((tmp_path / "data.report.json").read_text())
        assert len(report["failed_fetches"]) == 1
        assert report["failed_fetches"][0]["url"] == "https://example.com/page"
        assert report["failed_fetches"][0]["product"] == "panos"
        assert report["product_stats"][0]["failed_fetch_count"] == 1

    def test_report_written_with_no_failures(self, tmp_path):
        """Test that report is written even when there are no failures."""
        output_file = tmp_path / "data.json"
        mock_result = _make_fetch_result()

        with patch.dict(
            "bugdb.crawlers.registry.PRODUCT_WRAPPERS",
            {"panos": MagicMock(return_value=mock_result)},
        ):
            result = runner.invoke(app, ["fetch", "panos", "-o", str(output_file), "--report"])

        assert result.exit_code == 0
        report = json.loads((tmp_path / "data.report.json").read_text())
        assert report["failed_fetches"] == []

    def test_no_report_file_without_flag(self, tmp_path):
        """Test that no report is written without --report."""
        output_file = tmp_path / "data.json"
        mock_result = _make_fetch_result()

        with patch.dict(
            "bugdb.crawlers.registry.PRODUCT_WRAPPERS",
            {"panos": MagicMock(return_value=mock_result)},
        ):
            result = runner.invoke(app, ["fetch", "panos", "-o", str(output_file)])

        assert result.exit_code == 0
        assert not (tmp_path / "data.report.json").exists()

    def test_report_path_shown_in_output(self, tmp_path):
        """Test that report path is shown in the summary panel."""
        output_file = tmp_path / "data.json"
        mock_result = _make_fetch_result()

        with patch.dict(
            "bugdb.crawlers.registry.PRODUCT_WRAPPERS",
            {"panos": MagicMock(return_value=mock_result)},
        ):
            result = runner.invoke(app, ["fetch", "panos", "-o", str(output_file), "--report"])

        assert result.exit_code == 0
        assert "Report:" in result.stdout


class TestFetchWithRetry:
    """Tests for fetch --retry flag."""

    def _write_data_file(self, path):
        """Helper to write a minimal data.json."""
        db = BugDatabase(
            metadata=Metadata(),
            products=[
                Product(
                    id="panos",
                    name="PAN-OS",
                    versions=[
                        ProductVersion(
                            version="12.1.5",
                            known_issues=[Issue(bug_id="PAN-1", description="Existing known")],
                        ),
                    ],
                ),
            ],
        )
        path.write_text(json.dumps(db.model_dump(mode="json"), indent=2, default=str))

    def _write_report(self, path, data_file, failed_fetches=None):
        """Helper to write a report JSON."""
        report = FetchReport(
            data_file=str(data_file),
            total_products=1,
            total_versions=1,
            total_known_issues=1,
            total_addressed_issues=0,
            product_stats=[
                ProductStats(
                    product_id="panos",
                    product_name="PAN-OS",
                    versions_fetched=1,
                    known_issues_count=1,
                    addressed_issues_count=0,
                    failed_fetch_count=len(failed_fetches or []),
                ),
            ],
            failed_fetches=failed_fetches or [],
        )
        path.write_text(json.dumps(report.model_dump(mode="json"), indent=2, default=str))

    def test_retry_refetches_failed_products(self, tmp_path):
        """Test that retry calls only crawlers for failed products."""
        data_file = tmp_path / "data.json"
        report_file = tmp_path / "data.report.json"

        self._write_data_file(data_file)
        self._write_report(
            report_file,
            data_file,
            failed_fetches=[
                FailedFetchEntry(
                    url="https://example.com/page",
                    error="Timeout",
                    product="panos",
                    version="12.1.5",
                    issue_type="known",
                ),
            ],
        )

        mock_result = _make_fetch_result()

        mock_crawl = MagicMock(return_value=mock_result)
        with patch.dict(
            "bugdb.crawlers.registry.PRODUCT_WRAPPERS",
            {"panos": mock_crawl},
        ):
            result = runner.invoke(
                app, ["fetch", "--retry", str(report_file), "-o", str(data_file)]
            )

        assert result.exit_code == 0
        mock_crawl.assert_called_once()
        assert "Retry Fetch Complete" in result.stdout

    def test_retry_merges_into_existing_data(self, tmp_path):
        """Test that retry merges results into existing data file."""
        data_file = tmp_path / "data.json"
        report_file = tmp_path / "data.report.json"

        self._write_data_file(data_file)
        self._write_report(
            report_file,
            data_file,
            failed_fetches=[
                FailedFetchEntry(
                    url="https://example.com/page",
                    error="Timeout",
                    product="panos",
                ),
            ],
        )

        retry_result = _make_fetch_result(
            versions=[
                ProductVersion(
                    version="12.1.6",
                    known_issues=[Issue(bug_id="PAN-99", description="New issue")],
                ),
            ],
        )

        with patch.dict(
            "bugdb.crawlers.registry.PRODUCT_WRAPPERS",
            {"panos": MagicMock(return_value=retry_result)},
        ):
            result = runner.invoke(
                app, ["fetch", "--retry", str(report_file), "-o", str(data_file)]
            )

        assert result.exit_code == 0
        merged = json.loads(data_file.read_text())
        # Should have the merged product with versions from both original and retry
        panos = next(p for p in merged["products"] if p["id"] == "panos")
        version_strs = [v["version"] for v in panos["versions"]]
        assert "12.1.5" in version_strs
        assert "12.1.6" in version_strs

    def test_retry_no_failures_exits_cleanly(self, tmp_path):
        """Test that retry with no failures in report exits with message."""
        data_file = tmp_path / "data.json"
        report_file = tmp_path / "data.report.json"

        self._write_data_file(data_file)
        self._write_report(report_file, data_file, failed_fetches=[])

        result = runner.invoke(app, ["fetch", "--retry", str(report_file)])

        assert result.exit_code == 0
        assert "No failed fetches" in result.stdout

    def test_retry_rejects_product_argument(self, tmp_path):
        """Test that --retry rejects product argument."""
        report_file = tmp_path / "report.json"
        report_file.write_text("{}")

        result = runner.invoke(app, ["fetch", "panos", "--retry", str(report_file)])

        assert result.exit_code == 1
        assert "cannot be combined with a product" in result.stdout

    def test_retry_rejects_incremental(self, tmp_path):
        """Test that --retry rejects --incremental."""
        report_file = tmp_path / "report.json"
        report_file.write_text("{}")

        result = runner.invoke(app, ["fetch", "--retry", str(report_file), "--incremental"])

        assert result.exit_code == 1
        assert "cannot be combined with --incremental" in result.stdout

    def test_retry_rejects_version(self, tmp_path):
        """Test that --retry rejects --version."""
        report_file = tmp_path / "report.json"
        report_file.write_text("{}")

        result = runner.invoke(app, ["fetch", "--retry", str(report_file), "--version", "12-1"])

        assert result.exit_code == 1
        assert "cannot be combined with --version" in result.stdout

    def test_retry_missing_report_file(self, tmp_path):
        """Test that --retry fails with missing report file."""
        result = runner.invoke(app, ["fetch", "--retry", str(tmp_path / "nonexistent.json")])

        assert result.exit_code == 1
        assert "not found" in _flat(result.stdout)

    def test_retry_missing_data_file(self, tmp_path):
        """Test that --retry fails when data file from report is missing."""
        report_file = tmp_path / "data.report.json"
        missing_data = tmp_path / "missing.json"

        self._write_report(
            report_file,
            missing_data,
            failed_fetches=[
                FailedFetchEntry(
                    url="https://example.com/page",
                    error="Timeout",
                    product="panos",
                ),
            ],
        )

        result = runner.invoke(app, ["fetch", "--retry", str(report_file), "-o", str(missing_data)])

        assert result.exit_code == 1
        assert "not found" in _flat(result.stdout)

    def test_retry_with_report_generates_new_report(self, tmp_path):
        """Test that --retry combined with --report generates a new report."""
        data_file = tmp_path / "data.json"
        report_file = tmp_path / "data.report.json"

        self._write_data_file(data_file)
        self._write_report(
            report_file,
            data_file,
            failed_fetches=[
                FailedFetchEntry(
                    url="https://example.com/page",
                    error="Timeout",
                    product="panos",
                ),
            ],
        )

        mock_result = _make_fetch_result()

        with patch.dict(
            "bugdb.crawlers.registry.PRODUCT_WRAPPERS",
            {"panos": MagicMock(return_value=mock_result)},
        ):
            result = runner.invoke(
                app,
                ["fetch", "--retry", str(report_file), "--report", "-o", str(data_file)],
            )

        assert result.exit_code == 0
        # Report should be regenerated
        new_report = json.loads(report_file.read_text())
        assert "total_products" in new_report

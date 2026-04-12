"""Tests for BugDB data models."""

import pytest
from pydantic import ValidationError

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


class TestIssue:
    """Tests for Issue model."""

    def test_minimal_issue(self):
        """Test creating issue with only required fields."""
        issue = Issue(bug_id="PAN-12345", description="Test issue")
        assert issue.bug_id == "PAN-12345"
        assert issue.description == "Test issue"
        assert issue.symptoms is None
        assert issue.workaround is None
        assert issue.affected_components is None

    def test_full_issue(self):
        """Test creating issue with all fields."""
        issue = Issue(
            bug_id="PAN-12345",
            description="Test issue description",
            symptoms="Test symptoms",
            workaround="Test workaround",
            affected_components=["Component1", "Component2"],
        )
        assert issue.bug_id == "PAN-12345"
        assert issue.symptoms == "Test symptoms"
        assert issue.workaround == "Test workaround"
        assert issue.affected_components == ["Component1", "Component2"]

    def test_issue_missing_required_fields(self):
        """Test that missing required fields raise validation error."""
        with pytest.raises(ValidationError):
            Issue(bug_id="PAN-12345")  # Missing description

        with pytest.raises(ValidationError):
            Issue(description="Test")  # Missing bug_id


class TestProductVersion:
    """Tests for ProductVersion model."""

    def test_minimal_version(self):
        """Test creating version with only required fields."""
        version = ProductVersion(version="11.1.0")
        assert version.version == "11.1.0"
        assert version.release_date is None
        assert version.known_issues == []
        assert version.addressed_issues == []

    def test_version_with_issues(self):
        """Test creating version with issues."""
        known = Issue(bug_id="PAN-1", description="Known issue")
        addressed = Issue(bug_id="PAN-2", description="Fixed issue")

        version = ProductVersion(
            version="11.1.0",
            release_date="2026-03-01",
            known_issues=[known],
            addressed_issues=[addressed],
        )

        assert len(version.known_issues) == 1
        assert len(version.addressed_issues) == 1
        assert version.known_issues[0].bug_id == "PAN-1"
        assert version.addressed_issues[0].bug_id == "PAN-2"


class TestProduct:
    """Tests for Product model."""

    def test_minimal_product(self):
        """Test creating product with only required fields."""
        product = Product(id="pan-os", name="PAN-OS")
        assert product.id == "pan-os"
        assert product.name == "PAN-OS"
        assert product.versions == []

    def test_product_with_versions(self):
        """Test creating product with versions."""
        version = ProductVersion(version="11.1.0")
        product = Product(id="pan-os", name="PAN-OS", versions=[version])

        assert len(product.versions) == 1
        assert product.versions[0].version == "11.1.0"


class TestBugDatabase:
    """Tests for BugDatabase model."""

    def test_empty_database(self):
        """Test creating empty database."""
        db = BugDatabase()
        assert db.metadata is not None
        assert db.products == []

    def test_database_with_products(self):
        """Test creating database with products."""
        product = Product(id="pan-os", name="PAN-OS")
        db = BugDatabase(products=[product])

        assert len(db.products) == 1
        assert db.products[0].id == "pan-os"

    def test_database_serialization(self):
        """Test database can be serialized to dict/JSON."""
        issue = Issue(
            bug_id="PAN-12345",
            description="Test issue",
        )
        version = ProductVersion(
            version="11.1.0",
            known_issues=[issue],
        )
        product = Product(id="pan-os", name="PAN-OS", versions=[version])
        db = BugDatabase(products=[product])

        data = db.model_dump(mode="json")

        assert data["products"][0]["id"] == "pan-os"
        assert data["products"][0]["versions"][0]["version"] == "11.1.0"
        assert data["products"][0]["versions"][0]["known_issues"][0]["bug_id"] == "PAN-12345"


class TestMetadata:
    """Tests for Metadata model."""

    def test_default_metadata(self):
        """Test default metadata values."""
        metadata = Metadata()
        assert metadata.version == "1.0.0"
        assert metadata.source == "Palo Alto Networks Release Notes"
        assert metadata.generated_at is not None

    def test_custom_metadata(self):
        """Test custom metadata values."""
        metadata = Metadata(
            version="2.0.0",
            source="Custom Source",
        )
        assert metadata.version == "2.0.0"
        assert metadata.source == "Custom Source"


class TestFailedFetchEntry:
    """Tests for FailedFetchEntry model."""

    def test_minimal_entry(self):
        """Test creating entry with only required fields."""
        entry = FailedFetchEntry(
            url="https://example.com/page",
            error="Timeout",
            product="panos",
        )
        assert entry.url == "https://example.com/page"
        assert entry.error == "Timeout"
        assert entry.product == "panos"
        assert entry.version is None
        assert entry.issue_type is None

    def test_full_entry(self):
        """Test creating entry with all fields."""
        entry = FailedFetchEntry(
            url="https://example.com/page",
            error="Timeout",
            product="panos",
            version="12.1.5-h2",
            issue_type="known",
        )
        assert entry.version == "12.1.5-h2"
        assert entry.issue_type == "known"


class TestProductStats:
    """Tests for ProductStats model."""

    def test_product_stats_creation(self):
        """Test creating product stats."""
        stats = ProductStats(
            product_id="panos",
            product_name="PAN-OS",
            versions_fetched=45,
            known_issues_count=1200,
            addressed_issues_count=1800,
            failed_fetch_count=2,
        )
        assert stats.product_id == "panos"
        assert stats.versions_fetched == 45
        assert stats.failed_fetch_count == 2


class TestFetchReport:
    """Tests for FetchReport model."""

    def test_fetch_report_creation(self):
        """Test creating a fetch report with all fields."""
        report = FetchReport(
            bugdb_file="assets/bugdb.json",
            total_products=2,
            total_versions=10,
            total_known_issues=100,
            total_addressed_issues=200,
            product_stats=[
                ProductStats(
                    product_id="panos",
                    product_name="PAN-OS",
                    versions_fetched=5,
                    known_issues_count=50,
                    addressed_issues_count=100,
                    failed_fetch_count=1,
                ),
            ],
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
        assert report.total_products == 2
        assert len(report.product_stats) == 1
        assert len(report.failed_fetches) == 1
        assert report.generated_at is not None

    def test_fetch_report_serialization_roundtrip(self):
        """Test that a report can be serialized and deserialized."""
        report = FetchReport(
            bugdb_file="assets/bugdb.json",
            total_products=1,
            total_versions=3,
            total_known_issues=10,
            total_addressed_issues=20,
            product_stats=[],
            failed_fetches=[],
        )
        data = report.model_dump(mode="json")
        restored = FetchReport.model_validate(data)
        assert restored.bugdb_file == "assets/bugdb.json"
        assert restored.total_products == 1
        assert restored.failed_fetches == []

    def test_fetch_report_empty_failures(self):
        """Test report with no failures."""
        report = FetchReport(
            bugdb_file="bugdb.json",
            total_products=5,
            total_versions=20,
            total_known_issues=500,
            total_addressed_issues=800,
        )
        assert report.failed_fetches == []
        assert report.product_stats == []

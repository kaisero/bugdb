"""Tests for BugDB data models."""

import pytest
from pydantic import ValidationError

from bugdb.models import (
    BugDatabase,
    Issue,
    Metadata,
    Product,
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

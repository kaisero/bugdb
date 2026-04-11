"""Pydantic data models for BugDB."""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class ChangeType(str, Enum):
    """Type of change in a release."""

    FEATURE = "feature"
    IMPROVEMENT = "improvement"
    FIX = "fix"
    BREAKING = "breaking"


class ReleaseChange(BaseModel):
    """A single change in a release."""

    type: ChangeType = Field(..., description="Type of change")
    description: str = Field(..., description="Description of the change")


class Release(BaseModel):
    """A release with its changes."""

    version: str = Field(..., description="Version string (e.g., 1.0.0)")
    date: str = Field(..., description="Release date (YYYY-MM-DD)")
    title: str | None = Field(None, description="Optional release title")
    changes: list[ReleaseChange] = Field(
        default_factory=list, description="List of changes in this release"
    )


class ReleaseNotes(BaseModel):
    """Root model for release notes."""

    releases: list[Release] = Field(default_factory=list, description="List of releases")


class Issue(BaseModel):
    """A bug or issue entry."""

    bug_id: str = Field(..., description="Unique bug identifier (e.g., PAN-300637)")
    description: str = Field(..., description="Issue description")
    symptoms: str | None = Field(None, description="Observable symptoms")
    workaround: str | None = Field(None, description="Known workaround")
    fix_info: str | None = Field(
        None,
        description="Additional fix information (e.g., 'Resolved in Prisma Access Agent 25.3')",
    )
    affected_components: list[str] | None = Field(None, description="List of affected components")
    release_date: str | None = Field(
        None, description="Release date when the fix was deployed (YYYY-MM-DD format)"
    )


class ProductVersion(BaseModel):
    """A specific version of a product with its known and addressed issues."""

    version: str = Field(..., description="Version string (e.g., 11.1.13)")
    release_date: str | None = Field(None, description="Release date (YYYY-MM-DD)")
    known_issues: list[Issue] = Field(
        default_factory=list, description="Known issues in this version"
    )
    addressed_issues: list[Issue] = Field(
        default_factory=list, description="Issues addressed in this version"
    )


class Product(BaseModel):
    """A product with its versions and issues."""

    id: str = Field(..., description="Product identifier (e.g., pan-os)")
    name: str = Field(..., description="Display name (e.g., PAN-OS)")
    versions: list[ProductVersion] = Field(default_factory=list, description="Product versions")


class Metadata(BaseModel):
    """Database metadata."""

    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Generation timestamp",
    )
    version: str = Field(default="1.0.0", description="Schema version")
    source: str = Field(default="Palo Alto Networks Release Notes", description="Data source")


class BugDatabase(BaseModel):
    """Root model for the bug database."""

    metadata: Metadata = Field(default_factory=Metadata)
    products: list[Product] = Field(default_factory=list, description="Products list")


class FailedFetchEntry(BaseModel):
    """A failed URL fetch entry for the fetch report."""

    url: str = Field(..., description="URL that failed to fetch")
    error: str = Field(..., description="Error message")
    product: str = Field(..., description="Product ID")
    version: str | None = Field(None, description="Product version")
    issue_type: str | None = Field(None, description="'known' or 'addressed'")


class ProductStats(BaseModel):
    """Per-product fetch statistics."""

    product_id: str = Field(..., description="Product identifier")
    product_name: str = Field(..., description="Product display name")
    versions_fetched: int = Field(..., description="Number of versions fetched")
    known_issues_count: int = Field(..., description="Number of known issues fetched")
    addressed_issues_count: int = Field(..., description="Number of addressed issues fetched")
    failed_fetch_count: int = Field(..., description="Number of failed URL fetches")


class FetchReport(BaseModel):
    """Report generated after a fetch operation."""

    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Report generation timestamp",
    )
    data_file: str = Field(..., description="Path to the associated data output file")
    total_products: int = Field(..., description="Total number of products fetched")
    total_versions: int = Field(..., description="Total number of versions fetched")
    total_known_issues: int = Field(..., description="Total known issues fetched")
    total_addressed_issues: int = Field(..., description="Total addressed issues fetched")
    product_stats: list[ProductStats] = Field(
        default_factory=list, description="Per-product statistics"
    )
    failed_fetches: list[FailedFetchEntry] = Field(
        default_factory=list, description="URLs that could not be crawled"
    )

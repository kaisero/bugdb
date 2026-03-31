"""Pydantic data models for BugDB."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

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
    title: Optional[str] = Field(None, description="Optional release title")
    changes: list[ReleaseChange] = Field(
        default_factory=list, description="List of changes in this release"
    )


class ReleaseNotes(BaseModel):
    """Root model for release notes."""

    releases: list[Release] = Field(
        default_factory=list, description="List of releases"
    )


class Issue(BaseModel):
    """A bug or issue entry."""

    bug_id: str = Field(..., description="Unique bug identifier (e.g., PAN-300637)")
    description: str = Field(..., description="Issue description")
    symptoms: Optional[str] = Field(None, description="Observable symptoms")
    workaround: Optional[str] = Field(None, description="Known workaround")
    fix_info: Optional[str] = Field(
        None, description="Additional fix information (e.g., 'Resolved in Prisma Access Agent 25.3')"
    )
    affected_components: Optional[list[str]] = Field(
        None, description="List of affected components"
    )
    release_date: Optional[str] = Field(
        None, description="Release date when the fix was deployed (YYYY-MM-DD format)"
    )


class ProductVersion(BaseModel):
    """A specific version of a product with its known and addressed issues."""

    version: str = Field(..., description="Version string (e.g., 11.1.13)")
    release_date: Optional[str] = Field(None, description="Release date (YYYY-MM-DD)")
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
    versions: list[ProductVersion] = Field(
        default_factory=list, description="Product versions"
    )


class Metadata(BaseModel):
    """Database metadata."""

    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Generation timestamp",
    )
    version: str = Field(default="1.0.0", description="Schema version")
    source: str = Field(
        default="Palo Alto Networks Release Notes", description="Data source"
    )


class BugDatabase(BaseModel):
    """Root model for the bug database."""

    metadata: Metadata = Field(default_factory=Metadata)
    products: list[Product] = Field(default_factory=list, description="Products list")

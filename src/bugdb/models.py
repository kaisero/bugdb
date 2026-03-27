"""Pydantic data models for BugDB."""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class Issue(BaseModel):
    """A bug or issue entry."""

    bug_id: str = Field(..., description="Unique bug identifier (e.g., PAN-300637)")
    description: str = Field(..., description="Issue description")
    symptoms: Optional[str] = Field(None, description="Observable symptoms")
    workaround: Optional[str] = Field(None, description="Known workaround")
    affected_components: Optional[list[str]] = Field(
        None, description="List of affected components"
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

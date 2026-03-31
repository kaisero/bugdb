"""Data classes for the crawler module."""

from dataclasses import dataclass
from typing import Optional

from bugdb.models import Product, ProductVersion


@dataclass
class VersionInfo:
    """Information about a product version."""

    version: str
    known_issues_urls: list[str]
    addressed_issues_urls: list[str]


@dataclass
class FailedFetch:
    """Information about a failed URL fetch."""

    url: str
    error: str
    product: str
    version: Optional[str] = None
    issue_type: Optional[str] = None  # "known" or "addressed"


@dataclass
class CrawlResult:
    """Result of a crawl operation."""

    product: Product
    failed_fetches: list[FailedFetch]


@dataclass
class VersionCrawlResult:
    """Result of crawling a single version."""

    product_version: ProductVersion
    failed_fetches: list[FailedFetch]


@dataclass
class FetchResult:
    """Result of a complete fetch operation (module-level)."""

    from bugdb.models import BugDatabase
    database: BugDatabase
    failed_fetches: list[FailedFetch]


@dataclass
class PluginConfig:
    """Configuration for a Panorama/VM-Series plugin crawler.

    This allows a single generic crawler implementation to handle
    all plugin products with different URL structures.
    """

    # Product identifiers
    product_id: str  # e.g., "vm-series-plugin", "plugin-aws"
    product_name: str  # e.g., "VM-Series Plugin", "Panorama Plugin for AWS"

    # URL path to the main plugin page (relative to docs.paloaltonetworks.com)
    base_url: str  # e.g., "/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-aws"

    # Keywords to identify version links (used for version extraction from URLs)
    version_link_patterns: list[str]  # e.g., ["aws-plugin-", "panorama-plugin-for-aws-"]

    # Keywords to identify known/addressed issues links
    known_issues_keywords: list[str] = None  # Default: ["known-issues"]
    addressed_issues_keywords: list[str] = None  # Default: ["addressed-issues", "fixed-issues"]

    def __post_init__(self):
        if self.known_issues_keywords is None:
            self.known_issues_keywords = ["known-issues"]
        if self.addressed_issues_keywords is None:
            self.addressed_issues_keywords = ["addressed-issues", "fixed-issues"]

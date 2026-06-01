"""Cloud NGFW crawlers implementation (Azure and AWS)."""

import asyncio
import logging
from typing import Optional

from bugdb.models import Product, ProductVersion

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch
from ..sitemap_discovery import discover_saas_urls
from .saas import _fetch_saas_pages

logger = logging.getLogger(__name__)


class CloudNGFWAzureCrawler(BaseCrawler):
    """Crawler for Cloud NGFW for Azure release notes.

    Cloud NGFW for Azure is a SaaS product without version releases.
    All issues are on single known/addressed issues pages.
    """

    product_id = "cloud-ngfw-azure"
    product_name = "Cloud NGFW for Azure"

    async def crawl(
        self,
        major_versions: Optional[list[str]] = None,
        skip_versions: Optional[set[str]] = None,
    ) -> CrawlResult:
        """Crawl Cloud NGFW for Azure release notes.

        Note: major_versions and skip_versions are ignored since this is
        a versionless SaaS product.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        self._log("Crawling Cloud NGFW for Azure...")

        # Fallbacks used only when no sitemap is injected. The current
        # docs paths under /cloud-ngfw-azure/* (the old /cloud-ngfw/azure/*
        # paths return 301s; the addressed-issues redirect goes to a
        # "What's New" page that has no bug table).
        default_known = (
            "/cloud-ngfw-azure/release-notes/cloud-ngfw-for-azure-known-issues"
        )
        default_addressed = (
            "/cloud-ngfw-azure/release-notes/cloud-ngfw-for-azure-addressed-issues"
        )
        known_urls, addressed_urls = discover_saas_urls(
            self._sitemap, self.product_id, manifest=self._manifest
        )
        if not known_urls:
            known_urls = [default_known]
        if not addressed_urls:
            addressed_urls = [default_addressed]

        known_issues, addressed_issues, failed_fetches = await _fetch_saas_pages(
            self, known_urls, addressed_urls
        )

        # Retry failed fetches
        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(
                failed_fetches
            )
            failed_fetches = still_failed

        # Deduplicate
        known_issues = self._deduplicate_issues(known_issues)
        addressed_issues = self._deduplicate_issues(addressed_issues)

        # Create single "SaaS" version
        versions = []
        if known_issues or addressed_issues:
            versions.append(ProductVersion(
                version="SaaS",
                known_issues=known_issues,
                addressed_issues=addressed_issues,
            ))

        return CrawlResult(
            product=Product(
                id=self.product_id,
                name=self.product_name,
                versions=versions,
            ),
            failed_fetches=failed_fetches,
        )


class CloudNGFWAWSCrawler(BaseCrawler):
    """Crawler for Cloud NGFW for AWS release notes.

    Cloud NGFW for AWS is a SaaS product without version releases.
    It only has a known issues page (no addressed issues).
    """

    product_id = "cloud-ngfw-aws"
    product_name = "Cloud NGFW for AWS"

    async def crawl(
        self,
        major_versions: Optional[list[str]] = None,
        skip_versions: Optional[set[str]] = None,
    ) -> CrawlResult:
        """Crawl Cloud NGFW for AWS release notes.

        Note: major_versions and skip_versions are ignored since this is
        a versionless SaaS product.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        self._log("Crawling Cloud NGFW for AWS...")

        default_known = (
            "/cloud-ngfw-aws/release-notes/cloud-ngfw-for-aws-known-issues"
        )
        known_urls, _ = discover_saas_urls(
            self._sitemap, self.product_id, manifest=self._manifest
        )
        if not known_urls:
            known_urls = [default_known]

        known_issues, _addressed_unused, failed_fetches = await _fetch_saas_pages(
            self, known_urls, []
        )

        # Retry failed fetches
        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(
                failed_fetches
            )
            failed_fetches = still_failed

        # Deduplicate
        known_issues = self._deduplicate_issues(known_issues)

        # Create single "SaaS" version
        versions = []
        if known_issues:
            versions.append(ProductVersion(
                version="SaaS",
                known_issues=known_issues,
                addressed_issues=[],
            ))

        return CrawlResult(
            product=Product(
                id=self.product_id,
                name=self.product_name,
                versions=versions,
            ),
            failed_fetches=failed_fetches,
        )

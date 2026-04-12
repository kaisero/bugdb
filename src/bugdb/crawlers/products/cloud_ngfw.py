"""Cloud NGFW crawlers implementation (Azure and AWS)."""

import asyncio
import logging

from bugdb.models import Product, ProductVersion

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch

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
        major_versions: list[str] | None = None,
        skip_versions: set[str] | None = None,
    ) -> CrawlResult:
        """Crawl Cloud NGFW for Azure release notes.

        Note: major_versions and skip_versions are ignored since this is
        a versionless SaaS product.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        logger.info("Crawling Cloud NGFW for Azure...")
        self._set_task_total(1, f"{self.product_name}: fetching")
        failed_fetches: list[FailedFetch] = []

        known_issues_url = "/cloud-ngfw-azure/release-notes/cloud-ngfw-for-azure-known-issues"
        addressed_issues_url = (
            "/cloud-ngfw-azure/release-notes/cloud-ngfw-for-azure-addressed-issues"
        )

        # Fetch both pages in parallel
        fetch_tasks = [
            self._fetch_page_with_semaphore(known_issues_url),
            self._fetch_page_with_semaphore(addressed_issues_url),
        ]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        known_issues = []
        addressed_issues = []

        # Parse known issues
        if not isinstance(results[0], Exception):
            for table in results[0].find_all("table"):
                if table.find_parent("table"):
                    continue
                known_issues.extend(self._parse_issues_table(table))
            logger.info(f"  Found {len(known_issues)} known issues")
        else:
            logger.error(f"Error fetching known issues: {results[0]}")
            failed_fetches.append(
                FailedFetch(
                    url=known_issues_url,
                    error=str(results[0]),
                    product=self.product_id,
                    issue_type="known",
                )
            )

        # Parse addressed issues
        if not isinstance(results[1], Exception):
            for table in results[1].find_all("table"):
                if table.find_parent("table"):
                    continue
                addressed_issues.extend(self._parse_issues_table(table))
            logger.info(f"  Found {len(addressed_issues)} addressed issues")
        else:
            logger.error(f"Error fetching addressed issues: {results[1]}")
            failed_fetches.append(
                FailedFetch(
                    url=addressed_issues_url,
                    error=str(results[1]),
                    product=self.product_id,
                    issue_type="addressed",
                )
            )

        # Retry failed fetches
        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(failed_fetches)
            failed_fetches = still_failed

        # Deduplicate
        known_issues = self._deduplicate_issues(known_issues)
        addressed_issues = self._deduplicate_issues(addressed_issues)

        # Create single "SaaS" version
        versions = []
        if known_issues or addressed_issues:
            versions.append(
                ProductVersion(
                    version="SaaS",
                    known_issues=known_issues,
                    addressed_issues=addressed_issues,
                )
            )

        self._advance_task(f"{self.product_name}: done")

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
        major_versions: list[str] | None = None,
        skip_versions: set[str] | None = None,
    ) -> CrawlResult:
        """Crawl Cloud NGFW for AWS release notes.

        Note: major_versions and skip_versions are ignored since this is
        a versionless SaaS product.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        logger.info("Crawling Cloud NGFW for AWS...")
        self._set_task_total(1, f"{self.product_name}: fetching")
        failed_fetches: list[FailedFetch] = []

        known_issues_url = "/cloud-ngfw-aws/release-notes/cloud-ngfw-for-aws-known-issues"

        known_issues = []

        try:
            soup = await self._fetch_page_with_semaphore(known_issues_url)
            for table in soup.find_all("table"):
                if table.find_parent("table"):
                    continue
                known_issues.extend(self._parse_issues_table(table))
            logger.info(f"  Found {len(known_issues)} known issues")
        except Exception as e:
            logger.error(f"Error fetching known issues: {e}")
            failed_fetches.append(
                FailedFetch(
                    url=known_issues_url,
                    error=str(e),
                    product=self.product_id,
                    issue_type="known",
                )
            )

        # Retry failed fetches
        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(failed_fetches)
            failed_fetches = still_failed

        # Deduplicate
        known_issues = self._deduplicate_issues(known_issues)

        # Create single "SaaS" version
        versions = []
        if known_issues:
            versions.append(
                ProductVersion(
                    version="SaaS",
                    known_issues=known_issues,
                    addressed_issues=[],
                )
            )

        self._advance_task(f"{self.product_name}: done")

        return CrawlResult(
            product=Product(
                id=self.product_id,
                name=self.product_name,
                versions=versions,
            ),
            failed_fetches=failed_fetches,
        )

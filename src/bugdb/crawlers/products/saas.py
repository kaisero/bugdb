"""SaaS product crawlers (RBI, AI Runtime Security, Strata Logging Service)."""

import asyncio
import logging

from bugdb.models import Product, ProductVersion

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch

logger = logging.getLogger(__name__)


class RemoteBrowserIsolationCrawler(BaseCrawler):
    """Crawler for Remote Browser Isolation release notes.

    RBI is a SaaS product without version releases.
    It only has a known issues page (no addressed issues).
    """

    product_id = "remote-browser-isolation"
    product_name = "Remote Browser Isolation"

    async def crawl(
        self,
        major_versions: list[str] | None = None,
        skip_versions: set[str] | None = None,
    ) -> CrawlResult:
        """Crawl Remote Browser Isolation release notes.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        self._log("Crawling Remote Browser Isolation...")
        failed_fetches: list[FailedFetch] = []

        known_issues_url = (
            "/remote-browser-isolation/release-notes/"
            "remote-browser-isolation-release-information/"
            "remote-browser-isolation-known-issues"
        )

        known_issues = []

        try:
            soup = await self._fetch_page_with_semaphore(known_issues_url)
            for table in soup.find_all("table"):
                if table.find_parent("table"):
                    continue
                known_issues.extend(self._parse_issues_table(table))
            self._log(f"  Found {len(known_issues)} known issues")
        except Exception as e:
            self._log(f"  Error fetching known issues: {e}")
            failed_fetches.append(
                FailedFetch(
                    url=known_issues_url,
                    error=str(e),
                    product=self.product_id,
                    issue_type="known",
                )
            )

        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(failed_fetches)
            failed_fetches = still_failed

        known_issues = self._deduplicate_issues(known_issues)

        versions = []
        if known_issues:
            versions.append(
                ProductVersion(
                    version="SaaS",
                    known_issues=known_issues,
                    addressed_issues=[],
                )
            )

        return CrawlResult(
            product=Product(
                id=self.product_id,
                name=self.product_name,
                versions=versions,
            ),
            failed_fetches=failed_fetches,
        )


class AIRuntimeSecurityCrawler(BaseCrawler):
    """Crawler for AI Runtime Security release notes.

    AI Runtime Security (Prisma AIRS) is a SaaS product.
    It has both known and addressed issues pages.
    """

    product_id = "ai-runtime-security"
    product_name = "AI Runtime Security"

    async def crawl(
        self,
        major_versions: list[str] | None = None,
        skip_versions: set[str] | None = None,
    ) -> CrawlResult:
        """Crawl AI Runtime Security release notes.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        self._log("Crawling AI Runtime Security...")
        failed_fetches: list[FailedFetch] = []

        known_issues_url = "/ai-runtime-security/release-notes/known-issues"
        addressed_issues_url = "/ai-runtime-security/release-notes/addressed-issues"

        fetch_tasks = [
            self._fetch_page_with_semaphore(known_issues_url),
            self._fetch_page_with_semaphore(addressed_issues_url),
        ]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        known_issues = []
        addressed_issues = []

        if not isinstance(results[0], Exception):
            for table in results[0].find_all("table"):
                if table.find_parent("table"):
                    continue
                known_issues.extend(self._parse_issues_table(table))
            self._log(f"  Found {len(known_issues)} known issues")
        else:
            self._log(f"  Error fetching known issues: {results[0]}")
            failed_fetches.append(
                FailedFetch(
                    url=known_issues_url,
                    error=str(results[0]),
                    product=self.product_id,
                    issue_type="known",
                )
            )

        if not isinstance(results[1], Exception):
            for table in results[1].find_all("table"):
                if table.find_parent("table"):
                    continue
                addressed_issues.extend(self._parse_issues_table(table))
            self._log(f"  Found {len(addressed_issues)} addressed issues")
        else:
            self._log(f"  Error fetching addressed issues: {results[1]}")
            failed_fetches.append(
                FailedFetch(
                    url=addressed_issues_url,
                    error=str(results[1]),
                    product=self.product_id,
                    issue_type="addressed",
                )
            )

        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(failed_fetches)
            failed_fetches = still_failed

        known_issues = self._deduplicate_issues(known_issues)
        addressed_issues = self._deduplicate_issues(addressed_issues)

        versions = []
        if known_issues or addressed_issues:
            versions.append(
                ProductVersion(
                    version="SaaS",
                    known_issues=known_issues,
                    addressed_issues=addressed_issues,
                )
            )

        return CrawlResult(
            product=Product(
                id=self.product_id,
                name=self.product_name,
                versions=versions,
            ),
            failed_fetches=failed_fetches,
        )


class StrataLoggingServiceCrawler(BaseCrawler):
    """Crawler for Strata Logging Service release notes.

    Strata Logging Service is a SaaS product.
    It has both known and addressed issues pages.
    """

    product_id = "strata-logging-service"
    product_name = "Strata Logging Service"

    async def crawl(
        self,
        major_versions: list[str] | None = None,
        skip_versions: set[str] | None = None,
    ) -> CrawlResult:
        """Crawl Strata Logging Service release notes.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        self._log("Crawling Strata Logging Service...")
        failed_fetches: list[FailedFetch] = []

        known_issues_url = "/strata-logging-service/release-notes/known-issues"
        addressed_issues_url = "/strata-logging-service/release-notes/addressed-issues"

        fetch_tasks = [
            self._fetch_page_with_semaphore(known_issues_url),
            self._fetch_page_with_semaphore(addressed_issues_url),
        ]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        known_issues = []
        addressed_issues = []

        if not isinstance(results[0], Exception):
            for table in results[0].find_all("table"):
                if table.find_parent("table"):
                    continue
                known_issues.extend(self._parse_issues_table(table))
            self._log(f"  Found {len(known_issues)} known issues")
        else:
            self._log(f"  Error fetching known issues: {results[0]}")
            failed_fetches.append(
                FailedFetch(
                    url=known_issues_url,
                    error=str(results[0]),
                    product=self.product_id,
                    issue_type="known",
                )
            )

        if not isinstance(results[1], Exception):
            for table in results[1].find_all("table"):
                if table.find_parent("table"):
                    continue
                addressed_issues.extend(self._parse_issues_table(table))
            self._log(f"  Found {len(addressed_issues)} addressed issues")
        else:
            self._log(f"  Error fetching addressed issues: {results[1]}")
            failed_fetches.append(
                FailedFetch(
                    url=addressed_issues_url,
                    error=str(results[1]),
                    product=self.product_id,
                    issue_type="addressed",
                )
            )

        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(failed_fetches)
            failed_fetches = still_failed

        known_issues = self._deduplicate_issues(known_issues)
        addressed_issues = self._deduplicate_issues(addressed_issues)

        versions = []
        if known_issues or addressed_issues:
            versions.append(
                ProductVersion(
                    version="SaaS",
                    known_issues=known_issues,
                    addressed_issues=addressed_issues,
                )
            )

        return CrawlResult(
            product=Product(
                id=self.product_id,
                name=self.product_name,
                versions=versions,
            ),
            failed_fetches=failed_fetches,
        )

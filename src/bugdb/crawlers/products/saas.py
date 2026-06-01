"""SaaS product crawlers (RBI, AI Runtime Security, Strata Logging Service)."""

import asyncio
import logging

from bugdb.models import Product, ProductVersion

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch
from ..sitemap_discovery import discover_saas_urls


async def _fetch_saas_pages(
    crawler: BaseCrawler,
    known_urls: list[str],
    addressed_urls: list[str],
) -> tuple[list, list, list[FailedFetch]]:
    """Fetch known/addressed pages in parallel, parse, dedupe-by-call-site.

    Shared by every SaaS crawler in this module. Returns three lists:
    `(known_issues, addressed_issues, failed_fetches)`. Issues are NOT
    deduplicated here — that's the caller's job because some products
    bucket the same page into both lists (known-and-addressed pages).
    """
    tasks = []
    url_kinds: list[tuple[str, str]] = []
    for u in known_urls:
        tasks.append(crawler._fetch_page_with_semaphore(u))
        url_kinds.append(("known", u))
    for u in addressed_urls:
        tasks.append(crawler._fetch_page_with_semaphore(u))
        url_kinds.append(("addressed", u))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    known_issues: list = []
    addressed_issues: list = []
    failed_fetches: list[FailedFetch] = []

    for (kind, url), result in zip(url_kinds, results, strict=True):
        if isinstance(result, Exception):
            crawler._log(f"  Error fetching {kind} issues: {result}")
            failed_fetches.append(
                FailedFetch(
                    url=url,
                    error=str(result),
                    product=crawler.product_id,
                    issue_type=kind,
                )
            )
            continue
        for table in result.find_all("table"):
            if table.find_parent("table"):
                continue
            parsed = crawler._parse_issues_table(table)
            if kind == "known":
                known_issues.extend(parsed)
            else:
                addressed_issues.extend(parsed)
    return known_issues, addressed_issues, failed_fetches


logger = logging.getLogger(__name__)


class RemoteBrowserIsolationCrawler(BaseCrawler):
    """Crawler for Remote Browser Isolation release notes.

    RBI is a SaaS product without version releases.
    It only has a known issues page (no addressed issues).
    """

    product_id = "remote-browser-isolation"
    product_name = "Remote Browser Isolation"

    # Fallback used only when the sitemap is unavailable. The legacy
    # `/access/docs/...` path is stale (404 on the live site); kept here
    # so older offline test fixtures still work.
    _DEFAULT_KNOWN_ISSUES_URL = (
        "/remote-browser-isolation/release-notes/"
        "remote-browser-isolation-release-information/"
        "remote-browser-isolation-known-issues"
    )

    async def crawl(
        self,
        major_versions: list[str] | None = None,
        skip_versions: set[str] | None = None,
    ) -> CrawlResult:
        """Crawl Remote Browser Isolation release notes.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        logger.info("Crawling Remote Browser Isolation...")
        self._set_task_total(1, f"{self.product_name}: fetching")
        failed_fetches: list[FailedFetch] = []

        known_urls, _ = discover_saas_urls(self._sitemap, self.product_id, manifest=self._manifest)
        if not known_urls:
            known_urls = [self._DEFAULT_KNOWN_ISSUES_URL]

        known_issues = []

        for known_issues_url in known_urls:
            try:
                soup = await self._fetch_page_with_semaphore(known_issues_url)
                for table in soup.find_all("table"):
                    if table.find_parent("table"):
                        continue
                    known_issues.extend(self._parse_issues_table(table))
                logger.info(f"  Found {len(known_issues)} known issues")
            except Exception as e:
                logger.error(f"  Error fetching known issues: {e}")
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

        self._advance_task(f"{self.product_name}: done")

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

    # Fallbacks only used when no sitemap was injected. The legacy
    # `/ai-runtime-security/docs/release-notes/...` path is stale (404).
    _DEFAULT_KNOWN_ISSUES_URL = "/ai-runtime-security/release-notes/known-issues"
    _DEFAULT_ADDRESSED_ISSUES_URL = "/ai-runtime-security/release-notes/addressed-issues"

    async def crawl(
        self,
        major_versions: list[str] | None = None,
        skip_versions: set[str] | None = None,
    ) -> CrawlResult:
        """Crawl AI Runtime Security release notes.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        logger.info("Crawling AI Runtime Security...")
        self._set_task_total(1, f"{self.product_name}: fetching")

        known_urls, addressed_urls = discover_saas_urls(
            self._sitemap, self.product_id, manifest=self._manifest
        )
        if not known_urls:
            known_urls = [self._DEFAULT_KNOWN_ISSUES_URL]
        if not addressed_urls:
            addressed_urls = [self._DEFAULT_ADDRESSED_ISSUES_URL]

        known_issues, addressed_issues, failed_fetches = await _fetch_saas_pages(
            self, known_urls, addressed_urls
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

        self._advance_task(f"{self.product_name}: done")

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
        logger.info("Crawling Strata Logging Service...")
        self._set_task_total(1, f"{self.product_name}: fetching")

        default_known = "/strata-logging-service/release-notes/known-issues"
        default_addressed = "/strata-logging-service/release-notes/addressed-issues"
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

        self._advance_task(f"{self.product_name}: done")

        return CrawlResult(
            product=Product(
                id=self.product_id,
                name=self.product_name,
                versions=versions,
            ),
            failed_fetches=failed_fetches,
        )

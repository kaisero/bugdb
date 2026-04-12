"""Device Security (IoT Security) crawler implementation."""

import asyncio
import logging
import re

from bugdb.models import Issue, Product, ProductVersion

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch

logger = logging.getLogger(__name__)


class DeviceSecurityCrawler(BaseCrawler):
    """Crawler for Device Security (IoT Security) release notes.

    Device Security organizes issues by year (e.g., 2025, 2026)
    with sections for each feature within the year pages.
    """

    product_id = "device-security"
    product_name = "Device Security"

    async def discover_years(self) -> list[str]:
        """Discover available years from the Device Security index.

        Returns:
            List of year strings (e.g., ["2026", "2025", "2024"]).
        """
        years = []
        index_url = "/iot/release-notes"

        try:
            soup = await self._fetch_page_with_semaphore(index_url)

            for link in soup.find_all("a", href=True):
                href = link["href"]
                # Look for year patterns in URLs
                # (e.g., known-issues-in-2025, addressed-issues-in-2026)
                match = re.search(r"(?:known-issues|addressed-issues)(?:/|-in-)(\d{4})", href)
                if match:
                    year = match.group(1)
                    if year not in years and int(year) >= 2020:
                        years.append(year)

        except Exception as e:
            logger.error("Error discovering Device Security years: %s", e)
            logger.error(f"Error discovering years: {e}")

        # Sort descending (newest first)
        years.sort(reverse=True)
        return years

    def _parse_device_security_issues_page(self, soup, issue_type: str) -> dict[str, list[Issue]]:
        """Parse Device Security issues page organized by feature.

        The page has sections with feature headers followed by issue tables.
        We use the year/feature as the "version" for grouping.

        Args:
            soup: BeautifulSoup parsed page.
            issue_type: Either "known" or "addressed".

        Returns:
            Dict mapping feature names to lists of Issue objects.
        """
        results: dict[str, list[Issue]] = {}
        current_feature: str | None = None

        for element in soup.find_all(["h2", "h3", "h4", "table"]):
            if element.name in ["h2", "h3", "h4"]:
                header_text = element.get_text(strip=True)
                # Skip headers that are just section titles
                if header_text and not any(
                    skip in header_text.lower()
                    for skip in ["release notes", "issues", "table of contents"]
                ):
                    current_feature = header_text
                    logger.debug("Found Device Security feature: %s", current_feature)
                continue

            if element.name == "table":
                if element.find_parent("table"):
                    continue

                issues = self._parse_issues_table_with_feature(element, current_feature)

                if issues:
                    # Group by a generic "version" key (we'll use year)
                    if "All" not in results:
                        results["All"] = []
                    results["All"].extend(issues)

        return results

    async def crawl(
        self,
        major_versions: list[str] | None = None,
        skip_versions: set[str] | None = None,
    ) -> CrawlResult:
        """Crawl Device Security release notes.

        Args:
            major_versions: Ignored (years are auto-discovered).
            skip_versions: Set of year strings to skip (e.g., {"2025"}).

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        skip_versions = skip_versions or set()
        failed_fetches: list[FailedFetch] = []

        logger.info("Discovering available Device Security years...")
        years = await self.discover_years()
        logger.info(f"Found years: {', '.join(years)}")

        years_to_fetch = [y for y in years if y not in skip_versions]
        self._set_task_total(
            len(years_to_fetch),
            f"{self.product_name}: fetching {len(years_to_fetch)} years"
            if years_to_fetch
            else f"{self.product_name}: nothing new to fetch",
        )

        all_known: dict[str, list[Issue]] = {}
        all_addressed: dict[str, list[Issue]] = {}

        for year in years:
            if year in skip_versions:
                logger.info(f"  Skipping year {year}")
                continue

            logger.info(f"Crawling Device Security {year}...")

            # Known and addressed issues URLs for this year
            known_url = f"/iot/release-notes/known-issues/known-issues-in-{year}"
            addressed_url = f"/iot/release-notes/addressed-issues/addressed-issues-in-{year}"

            fetch_tasks = [
                self._fetch_page_with_semaphore(known_url),
                self._fetch_page_with_semaphore(addressed_url),
            ]
            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            # Parse known issues
            if not isinstance(results[0], Exception):
                issues_by_feature = self._parse_device_security_issues_page(results[0], "known")
                for _feature, issues in issues_by_feature.items():
                    key = f"{year}"
                    if key not in all_known:
                        all_known[key] = []
                    all_known[key].extend(issues)
                total = sum(len(i) for i in issues_by_feature.values())
                logger.info(f"  {year}: {total} known issues")
            else:
                logger.error(f"Error fetching {year} known issues: {results[0]}")
                failed_fetches.append(
                    FailedFetch(
                        url=known_url,
                        error=str(results[0]),
                        product=self.product_id,
                        version=year,
                        issue_type="known",
                    )
                )

            # Parse addressed issues
            if not isinstance(results[1], Exception):
                issues_by_feature = self._parse_device_security_issues_page(results[1], "addressed")
                for _feature, issues in issues_by_feature.items():
                    key = f"{year}"
                    if key not in all_addressed:
                        all_addressed[key] = []
                    all_addressed[key].extend(issues)
                total = sum(len(i) for i in issues_by_feature.values())
                logger.info(f"  {year}: {total} addressed issues")
            else:
                logger.error(f"Error fetching {year} addressed issues: {results[1]}")
                failed_fetches.append(
                    FailedFetch(
                        url=addressed_url,
                        error=str(results[1]),
                        product=self.product_id,
                        version=year,
                        issue_type="addressed",
                    )
                )

            self._advance_task(f"{self.product_name}: {year} done")

        # Retry failed fetches
        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(failed_fetches)
            failed_fetches = still_failed

        # Combine into ProductVersion objects
        all_versions = set(all_known.keys()) | set(all_addressed.keys())
        product_versions = []

        for ver in all_versions:
            known = self._deduplicate_issues(all_known.get(ver, []))
            addressed = self._deduplicate_issues(all_addressed.get(ver, []))

            if known or addressed:
                product_versions.append(
                    ProductVersion(
                        version=ver,
                        known_issues=known,
                        addressed_issues=addressed,
                    )
                )

        # Sort by year (newest first)
        product_versions.sort(key=lambda v: v.version, reverse=True)

        return CrawlResult(
            product=Product(
                id=self.product_id,
                name=self.product_name,
                versions=product_versions,
            ),
            failed_fetches=failed_fetches,
        )

"""Autonomous DEM (ADEM) crawler implementation."""

import asyncio
import logging
import re
from typing import Optional

from bugdb.models import Issue, Product, ProductVersion

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch

logger = logging.getLogger(__name__)


class ADEMCrawler(BaseCrawler):
    """Crawler for Autonomous DEM release notes.

    ADEM issues are organized by agent version with release dates.
    """

    product_id = "adem"
    product_name = "Autonomous DEM"

    def _parse_adem_date(self, text: str) -> Optional[str]:
        """Parse a date string from ADEM release notes.

        Handles formats like:
        - "March 2024" -> "2024-03-01"
        - "March 15, 2024" -> "2024-03-15"
        - "2024-03-15" -> "2024-03-15"

        Args:
            text: Text that may contain a date.

        Returns:
            Date in YYYY-MM-DD format, or None if not a date.
        """
        text = text.strip()

        months = {
            "january": "01", "february": "02", "march": "03", "april": "04",
            "may": "05", "june": "06", "july": "07", "august": "08",
            "september": "09", "october": "10", "november": "11", "december": "12",
        }

        # Try "Month Day, Year" format
        match = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", text)
        if match:
            month_name = match.group(1).lower()
            day = match.group(2).zfill(2)
            year = match.group(3)
            if month_name in months:
                return f"{year}-{months[month_name]}-{day}"

        # Try "Month Year" format
        match = re.match(r"^([A-Za-z]+)\s+(\d{4})$", text)
        if match:
            month_name = match.group(1).lower()
            year = match.group(2)
            if month_name in months:
                return f"{year}-{months[month_name]}-01"

        # Try ISO format
        match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
        if match:
            return text

        return None

    def _parse_adem_issues_page(
        self, soup, issue_type: str
    ) -> dict[str, list[Issue]]:
        """Parse an ADEM issues page organized by agent version.

        Args:
            soup: BeautifulSoup parsed page.
            issue_type: Either "known" or "addressed".

        Returns:
            Dict mapping version strings to lists of Issue objects.
        """
        results: dict[str, list[Issue]] = {}
        current_version = "Unknown"
        current_release_date: Optional[str] = None

        for element in soup.find_all(["h2", "h3", "h4", "p", "table"]):
            if element.name in ["h2", "h3", "h4"]:
                header_text = element.get_text(strip=True)

                # Check for agent version header
                version_match = re.search(
                    r"(?:Autonomous\s+DEM\s+)?Agent\s+(\d+\.\d+)",
                    header_text,
                    re.IGNORECASE,
                )
                if version_match:
                    current_version = version_match.group(1)
                    current_release_date = None
                    logger.debug("Found ADEM version header: %s", current_version)
                    continue

                # Check for date header
                date_match = self._parse_adem_date(header_text)
                if date_match:
                    current_release_date = date_match
                    logger.debug("Found ADEM release date: %s", current_release_date)
                    continue

            elif element.name == "p":
                text = element.get_text(strip=True)
                date_match = self._parse_adem_date(text)
                if date_match:
                    current_release_date = date_match
                    continue

            elif element.name == "table":
                if element.find_parent("table"):
                    continue

                issues = self._parse_issues_table(element)

                # Add release date to addressed issues
                if issue_type == "addressed" and current_release_date:
                    for issue in issues:
                        issue.release_date = current_release_date

                if issues:
                    if current_version not in results:
                        results[current_version] = []
                    results[current_version].extend(issues)

        return results

    async def crawl(
        self,
        major_versions: Optional[list[str]] = None,
        skip_versions: Optional[set[str]] = None,
    ) -> CrawlResult:
        """Crawl Autonomous DEM release notes.

        Args:
            major_versions: Ignored (versions are auto-discovered from page).
            skip_versions: Ignored.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        self._log("Crawling Autonomous DEM...")
        failed_fetches: list[FailedFetch] = []

        known_issues_url = (
            "/autonomous-dem/release-notes/ai-powered-adem-release-notes"
            "/release-updates-release-notes-doc/known-issues-adem"
        )
        addressed_issues_url = (
            "/autonomous-dem/release-notes/ai-powered-adem-release-notes"
            "/release-updates-release-notes-doc/addressed-issues-adem"
        )

        fetch_tasks = [
            self._fetch_page_with_semaphore(known_issues_url),
            self._fetch_page_with_semaphore(addressed_issues_url),
        ]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        known_by_version: dict[str, list[Issue]] = {}
        addressed_by_version: dict[str, list[Issue]] = {}

        if not isinstance(results[0], Exception):
            known_by_version = self._parse_adem_issues_page(results[0], "known")
            total_known = sum(len(issues) for issues in known_by_version.values())
            self._log(f"  Found {total_known} known issues across {len(known_by_version)} versions")
        else:
            self._log(f"  Error fetching known issues: {results[0]}")
            failed_fetches.append(FailedFetch(
                url=known_issues_url,
                error=str(results[0]),
                product=self.product_id,
                issue_type="known",
            ))

        if not isinstance(results[1], Exception):
            addressed_by_version = self._parse_adem_issues_page(results[1], "addressed")
            total_addressed = sum(len(issues) for issues in addressed_by_version.values())
            self._log(f"  Found {total_addressed} addressed issues across {len(addressed_by_version)} versions")
        else:
            self._log(f"  Error fetching addressed issues: {results[1]}")
            failed_fetches.append(FailedFetch(
                url=addressed_issues_url,
                error=str(results[1]),
                product=self.product_id,
                issue_type="addressed",
            ))

        # Retry failed fetches
        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(
                failed_fetches
            )
            failed_fetches = still_failed

        # Combine into ProductVersion objects
        all_versions_set = set(known_by_version.keys()) | set(addressed_by_version.keys())
        all_product_versions = []

        for ver in all_versions_set:
            known = self._deduplicate_issues(known_by_version.get(ver, []))
            addressed = self._deduplicate_issues(addressed_by_version.get(ver, []))

            if known or addressed:
                all_product_versions.append(ProductVersion(
                    version=ver,
                    known_issues=known,
                    addressed_issues=addressed,
                ))

        # Sort versions
        all_product_versions.sort(
            key=lambda v: self._version_sort_key(v.version),
            reverse=True,
        )

        return CrawlResult(
            product=Product(
                id=self.product_id,
                name=self.product_name,
                versions=all_product_versions,
            ),
            failed_fetches=failed_fetches,
        )

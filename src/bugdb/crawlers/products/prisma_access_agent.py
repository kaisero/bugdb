"""Prisma Access Agent crawler implementation."""

import asyncio
import logging
import re
from typing import Optional

from bugdb.models import Product

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch, VersionInfo

logger = logging.getLogger(__name__)


class PrismaAccessAgentCrawler(BaseCrawler):
    """Crawler for Prisma Access Agent release notes."""

    product_id = "prisma-access-agent"
    product_name = "Prisma Access Agent"

    async def discover_versions(self) -> list[str]:
        """Discover available Prisma Access Agent major versions.

        Returns:
            List of major version strings (e.g., ["26-1", "25-2"]).
        """
        logger.debug("Discovering Prisma Access Agent versions by probing URLs")

        candidate_versions = [
            "26-1", "25-2", "25-1", "24-2", "24-1",
            "6-3", "6-2", "6-1", "6-0",
            "5-3", "5-2", "5-1", "5-0",
        ]

        valid_versions = []

        async def check_version(version: str) -> Optional[str]:
            """Check if a version URL exists."""
            url = f"/prisma-access-agent/release-notes"
            try:
                soup = await self._fetch_page_with_semaphore(url)
                title = soup.find("title")
                title_text = title.get_text().lower() if title else ""
                if "404" in title_text or "not found" in title_text or "error" in title_text:
                    return None
                h1 = soup.find("h1")
                if h1:
                    logger.debug("Found valid Prisma Access Agent version: %s", version)
                    return version
                return None
            except Exception:
                return None

        tasks = [check_version(v) for v in candidate_versions]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, str):
                valid_versions.append(result)

        sorted_versions = sorted(
            valid_versions, key=lambda v: [int(x) for x in v.split("-")], reverse=True
        )
        logger.debug("Discovered %d Prisma Access Agent versions: %s",
                     len(sorted_versions), sorted_versions)
        return sorted_versions

    async def discover_version_pages(self, major_version: str) -> list[VersionInfo]:
        """Discover all version pages for a major version.

        Args:
            major_version: The major version (e.g., "25-2").

        Returns:
            List of VersionInfo objects with URLs for each minor version.
        """
        version_infos = []
        base_url = f"/prisma-access-agent/release-notes"

        try:
            soup = await self._fetch_page_with_semaphore(base_url)

            for link in soup.find_all("a", href=True):
                href = link["href"]
                href_lower = href.lower()

                if "known" in href_lower or "addressed" in href_lower:
                    version = self._extract_version_from_url(href)
                    if not version:
                        continue

                    vi = next(
                        (v for v in version_infos if v.version == version), None
                    )
                    if not vi:
                        vi = VersionInfo(version=version, known_issues_urls=[], addressed_issues_urls=[])
                        version_infos.append(vi)

                    if not href.startswith("/"):
                        href = f"/{href}"
                    if href.startswith("/content/techdocs/en_US"):
                        href = href[len("/content/techdocs/en_US"):]
                    if href.endswith(".html"):
                        href = href[:-5]

                    # Classify by last path segment to avoid false matches
                    last_segment = href.rstrip("/").rsplit("/", 1)[-1].lower()
                    if "addressed" in last_segment:
                        if href not in vi.addressed_issues_urls:
                            vi.addressed_issues_urls.append(href)
                    elif "known" in last_segment:
                        if href not in vi.known_issues_urls:
                            vi.known_issues_urls.append(href)

        except Exception as e:
            logger.error("Error discovering version pages for %s: %s", major_version, e)
            self._log(f"  Error discovering version pages: {e}")

        version_infos.sort(
            key=lambda v: self._version_sort_key(v.version),
            reverse=True,
        )

        return version_infos

    async def crawl(
        self,
        major_versions: Optional[list[str]] = None,
        skip_versions: Optional[set[str]] = None,
    ) -> CrawlResult:
        """Crawl Prisma Access Agent release notes.

        Args:
            major_versions: List of major versions to crawl.
            skip_versions: Set of version strings to skip.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        skip_versions = skip_versions or set()
        all_failed_fetches: list[FailedFetch] = []

        if major_versions is None:
            self._log("Discovering available Prisma Access Agent versions...")
            major_versions = await self.discover_versions()
            self._log(f"Found versions: {', '.join(major_versions)}")

        all_product_versions = []

        for major_version in major_versions:
            version_str = major_version.replace("-", ".")
            self._log(f"Crawling Prisma Access Agent {version_str}...")

            version_infos = await self.discover_version_pages(major_version)
            version_infos = [
                vi for vi in version_infos if vi.version not in skip_versions
            ]

            if not version_infos:
                self._log("  No versions to crawl (all skipped or none found)")
                continue

            product_versions, failed_fetches = await self._crawl_versions_parallel(
                version_infos, self.product_id
            )

            all_product_versions.extend(product_versions)
            all_failed_fetches.extend(failed_fetches)

        if all_failed_fetches:
            recovered, still_failed = await self._retry_failed_fetches_sequentially(
                all_failed_fetches
            )
            all_failed_fetches = still_failed

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
            failed_fetches=all_failed_fetches,
        )

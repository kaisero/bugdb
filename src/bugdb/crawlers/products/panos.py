"""PAN-OS crawler implementation."""

import asyncio
import logging
import re
from typing import Optional

from bugdb.fetch_manifest import FetchManifest
from bugdb.models import Product
from bugdb.sitemap import SitemapIndex

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch, VersionInfo
from ..sitemap_discovery import (
    discover_major_versions,
    discover_version_pages,
)

logger = logging.getLogger(__name__)


class PANOSCrawler(BaseCrawler):
    """Crawler for PAN-OS release notes."""

    product_id = "panos"
    product_name = "PAN-OS"

    def __init__(
        self,
        *args,
        sitemap: Optional[SitemapIndex] = None,
        manifest: Optional[FetchManifest] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._sitemap = sitemap
        self._manifest = manifest

    def discover_versions_from_sitemap(self) -> list[str]:
        """Return major versions present in the sitemap, newest first."""
        return discover_major_versions(self._sitemap, self.product_id)

    def discover_version_pages_from_sitemap(
        self, major_version: str
    ) -> list[VersionInfo]:
        """Build VersionInfo entries from sitemap URLs for one major version.

        Skips URLs whose sitemap lastmod matches the manifest entry.
        """
        return discover_version_pages(
            self._sitemap,
            self.product_id,
            major_version=major_version,
            manifest=self._manifest,
        )

    async def discover_versions(self) -> list[str]:
        """Discover available PAN-OS major versions.

        The version dropdown is JavaScript-rendered, so we probe for known
        version patterns by checking if the URLs exist.

        Returns:
            List of major version strings (e.g., ["12-1", "11-2", "11-1"]).
        """
        logger.debug("Discovering PAN-OS versions by probing URLs")

        # Known version patterns to check (newest first)
        candidate_versions = [
            "12-1", "12-0",
            "11-3", "11-2", "11-1", "11-0",
            "10-2", "10-1", "10-0",
            "9-1",
        ]

        valid_versions = []

        async def check_version(version: str) -> Optional[str]:
            """Check if a version URL exists."""
            url = f"/pan-os/{version}/pan-os-release-notes"
            try:
                soup = await self._fetch_page_with_semaphore(url)
                title = soup.find("title")
                title_text = title.get_text().lower() if title else ""
                if "404" in title_text or "not found" in title_text or "error" in title_text:
                    return None
                h1 = soup.find("h1")
                if h1:
                    logger.debug("Found valid PAN-OS version: %s", version)
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
        logger.debug("Discovered %d PAN-OS versions: %s",
                     len(sorted_versions), sorted_versions)
        return sorted_versions

    async def discover_version_pages(self, major_version: str) -> list[VersionInfo]:
        """Discover all version pages for a major version.

        Args:
            major_version: The major version (e.g., "11-2").

        Returns:
            List of VersionInfo objects with URLs for each minor version.
        """
        version_infos = []
        base_url = f"/pan-os/{major_version}/pan-os-release-notes"

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

                    if "known" in href_lower:
                        if href not in vi.known_issues_urls:
                            vi.known_issues_urls.append(href)
                    else:
                        if href not in vi.addressed_issues_urls:
                            vi.addressed_issues_urls.append(href)

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
        """Crawl PAN-OS release notes.

        Args:
            major_versions: List of major versions to crawl (e.g., ["12-1", "11-2"]).
                           If None, discovers and crawls all available versions.
            skip_versions: Set of version strings to skip (for incremental fetching).

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        skip_versions = skip_versions or set()
        all_failed_fetches: list[FailedFetch] = []

        # Prefer sitemap-driven discovery when available; falls back to the
        # JS-rendered probe (current legacy behavior).
        use_sitemap = self._sitemap is not None

        if major_versions is None:
            if use_sitemap:
                self._log("Discovering available PAN-OS versions from sitemap...")
                major_versions = self.discover_versions_from_sitemap()
            else:
                self._log("Discovering available PAN-OS versions...")
                major_versions = await self.discover_versions()
            self._log(f"Found versions: {', '.join(major_versions)}")

        all_product_versions = []

        for major_version in major_versions:
            version_str = major_version.replace("-", ".")
            self._log(f"Crawling PAN-OS {version_str}...")

            if use_sitemap:
                version_infos = self.discover_version_pages_from_sitemap(major_version)
            else:
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

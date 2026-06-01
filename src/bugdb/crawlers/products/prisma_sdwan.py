"""Prisma SD-WAN crawler implementation."""

import asyncio
import logging

from bugdb.models import Product

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch, VersionInfo
from ..sitemap_discovery import (
    discover_major_versions,
    discover_version_pages,
)

logger = logging.getLogger(__name__)


class PrismaSDWANCrawler(BaseCrawler):
    """Crawler for Prisma SD-WAN (ION) release notes."""

    product_id = "prisma-sdwan"
    product_name = "Prisma SD-WAN"

    def discover_versions_from_sitemap(self) -> list[str]:
        return discover_major_versions(self._sitemap, self.product_id)

    def discover_version_pages_from_sitemap(
        self, major_version: str
    ) -> list[VersionInfo]:
        return discover_version_pages(
            self._sitemap,
            self.product_id,
            major_version=major_version,
            manifest=self._manifest,
        )

    async def discover_versions(self) -> list[str]:
        """Discover available Prisma SD-WAN major versions.

        Returns:
            List of major version strings (e.g., ["6-5", "6-4"]).
        """
        logger.debug("Discovering Prisma SD-WAN versions by probing URLs")

        candidate_versions = [
            "6-6",
            "6-5",
            "6-4",
            "6-3",
            "6-2",
            "6-1",
            "6-0",
            "5-6",
            "5-5",
            "5-4",
            "5-3",
            "5-2",
            "5-1",
        ]

        valid_versions = []

        async def check_version(version: str) -> str | None:
            """Check if a version URL exists."""
            url = f"/prisma-sd-wan/release-notes/{version}"
            try:
                soup = await self._fetch_page_with_semaphore(url)
                title = soup.find("title")
                title_text = title.get_text().lower() if title else ""
                if "404" in title_text or "not found" in title_text or "error" in title_text:
                    return None
                h1 = soup.find("h1")
                if h1:
                    logger.debug("Found valid Prisma SD-WAN version: %s", version)
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
        logger.debug(
            "Discovered %d Prisma SD-WAN versions: %s", len(sorted_versions), sorted_versions
        )
        return sorted_versions

    async def discover_version_pages(self, major_version: str) -> list[VersionInfo]:
        """Discover all version pages for a major version.

        Prisma SD-WAN has a different structure - issues pages are organized
        by major version with all minor versions in sections on the same page.

        Args:
            major_version: The major version (e.g., "6-4").

        Returns:
            List of VersionInfo objects.
        """
        version_infos = []
        base_url = f"/prisma-sd-wan/release-notes/{major_version}"

        try:
            soup = await self._fetch_page_with_semaphore(base_url)

            for link in soup.find_all("a", href=True):
                href = link["href"]
                href_lower = href.lower()

                if "known" in href_lower or "addressed" in href_lower or "fixed" in href_lower:
                    version = self._extract_version_from_url(href)
                    if not version:
                        continue

                    vi = next((v for v in version_infos if v.version == version), None)
                    if not vi:
                        vi = VersionInfo(
                            version=version, known_issues_urls=[], addressed_issues_urls=[]
                        )
                        version_infos.append(vi)

                    if not href.startswith("/"):
                        href = f"/{href}"
                    if href.startswith("/content/techdocs/en_US"):
                        href = href[len("/content/techdocs/en_US") :]
                    if href.endswith(".html"):
                        href = href[:-5]

                    # Classify by last path segment to avoid false matches.
                    last_segment = href.rstrip("/").rsplit("/", 1)[-1].lower()
                    # Skip "known-and-addressed-issues" hub pages — they
                    # are link-only indexes with no issue tables.
                    if "known-and-addressed" in last_segment:
                        continue
                    if (
                        "addressed" in last_segment or "fixed" in last_segment
                    ) and href not in vi.addressed_issues_urls:
                        vi.addressed_issues_urls.append(href)
                    elif "known" in last_segment and href not in vi.known_issues_urls:
                        vi.known_issues_urls.append(href)

        except Exception as e:
            logger.error("Error discovering version pages for %s: %s", major_version, e)

        version_infos.sort(
            key=lambda v: self._version_sort_key(v.version),
            reverse=True,
        )

        return version_infos

    async def crawl(
        self,
        major_versions: list[str] | None = None,
        skip_versions: set[str] | None = None,
    ) -> CrawlResult:
        """Crawl Prisma SD-WAN release notes.

        Args:
            major_versions: List of major versions to crawl.
            skip_versions: Set of version strings to skip.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        skip_versions = skip_versions or set()
        all_failed_fetches: list[FailedFetch] = []
        use_sitemap = self._sitemap is not None

        # Cache-aware discovery — see BaseCrawler._resolve_version_infos.
        if major_versions is None:
            if use_sitemap:
                logger.info("Discovering available Prisma SD-WAN versions from sitemap...")
            else:
                logger.info("Discovering available Prisma SD-WAN versions...")

        if use_sitemap:

            async def _discover_majors() -> list[str]:
                return self.discover_versions_from_sitemap()

            async def _discover_pages(major: str) -> list:
                return self.discover_version_pages_from_sitemap(major)

            vi_by_major = await self._resolve_version_infos(
                discover_majors_fn=_discover_majors,
                discover_pages_fn=_discover_pages,
                explicit_majors=major_versions,
                skip_versions=skip_versions,
            )
        else:
            vi_by_major = await self._resolve_version_infos(
                discover_majors_fn=self.discover_versions,
                discover_pages_fn=self.discover_version_pages,
                explicit_majors=major_versions,
                skip_versions=skip_versions,
            )
        if major_versions is None:
            logger.info("Found versions: %s", ", ".join(vi_by_major.keys()))

        total_versions = sum(len(v) for v in vi_by_major.values())
        self._set_task_total(
            total_versions,
            f"{self.product_name}: fetching {total_versions} versions"
            if total_versions
            else f"{self.product_name}: nothing new to fetch",
        )

        all_product_versions = []

        for major_version, version_infos in vi_by_major.items():
            version_str = major_version.replace("-", ".")
            logger.info("Crawling Prisma SD-WAN %s...", version_str)

            if not version_infos:
                logger.info("No versions to crawl (all skipped or none found)")
                continue

            product_versions, failed_fetches = await self._crawl_versions_parallel(
                version_infos, self.product_id
            )

            all_product_versions.extend(product_versions)
            all_failed_fetches.extend(failed_fetches)

        if all_failed_fetches:
            _recovered, still_failed = await self._retry_failed_fetches_sequentially(
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

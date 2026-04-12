"""GlobalProtect crawler implementation."""

import asyncio
import logging

from bugdb.models import Product

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch, VersionInfo

logger = logging.getLogger(__name__)


class GlobalProtectCrawler(BaseCrawler):
    """Crawler for GlobalProtect App release notes."""

    product_id = "globalprotect"
    product_name = "GlobalProtect"

    async def discover_versions(self) -> list[str]:
        """Discover available GlobalProtect major versions.

        The version dropdown is JavaScript-rendered, so we probe for known
        version patterns by checking if the URLs exist.

        Returns:
            List of major version strings (e.g., ["6-3", "6-2", "6-1"]).
        """
        logger.debug("Discovering GlobalProtect versions by probing URLs")

        # Known version patterns to check (newest first)
        candidate_versions = [
            "6-3",
            "6-2",
            "6-1",
            "6-0",
            "5-3",
            "5-2",
            "5-1",
            "5-0",
            "4-1",
        ]

        valid_versions = []

        async def check_version(version: str) -> str | None:
            """Check if a version URL exists."""
            url = f"/globalprotect/{version}/globalprotect-app-release-notes"
            try:
                soup = await self._fetch_page_with_semaphore(url)
                # Check if page has actual content (not a 404 or error page)
                title = soup.find("title")
                title_text = title.get_text().lower() if title else ""
                if "404" in title_text or "not found" in title_text or "error" in title_text:
                    return None
                # Check for a valid h1 header
                h1 = soup.find("h1")
                if h1:
                    logger.debug("Found valid GlobalProtect version: %s", version)
                    return version
                return None
            except Exception:
                return None

        # Check versions concurrently
        tasks = [check_version(v) for v in candidate_versions]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, str):
                valid_versions.append(result)

        # Sort versions in descending order (newest first)
        sorted_versions = sorted(
            valid_versions, key=lambda v: [int(x) for x in v.split("-")], reverse=True
        )
        logger.debug(
            "Discovered %d GlobalProtect versions: %s", len(sorted_versions), sorted_versions
        )
        return sorted_versions

    async def discover_version_pages(self, major_version: str) -> list[VersionInfo]:
        """Discover all version pages for a major version.

        Fetches the main release notes index and extracts links to specific
        version pages.

        Args:
            major_version: The major version (e.g., "6-2").

        Returns:
            List of VersionInfo objects with URLs for each minor version.
        """
        version_infos = []
        base_url = f"/globalprotect/{major_version}/globalprotect-app-release-notes"

        try:
            soup = await self._fetch_page_with_semaphore(base_url)

            # Find all links to known and addressed issues pages
            for link in soup.find_all("a", href=True):
                href = link["href"]
                href_lower = href.lower()

                if "known" in href_lower or "addressed" in href_lower:
                    # Extract version from URL
                    version = self._extract_version_from_url(href)
                    if not version:
                        continue

                    # Find or create VersionInfo for this version
                    vi = next((v for v in version_infos if v.version == version), None)
                    if not vi:
                        vi = VersionInfo(
                            version=version, known_issues_urls=[], addressed_issues_urls=[]
                        )
                        version_infos.append(vi)

                    # Normalize URL
                    if not href.startswith("/"):
                        href = f"/{href}"
                    if href.startswith("/content/techdocs/en_US"):
                        href = href[len("/content/techdocs/en_US") :]
                    if href.endswith(".html"):
                        href = href[:-5]

                    # Classify by last path segment to avoid false matches
                    # (e.g., "known-issues-related-to-gp-app/addressed-issues").
                    last_segment = href.rstrip("/").rsplit("/", 1)[-1].lower()
                    # Skip "known-and-addressed-issues" hub pages — they
                    # are link-only indexes with no issue tables.
                    if "known-and-addressed" in last_segment:
                        continue
                    if "addressed" in last_segment and href not in vi.addressed_issues_urls:
                        vi.addressed_issues_urls.append(href)
                    elif "known" in last_segment and href not in vi.known_issues_urls:
                        vi.known_issues_urls.append(href)

        except Exception as e:
            logger.error("Error discovering version pages for %s: %s", major_version, e)

        # Sort by version (newest first)
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
        """Crawl GlobalProtect release notes.

        Args:
            major_versions: List of major versions to crawl (e.g., ["6-2", "6-1"]).
                           If None, discovers and crawls all available versions.
            skip_versions: Set of version strings to skip (for incremental fetching).

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        skip_versions = skip_versions or set()
        all_failed_fetches: list[FailedFetch] = []

        # Cache-aware discovery: warm runs skip the probe + per-major
        # index fetches entirely. See BaseCrawler._resolve_version_infos.
        if major_versions is None:
            logger.info("Discovering available GlobalProtect versions...")
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
            logger.info("Crawling GlobalProtect %s...", version_str)

            if not version_infos:
                logger.info("No versions to crawl (all skipped or none found)")
                continue

            # Crawl all versions in parallel
            product_versions, failed_fetches = await self._crawl_versions_parallel(
                version_infos, self.product_id
            )

            all_product_versions.extend(product_versions)
            all_failed_fetches.extend(failed_fetches)

        # Retry failed fetches
        if all_failed_fetches:
            _recovered, still_failed = await self._retry_failed_fetches_sequentially(
                all_failed_fetches
            )
            all_failed_fetches = still_failed

        # Sort all versions (newest first)
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

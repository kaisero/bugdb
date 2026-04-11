"""PAN-OS crawler implementation."""

import asyncio
import logging
import re
from typing import Optional

from bugdb.models import Product

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch, VersionInfo

logger = logging.getLogger(__name__)


class PANOSCrawler(BaseCrawler):
    """Crawler for PAN-OS release notes."""

    product_id = "panos"
    product_name = "PAN-OS"

    # Palo Alto Networks moved PAN-OS release notes from the legacy
    # `/pan-os/<v>/pan-os-release-notes` path onto the shared NGFW release
    # notes book at `/ngfw/release-notes/<v>` starting with PAN-OS 12.1.
    # We probe the new pattern first and fall back to the legacy one so a
    # single crawler handles both newer and older versions.
    _NGFW_BASE = "/ngfw/release-notes/{v}"
    _LEGACY_BASE = "/pan-os/{v}/pan-os-release-notes"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Per-major-version landing URL that actually responded with a real
        # page. Populated by discover_versions() and reused by
        # discover_version_pages() so the probe only happens once.
        self._base_url_for_version: dict[str, str] = {}

    async def _probe_landing_url(self, url: str) -> bool:
        """Return True if the given URL renders a real PAN-OS page (not 404)."""
        try:
            soup = await self._fetch_page_with_semaphore(url)
        except Exception:
            return False
        title = soup.find("title")
        title_text = title.get_text().lower() if title else ""
        if "404" in title_text or "not found" in title_text or "error" in title_text:
            return False
        return soup.find("h1") is not None

    async def _resolve_landing_url(self, major_version: str) -> Optional[str]:
        """Resolve the landing URL for a major version, probing if needed.

        Tries the NGFW path first (used by 12.1+) and falls back to the
        legacy `/pan-os/<v>/pan-os-release-notes` path. Caches the result
        in ``self._base_url_for_version``.
        """
        cached = self._base_url_for_version.get(major_version)
        if cached:
            return cached
        for template in (self._NGFW_BASE, self._LEGACY_BASE):
            candidate = template.format(v=major_version)
            if await self._probe_landing_url(candidate):
                self._base_url_for_version[major_version] = candidate
                return candidate
        return None

    async def discover_versions(self) -> list[str]:
        """Discover available PAN-OS major versions.

        The version dropdown is JavaScript-rendered, so we probe for known
        version patterns by checking if the URLs exist. Both the legacy
        `/pan-os/<v>/pan-os-release-notes` and the newer
        `/ngfw/release-notes/<v>` paths are tried per candidate.

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

        tasks = [self._resolve_landing_url(v) for v in candidate_versions]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_versions: list[str] = []
        for version, result in zip(candidate_versions, results):
            if isinstance(result, str) and result:
                logger.debug("Found valid PAN-OS version: %s -> %s", version, result)
                valid_versions.append(version)

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
        base_url = await self._resolve_landing_url(major_version)
        if not base_url:
            logger.warning(
                "No landing URL found for PAN-OS %s (tried NGFW and legacy paths)",
                major_version,
            )
            self._log(
                f"  No landing URL found for PAN-OS {major_version}"
            )
            return version_infos

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
                    # (e.g., "known-and-addressed-issues/addressed-issues")
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

        if major_versions is None:
            self._log("Discovering available PAN-OS versions...")
            major_versions = await self.discover_versions()
            self._log(f"Found versions: {', '.join(major_versions)}")

        all_product_versions = []

        for major_version in major_versions:
            version_str = major_version.replace("-", ".")
            self._log(f"Crawling PAN-OS {version_str}...")

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

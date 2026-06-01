"""Prisma Access Agent crawler implementation."""

import asyncio
import logging
import re
from typing import Optional

from bugdb.models import Issue, Product, ProductVersion

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch, VersionInfo
from ..sitemap_discovery import (
    discover_major_versions,
    discover_version_pages,
    extract_dotted_version,
    filter_unchanged,
    group_into_version_infos,
)

logger = logging.getLogger(__name__)


class PrismaAccessAgentCrawler(BaseCrawler):
    """Crawler for Prisma Access Agent release notes."""

    product_id = "prisma-access-agent"
    product_name = "Prisma Access Agent"

    def discover_versions_from_sitemap(self) -> list[str]:
        """Derive 'major-minor' from each URL's extracted version.

        Prisma Access Agent encodes the version inside the slug
        (e.g. 'prisma-access-agent-26-2-1-known-issues') rather than as
        a `/X-Y/` path segment, so the generic discover_major_versions
        helper (which reads SitemapEntry.major_version) returns the
        empty list. We re-derive majors from the extract_dotted_version
        output instead.
        """
        if self._sitemap is None:
            return []
        majors: set[str] = set()
        for entry in self._sitemap.for_product(self.product_id):
            ver = extract_dotted_version(entry.url)
            if not ver:
                continue
            parts = ver.split(".")
            if len(parts) >= 2:
                majors.add(f"{parts[0]}-{parts[1]}")
        return sorted(
            majors, key=lambda v: [int(x) for x in v.split("-")], reverse=True
        )

    def discover_version_pages_from_sitemap(
        self, major_version: str
    ) -> list[VersionInfo]:
        """Group sitemap URLs by extracted dotted version, filtered to one major."""
        if self._sitemap is None:
            return []
        major_prefix = major_version.replace("-", ".") + "."
        entries = []
        for entry in self._sitemap.for_product(self.product_id):
            ver = extract_dotted_version(entry.url)
            if ver and (ver + ".").startswith(major_prefix):
                entries.append(entry)
        entries = filter_unchanged(entries, self._manifest)
        return group_into_version_infos(entries)

    def _find_addressed_index_url(self) -> Optional[str]:
        """Find the single 'all addressed issues' index URL in the sitemap.

        The new docs layout consolidates addressed issues onto one page
        instead of per-version pages, with `<h2>` headings separating
        each version's table.
        """
        if self._sitemap is None:
            return None
        for entry in self._sitemap.for_product(self.product_id):
            lower = entry.url.lower()
            if "addressed-issues" not in lower:
                continue
            # The index page has no version in its slug; per-version
            # variants would. Filter to URLs where extract_dotted_version
            # returns None (i.e., the bare index).
            if extract_dotted_version(entry.url) is None:
                return entry.url.replace(
                    "https://docs.paloaltonetworks.com", ""
                )
        return None

    def _parse_addressed_index_by_version(
        self, soup
    ) -> dict[str, list[Issue]]:
        """Walk h2/table pairs in the addressed-issues index page.

        Each `<h2>` carries a label like "Issues Addressed in Prisma Access
        Agent 26.2"; the following `<table>` is the bug table for that
        version. Returns dict[version_string, list[Issue]].
        """
        result: dict[str, list[Issue]] = {}
        version_re = re.compile(r"Prisma Access Agent\s+(\d+\.\d+(?:\.\d+)?)")
        current_version: Optional[str] = None
        for element in soup.find_all(["h2", "h3", "table"]):
            if element.name in ("h2", "h3"):
                m = version_re.search(element.get_text())
                current_version = m.group(1) if m else None
                continue
            if element.name != "table" or current_version is None:
                continue
            if element.find_parent("table"):
                continue
            issues = self._parse_issues_table(element)
            if issues:
                result.setdefault(current_version, []).extend(issues)
        return result

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
            url = f"/access/docs/prisma-access-agent/{version}/prisma-access-agent-release-notes"
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
        base_url = f"/access/docs/prisma-access-agent/{major_version}/prisma-access-agent-release-notes"

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
        """Crawl Prisma Access Agent release notes.

        Args:
            major_versions: List of major versions to crawl.
            skip_versions: Set of version strings to skip.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        skip_versions = skip_versions or set()
        all_failed_fetches: list[FailedFetch] = []
        use_sitemap = self._sitemap is not None

        if major_versions is None:
            if use_sitemap:
                self._log(
                    "Discovering available Prisma Access Agent versions from sitemap..."
                )
                major_versions = self.discover_versions_from_sitemap()
            else:
                self._log("Discovering available Prisma Access Agent versions...")
                major_versions = await self.discover_versions()
            self._log(f"Found versions: {', '.join(major_versions)}")

        all_product_versions = []

        for major_version in major_versions:
            version_str = major_version.replace("-", ".")
            self._log(f"Crawling Prisma Access Agent {version_str}...")

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

        # In the new docs layout, addressed issues for ALL Prisma Access
        # Agent versions live on a single index page with H2-grouped tables.
        # Fetch it once and merge each section into the matching version.
        if use_sitemap:
            addressed_index_url = self._find_addressed_index_url()
            if addressed_index_url is not None:
                try:
                    soup = await self._fetch_page_with_semaphore(
                        addressed_index_url
                    )
                    by_version = self._parse_addressed_index_by_version(soup)
                    self._log(
                        f"  Addressed-issues index produced "
                        f"{sum(len(v) for v in by_version.values())} issues "
                        f"across {len(by_version)} versions"
                    )
                    # Merge into existing ProductVersion entries by version
                    # match. Versions seen ONLY on the index page get
                    # synthesised as new ProductVersion entries.
                    by_existing = {pv.version: pv for pv in all_product_versions}
                    for ver, issues in by_version.items():
                        pv = by_existing.get(ver)
                        if pv is None:
                            pv = ProductVersion(
                                version=ver,
                                known_issues=[],
                                addressed_issues=[],
                            )
                            all_product_versions.append(pv)
                            by_existing[ver] = pv
                        pv.addressed_issues = self._deduplicate_issues(
                            list(pv.addressed_issues) + issues
                        )
                except Exception as e:
                    self._log(
                        f"  Error fetching addressed-issues index: {e}"
                    )
                    all_failed_fetches.append(
                        FailedFetch(
                            url=addressed_index_url,
                            error=str(e),
                            product=self.product_id,
                            issue_type="addressed",
                        )
                    )

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

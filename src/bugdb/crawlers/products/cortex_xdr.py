"""Cortex XDR Agent crawler implementation."""

import asyncio
import logging
import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup

from bugdb.models import Issue, Product, ProductVersion

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch
from ..utils import CORTEX_BASE_URL, extract_workaround

logger = logging.getLogger(__name__)


def _extract_version_from_metadata(topic: dict) -> Optional[str]:
    """Pull the "Version" metadata value from a FluidTopics topic dict."""
    for entry in topic.get("metadata", []):
        if entry.get("key") == "Version" and entry.get("values"):
            return entry["values"][0]
    return None


def _extract_publication_date(topic: dict) -> Optional[str]:
    """Pull the publication date from a FluidTopics topic dict."""
    for entry in topic.get("metadata", []):
        if entry.get("key") in (
            "publicationDate",
            "Last date published",
        ) and entry.get("values"):
            return entry["values"][0]
    return None


def _major_version(version: str) -> str:
    """Return the "major.minor" prefix of a version string (e.g. 9.1.1 -> 9.1)."""
    parts = version.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else version


class CortexXDRCrawler(BaseCrawler):
    """Crawler for Cortex XDR Agent release notes.

    Cortex XDR has a different documentation portal (docs-cortex.paloaltonetworks.com)
    with release notes organized by agent version. When a `fluidtopics` client
    is injected, the crawler uses the public khub JSON API instead of the
    legacy shadow-DOM-scraping Playwright path.
    """

    product_id = "cortex-xdr"
    product_name = "Cortex XDR Agent"

    def __init__(self, *args, fluidtopics=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._fluidtopics = fluidtopics

    def _parse_cortex_release_date(self, date_text: str) -> Optional[str]:
        """Parse Cortex XDR release date text to YYYY-MM-DD format."""
        if not date_text:
            return None

        date_text = re.sub(r",\s*", ", ", date_text.strip())

        formats = [
            "%B %d, %Y",
            "%b %d, %Y",
            "%B %d %Y",
            "%Y-%m-%d",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_text, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        logger.debug("Could not parse Cortex release date: %s", date_text)
        return None

    def _extract_cortex_xdr_version(self, text: str) -> Optional[str]:
        """Extract version number from Cortex XDR release text."""
        match = re.search(r"(\d+\.\d+(?:\.\d+)?)", text)
        if match:
            return match.group(1)
        return None

    def _parse_cortex_xdr_releases_page(self, soup) -> list[tuple[str, str, Optional[str]]]:
        """Parse the Cortex XDR releases page to extract version links and dates."""
        releases: list[tuple[str, str, Optional[str]]] = []
        seen_versions: set[str] = set()

        tables = soup.find_all("table")

        for table in tables:
            headers = [th.get_text(strip=True).upper() for th in table.find_all("th")]

            if "FEATURE" in headers or "LIMITATION" in headers:
                continue

            date_col = None
            for i, h in enumerate(headers):
                if "DATE" in h:
                    date_col = i
                    break

            for row in table.find_all("tr")[1:]:
                cells = row.find_all("td")
                if not cells:
                    continue

                link = row.find("a", href=True)
                if not link:
                    continue

                href = link.get("href", "")
                link_text = link.get_text(strip=True)

                if any(x in link_text.lower() for x in ["ios", "android", "mobile"]):
                    continue

                version = self._extract_cortex_xdr_version(link_text)
                if not version:
                    continue

                # For archive releases, only include >= 7.7
                prev_header = table.find_previous(["h1", "h2", "h3"])
                if prev_header and "archive" in prev_header.get_text().lower():
                    try:
                        major_minor = tuple(map(int, version.split(".")[:2]))
                        if major_minor < (7, 7):
                            continue
                    except (ValueError, IndexError):
                        pass

                if version in seen_versions:
                    continue
                seen_versions.add(version)

                if not href.startswith("http"):
                    href = f"{CORTEX_BASE_URL}{href}"

                release_date = None
                if date_col is not None and date_col < len(cells):
                    date_text = cells[date_col].get_text(strip=True)
                    release_date = self._parse_cortex_release_date(date_text)

                releases.append((version, href, release_date))
                logger.debug("Found Cortex XDR release: %s -> %s (date: %s)",
                            version, href[:80], release_date)

        return releases

    def _parse_cortex_xdr_release_page(self, soup) -> tuple[list[Issue], list[Issue]]:
        """Parse a Cortex XDR release page for known and addressed issues."""
        known_issues: list[Issue] = []
        addressed_issues: list[Issue] = []

        current_section = None

        for element in soup.find_all(["h1", "h2", "h3", "h4", "table"]):
            if element.name in ["h1", "h2", "h3", "h4"]:
                heading_text = element.get_text(strip=True).lower()

                if ("addressed" in heading_text or "fixed" in heading_text) and "issue" in heading_text:
                    current_section = "addressed"
                elif "known" in heading_text and ("limitation" in heading_text or "issue" in heading_text):
                    current_section = "known"
                elif "feature" in heading_text or "enhancement" in heading_text or "improvement" in heading_text:
                    current_section = "feature"
                continue

            if element.name == "table" and current_section in ["known", "addressed"]:
                if element.find_parent("table"):
                    continue

                headers = [th.get_text(strip=True).upper() for th in element.find_all("th")]

                if "FEATURE" in headers:
                    continue

                issue_col = None
                desc_col = None

                for i, h in enumerate(headers):
                    if h in ["ISSUE", "BUG", "ID"]:
                        issue_col = i
                    elif h in ["DESCRIPTION", "LIMITATION", "DETAILS"]:
                        desc_col = i

                if issue_col is None:
                    issue_col = 0
                    desc_col = 1 if len(headers) > 1 else 0

                for row in element.find_all("tr")[1:]:
                    cells = row.find_all("td")
                    if len(cells) <= issue_col:
                        continue

                    bug_id_cell = cells[issue_col]
                    bug_id_text = bug_id_cell.get_text(strip=True)

                    platform_match = re.search(r"\(([^)]+)\)", bug_id_text)
                    affected_components: Optional[list[str]] = None
                    if platform_match:
                        platform = platform_match.group(1).strip().lower()
                        platform_map = {
                            "windows": "Windows",
                            "linux": "Linux",
                            "macos": "macOS",
                            "mac": "macOS",
                            "android": "Android",
                            "ios": "iOS",
                        }
                        if platform in platform_map:
                            affected_components = [platform_map[platform]]

                    bug_id = re.sub(r"\([^)]+\)", "", bug_id_text)
                    bug_id = bug_id.split("\n")[0].strip()
                    bug_id = re.sub(r"[‑–—]", "-", bug_id)

                    if not bug_id or not re.match(r"^[A-Z]+-\d+", bug_id):
                        match = re.search(r"([A-Z]+-\d+)", bug_id_cell.get_text())
                        if match:
                            bug_id = match.group(1)
                        else:
                            continue

                    description = ""
                    if desc_col is not None and desc_col < len(cells):
                        description = cells[desc_col].get_text(strip=True)
                    else:
                        full_text = row.get_text(strip=True)
                        description = full_text.replace(bug_id, "", 1).strip()

                    description = re.sub(r"\s+", " ", description).strip()
                    clean_desc, workaround = extract_workaround(description)

                    issue = Issue(
                        bug_id=bug_id,
                        description=clean_desc or description,
                        workaround=workaround,
                        affected_components=affected_components,
                    )

                    if current_section == "known":
                        known_issues.append(issue)
                    else:
                        addressed_issues.append(issue)

        return known_issues, addressed_issues

    async def crawl(
        self,
        major_versions: Optional[list[str]] = None,
        skip_versions: Optional[set[str]] = None,
    ) -> CrawlResult:
        """Crawl Cortex XDR Agent release notes.

        Uses the FluidTopics khub API when a `fluidtopics` client was injected;
        otherwise falls back to the legacy Playwright shadow-DOM crawl.
        """
        if self._fluidtopics is not None:
            return await self._crawl_via_fluidtopics(skip_versions)
        return await self._legacy_crawl(major_versions, skip_versions)

    async def _crawl_via_fluidtopics(
        self,
        skip_versions: Optional[set[str]] = None,
    ) -> CrawlResult:
        """Crawl Cortex XDR via the FluidTopics khub JSON API."""
        skip_versions = skip_versions or set()
        failed_fetches: list[FailedFetch] = []
        self._log("Crawling Cortex XDR Agent via FluidTopics...")

        try:
            maps = await self._fluidtopics.list_maps(product="Cortex XDR")
        except Exception as exc:
            self._log(f"  Error listing Cortex XDR maps: {exc}")
            failed_fetches.append(
                FailedFetch(
                    url=f"{CORTEX_BASE_URL}/api/khub/maps",
                    error=str(exc),
                    product=self.product_id,
                    issue_type="maps",
                )
            )
            return CrawlResult(
                product=Product(
                    id=self.product_id,
                    name=self.product_name,
                    versions=[],
                ),
                failed_fetches=failed_fetches,
            )

        # Filter to release-notes maps only.  The portal can contain other
        # Cortex maps (admin guides, etc.).
        rn_maps = [m for m in maps if "Release Notes" in m.get("title", "")]
        self._log(f"  Found {len(rn_maps)} Cortex XDR release-notes maps")

        # version → (known_issues, addressed_issues, release_date)
        versions_data: dict[
            str, tuple[list[Issue], list[Issue], Optional[str]]
        ] = {}

        for m in rn_maps:
            map_id = m["id"]
            try:
                topics = await self._fluidtopics.list_topics(map_id=map_id)
            except Exception as exc:
                failed_fetches.append(
                    FailedFetch(
                        url=f"{CORTEX_BASE_URL}/api/khub/maps/{map_id}/topics",
                        error=str(exc),
                        product=self.product_id,
                        issue_type="topics",
                    )
                )
                continue

            for t in topics:
                title = t.get("title", "")
                title_lower = title.lower()

                # Only known-issues / known-limitations / addressed / fixed
                # topics carry the bug tables we care about.
                is_addressed = (
                    "addressed" in title_lower or "fixed" in title_lower
                ) and "issue" in title_lower
                is_known = (
                    "known" in title_lower
                    and ("issue" in title_lower or "limitation" in title_lower)
                )
                if not (is_addressed or is_known):
                    continue

                # Pull the exact version from metadata or derive from title.
                ver = _extract_version_from_metadata(
                    t
                ) or self._extract_cortex_xdr_version(title)
                if ver is None:
                    continue
                if ver in skip_versions:
                    continue

                try:
                    page = await self._fluidtopics.fetch_topic(
                        map_id=map_id, topic_id=t["id"]
                    )
                except Exception as exc:
                    failed_fetches.append(
                        FailedFetch(
                            url=t.get("contentApiEndpoint", ""),
                            error=str(exc),
                            product=self.product_id,
                            version=ver,
                            issue_type="addressed" if is_addressed else "known",
                        )
                    )
                    continue
                if page.status_code != 200:
                    failed_fetches.append(
                        FailedFetch(
                            url=t.get("contentApiEndpoint", ""),
                            error=f"HTTP {page.status_code}",
                            product=self.product_id,
                            version=ver,
                            issue_type="addressed" if is_addressed else "known",
                        )
                    )
                    continue

                soup = BeautifulSoup(page.html, "lxml")
                topic_known, topic_addressed = self._parse_cortex_xdr_release_page_html(
                    soup, force_section="known" if is_known else "addressed"
                )

                kk, aa, date = versions_data.setdefault(
                    ver, ([], [], _extract_publication_date(t))
                )
                kk.extend(topic_known)
                aa.extend(topic_addressed)

        product_versions: list[ProductVersion] = []
        for ver, (known, addressed, date) in versions_data.items():
            if not known and not addressed:
                continue
            product_versions.append(
                ProductVersion(
                    version=ver,
                    release_date=date,
                    known_issues=self._deduplicate_issues(known),
                    addressed_issues=self._deduplicate_issues(addressed),
                )
            )

        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(
                failed_fetches
            )
            failed_fetches = still_failed

        product_versions.sort(
            key=lambda v: self._version_sort_key(v.version), reverse=True
        )

        return CrawlResult(
            product=Product(
                id=self.product_id,
                name=self.product_name,
                versions=product_versions,
            ),
            failed_fetches=failed_fetches,
        )

    def _parse_cortex_xdr_release_page_html(
        self, soup, *, force_section: str
    ) -> tuple[list[Issue], list[Issue]]:
        """Parse a FluidTopics content fragment for issues.

        FluidTopics returns one topic = one section (e.g. only addressed
        issues or only known limitations). The parser-of-record
        (`_parse_cortex_xdr_release_page`) walks sibling headings to decide
        the section; for these topic fragments we pass `force_section`
        directly because the heading is in the parent topic title, not
        the HTML.
        """
        known: list[Issue] = []
        addressed: list[Issue] = []
        for table in soup.find_all("table"):
            if table.find_parent("table"):
                continue
            headers = [
                th.get_text(strip=True).upper() for th in table.find_all("th")
            ]
            if "FEATURE" in headers:
                continue
            issue_col = None
            desc_col = None
            for i, h in enumerate(headers):
                if h in ("ISSUE", "BUG", "ID"):
                    issue_col = i
                elif h in ("DESCRIPTION", "LIMITATION", "DETAILS"):
                    desc_col = i
            if issue_col is None:
                issue_col = 0
                desc_col = 1 if len(headers) > 1 else 0

            for row in table.find_all("tr")[1:]:
                cells = row.find_all("td")
                if len(cells) <= issue_col:
                    continue
                bug_id_cell = cells[issue_col]
                bug_id_text = bug_id_cell.get_text(strip=True)

                platform_match = re.search(r"\(([^)]+)\)", bug_id_text)
                affected_components: Optional[list[str]] = None
                if platform_match:
                    platform = platform_match.group(1).strip().lower()
                    platform_map = {
                        "windows": "Windows",
                        "linux": "Linux",
                        "macos": "macOS",
                        "mac": "macOS",
                        "android": "Android",
                        "ios": "iOS",
                    }
                    if platform in platform_map:
                        affected_components = [platform_map[platform]]

                bug_id = re.sub(r"\([^)]+\)", "", bug_id_text)
                bug_id = bug_id.split("\n")[0].strip()
                bug_id = re.sub(r"[‑–—]", "-", bug_id)

                if not bug_id or not re.match(r"^[A-Z]+-\d+", bug_id):
                    match = re.search(r"([A-Z]+-\d+)", bug_id_cell.get_text())
                    if match:
                        bug_id = match.group(1)
                    else:
                        continue

                description = ""
                if desc_col is not None and desc_col < len(cells):
                    description = cells[desc_col].get_text(strip=True)
                else:
                    description = row.get_text(strip=True).replace(bug_id, "", 1).strip()

                description = re.sub(r"\s+", " ", description).strip()
                clean_desc, workaround = extract_workaround(description)

                issue = Issue(
                    bug_id=bug_id,
                    description=clean_desc or description,
                    workaround=workaround,
                    affected_components=affected_components,
                )

                if force_section == "known":
                    known.append(issue)
                else:
                    addressed.append(issue)

        return known, addressed

    async def _legacy_crawl(
        self,
        major_versions: Optional[list[str]] = None,
        skip_versions: Optional[set[str]] = None,
    ) -> CrawlResult:
        """Crawl Cortex XDR via the legacy Playwright shadow-DOM walk."""
        self._log("Crawling Cortex XDR Agent (legacy Playwright)...")
        failed_fetches: list[FailedFetch] = []
        skip_versions = skip_versions or set()

        releases_url = f"{CORTEX_BASE_URL}/r/Cortex-XDR/Cortex-XDR-Agent-Releases/Cortex-XDR-Agent-Releases"

        try:
            soup = await self._fetch_cortex_page_with_semaphore(releases_url, wait_time=5000)
        except Exception as e:
            self._log(f"  Error fetching releases page: {e}")
            failed_fetches.append(FailedFetch(
                url=releases_url,
                error=str(e),
                product=self.product_id,
                issue_type="releases",
            ))
            return CrawlResult(
                product=Product(id=self.product_id, name=self.product_name, versions=[]),
                failed_fetches=failed_fetches,
            )

        release_links = self._parse_cortex_xdr_releases_page(soup)
        self._log(f"  Found {len(release_links)} releases to process")

        releases_to_fetch: list[tuple[str, str, Optional[str]]] = []
        for version, url, release_date in release_links:
            if version in skip_versions:
                self._log(f"  Skipping existing version: {version}")
            else:
                releases_to_fetch.append((version, url, release_date))

        if not releases_to_fetch:
            self._log("  No new versions to fetch")
            return CrawlResult(
                product=Product(id=self.product_id, name=self.product_name, versions=[]),
                failed_fetches=failed_fetches,
            )

        self._log(f"  Fetching {len(releases_to_fetch)} versions...")

        version_dates: dict[str, Optional[str]] = {v: d for v, _, d in releases_to_fetch}

        async def fetch_release(version: str, url: str) -> tuple[str, Optional[any], Optional[str]]:
            try:
                soup = await self._fetch_cortex_page_with_semaphore(url, wait_time=5000)
                return (version, soup, None)
            except Exception as e:
                return (version, None, str(e))

        fetch_tasks = [fetch_release(ver, url) for ver, url, _ in releases_to_fetch]
        results = await asyncio.gather(*fetch_tasks)

        all_product_versions: list[ProductVersion] = []

        for version, soup, error in results:
            if error:
                self._log(f"  Error fetching {version}: {error}")
                failed_fetches.append(FailedFetch(
                    url=next((u for v, u, _ in releases_to_fetch if v == version), ""),
                    error=error,
                    product=self.product_id,
                    version=version,
                    issue_type="release",
                ))
                continue

            known_issues, addressed_issues = self._parse_cortex_xdr_release_page(soup)

            self._log(f"  {version}: {len(known_issues)} known, {len(addressed_issues)} addressed")

            if known_issues or addressed_issues:
                all_product_versions.append(ProductVersion(
                    version=version,
                    release_date=version_dates.get(version),
                    known_issues=self._deduplicate_issues(known_issues),
                    addressed_issues=self._deduplicate_issues(addressed_issues),
                ))

        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(
                failed_fetches
            )
            failed_fetches = still_failed

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

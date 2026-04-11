"""Panorama Plugin for SD-WAN crawler implementation."""

import asyncio
import logging
import re

from bugdb.models import Issue, Product, ProductVersion

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch
from ..utils import normalize_text

logger = logging.getLogger(__name__)


class SDWANPluginCrawler(BaseCrawler):
    """Crawler for Panorama Plugin for SD-WAN release notes.

    This product has a unique structure:
    - Only known issues pages exist (no separate addressed issues pages)
    - Fix information is embedded in known issues text
    - Issues are in div.topic containers, not tables
    """

    product_id = "sdwan-plugin"
    product_name = "Panorama Plugin for SD-WAN"

    async def discover_versions(self) -> list[str]:
        """Discover available SD-WAN Plugin major versions.

        Returns:
            List of major version strings (e.g., ["3-4", "3-3"]).
        """
        logger.debug("Discovering SD-WAN Plugin versions by probing URLs")

        candidate_versions = [
            "3-4",
            "3-3",
            "3-2",
            "3-1",
            "3-0",
            "2-2",
            "2-1",
            "2-0",
            "1-0",
        ]

        valid_versions = []

        async def check_version(version: str) -> str | None:
            """Check if a version URL exists."""
            version_num = version.replace("-", "") + "0"
            url = f"/sd-wan/release-notes/panorama-plugin-for-sd-wan/sd-wan-plugin-{version_num}"
            try:
                soup = await self._fetch_page_with_semaphore(url)
                title = soup.find("title")
                title_text = title.get_text().lower() if title else ""
                if "404" in title_text or "not found" in title_text or "error" in title_text:
                    return None
                h1 = soup.find("h1")
                if h1 and ("plugin" in h1.get_text().lower() or "sd-wan" in h1.get_text().lower()):
                    logger.debug("Found valid SD-WAN Plugin version: %s", version)
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
            "Discovered %d SD-WAN Plugin versions: %s", len(sorted_versions), sorted_versions
        )
        return sorted_versions

    async def _parse_sdwan_plugin_issues_page(
        self, url: str, major_version: str
    ) -> tuple[list[Issue], dict[str, list[Issue]]]:
        """Parse known issues page for SD-WAN Plugin.

        Args:
            url: URL of the known issues page.
            major_version: The major version being parsed (e.g., "3-3").

        Returns:
            Tuple of (known_issues, addressed_issues_by_version).
        """
        known_issues: list[Issue] = []
        addressed_by_version: dict[str, list[Issue]] = {}

        try:
            soup = await self._fetch_page_with_semaphore(url)

            for topic in soup.find_all("div", class_="topic"):
                title_elem = topic.find(["h2", "h3"], class_="title")
                if not title_elem:
                    continue

                bug_id = title_elem.get_text(strip=True)

                if not re.match(r"^(PAN|PLUG)-\d+$", bug_id):
                    continue

                description_parts = []
                affected_components = None
                workaround_text = None
                fix_info_text = None

                shortdesc = topic.find("div", class_="shortdesc")
                if shortdesc:
                    description_parts.append(normalize_text(shortdesc))

                in_workaround = False
                first_p_processed = False

                for p_elem in topic.find_all("div", class_="p"):
                    p_text = normalize_text(p_elem)

                    b_elem = p_elem.find("b")
                    if b_elem and "workaround" in b_elem.get_text().lower():
                        in_workaround = True
                        workaround_parts = []
                        for sibling in b_elem.next_siblings:
                            if hasattr(sibling, "get_text"):
                                workaround_parts.append(sibling.get_text(strip=True))
                            elif isinstance(sibling, str):
                                workaround_parts.append(sibling.strip())
                        if workaround_parts:
                            workaround_text = " ".join(workaround_parts).strip()
                            workaround_text = re.sub(r"\s+", " ", workaround_text).strip()
                            workaround_text = re.sub(r"^[:\-]\s*", "", workaround_text)
                        continue

                    tt_elem = p_elem.find("tt")
                    if tt_elem:
                        tt_text = normalize_text(tt_elem)
                        if "this issue is addressed" in tt_text.lower():
                            fix_info_text = tt_text
                            continue

                    if not in_workaround and not first_p_processed:
                        first_p_processed = True
                        component_match = re.match(r"^\(\s*([^)]+?)\s*\)\s*", p_text)
                        if component_match:
                            affected_components = [component_match.group(1).strip()]
                            remaining = p_text[component_match.end() :].strip()
                            if remaining:
                                description_parts.append(remaining)
                            continue

                    if not in_workaround:
                        description_parts.append(p_text)

                full_description = " ".join(description_parts)
                desc_cleaned = re.sub(r"\s+", " ", full_description).strip()

                desc_prefix_match = re.match(
                    r"^Description\s+of\s+" + re.escape(bug_id) + r"[\s:.\-]*",
                    desc_cleaned,
                    re.IGNORECASE,
                )
                if desc_prefix_match:
                    desc_cleaned = desc_cleaned[desc_prefix_match.end() :].strip()

                # Extract fix versions from fix_info_text
                plugin_fix_versions = []
                if fix_info_text:
                    version_matches = re.findall(
                        r"(\d+\.\d+(?:\.\d+)?(?:-[a-zA-Z0-9]+)?)", fix_info_text
                    )
                    seen = set()
                    for v in version_matches:
                        if v not in seen:
                            seen.add(v)
                            major_match = re.match(r"(\d+)\.", v)
                            if major_match and int(major_match.group(1)) < 8:
                                plugin_fix_versions.append(v)

                fix_info = fix_info_text

                issue = Issue(
                    bug_id=bug_id,
                    description=desc_cleaned,
                    workaround=workaround_text,
                    fix_info=fix_info,
                    affected_components=affected_components,
                )

                known_issues.append(issue)

                for fix_version in plugin_fix_versions:
                    if fix_version not in addressed_by_version:
                        addressed_by_version[fix_version] = []
                    addressed_issue = Issue(
                        bug_id=bug_id,
                        description=desc_cleaned,
                        workaround=workaround_text,
                        fix_info=f"Plugin {fix_version}",
                        affected_components=affected_components,
                    )
                    addressed_by_version[fix_version].append(addressed_issue)

                logger.debug("Parsed SD-WAN Plugin issue: %s", bug_id)

        except Exception as e:
            logger.error("Error parsing SD-WAN Plugin page %s: %s", url, e)
            self._log(f"  Error parsing {url}: {e}")
            raise

        return known_issues, addressed_by_version

    async def crawl(
        self,
        major_versions: list[str] | None = None,
        skip_versions: set[str] | None = None,
    ) -> CrawlResult:
        """Crawl Panorama Plugin for SD-WAN release notes.

        Args:
            major_versions: List of major versions to crawl.
            skip_versions: Set of version strings to skip.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        skip_versions = skip_versions or set()
        failed_fetches: list[FailedFetch] = []

        if major_versions is None:
            self._log("Discovering available Panorama Plugin for SD-WAN versions...")
            major_versions = await self.discover_versions()
            self._log(f"Found versions: {', '.join(major_versions)}")

        all_product_versions: list[ProductVersion] = []

        for major_version in major_versions:
            version_str = major_version.replace("-", ".")
            self._log(f"Crawling Panorama Plugin for SD-WAN {version_str}...")

            version_num = major_version.replace("-", "") + "0"
            known_issues_url = (
                f"/sd-wan/release-notes/panorama-plugin-for-sd-wan"
                f"/sd-wan-plugin-{version_num}"
                f"/known-issues-in-sd-wan-plugin-{version_num}"
            )

            try:
                known_issues, addressed_by_version = await self._parse_sdwan_plugin_issues_page(
                    known_issues_url, major_version
                )

                if version_str not in skip_versions:
                    known_filtered = self._deduplicate_issues(known_issues)
                    if known_filtered:
                        all_product_versions.append(
                            ProductVersion(
                                version=version_str,
                                known_issues=known_filtered,
                                addressed_issues=[],
                            )
                        )
                        self._log(f"    {version_str}: {len(known_filtered)} known issues")

                for fix_version, issues in addressed_by_version.items():
                    if fix_version not in skip_versions:
                        addressed_filtered = self._deduplicate_issues(issues)
                        if addressed_filtered:
                            existing_pv = next(
                                (pv for pv in all_product_versions if pv.version == fix_version),
                                None,
                            )
                            if existing_pv:
                                existing_pv.addressed_issues.extend(addressed_filtered)
                            else:
                                all_product_versions.append(
                                    ProductVersion(
                                        version=fix_version,
                                        known_issues=[],
                                        addressed_issues=addressed_filtered,
                                    )
                                )
                            self._log(
                                f"    {fix_version}: {len(addressed_filtered)} addressed issues"
                            )

            except Exception as e:
                failed_fetches.append(
                    FailedFetch(
                        url=known_issues_url,
                        error=str(e),
                        product=self.product_id,
                        version=version_str,
                        issue_type="known",
                    )
                )
                self._log(f"  Error fetching {known_issues_url}: {e}")

        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(failed_fetches)
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

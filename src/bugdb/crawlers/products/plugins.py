"""Generic Panorama/VM-Series plugin crawler implementation."""

import asyncio
import logging
import re

from bugdb.models import Product, ProductVersion

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch, PluginConfig, VersionInfo

logger = logging.getLogger(__name__)


# Plugin configurations for all supported plugins
PLUGIN_CONFIGS: dict[str, PluginConfig] = {
    "vm-series-plugin": PluginConfig(
        product_id="vm-series-plugin",
        product_name="VM-Series Plugin",
        base_url="/plugins/vm-series-and-panorama-plugins-release-notes/vm-series-plugin",
        version_link_patterns=["vm-series-plugin-", "vmseries-plugin-"],
    ),
    "plugin-aws": PluginConfig(
        product_id="plugin-aws",
        product_name="Panorama Plugin for AWS",
        base_url="/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-aws",
        version_link_patterns=["aws-plugin-", "panorama-plugin-for-aws-"],
    ),
    "plugin-azure": PluginConfig(
        product_id="plugin-azure",
        product_name="Panorama Plugin for Azure",
        base_url="/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-azure",
        version_link_patterns=["azure-plugin-", "panorama-plugin-for-azure-"],
    ),
    "plugin-gcp": PluginConfig(
        product_id="plugin-gcp",
        product_name="Panorama Plugin for GCP",
        base_url="/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-gcp",
        version_link_patterns=["gcp-plugin-", "panorama-plugin-for-gcp-"],
    ),
    "plugin-vmware-nsx": PluginConfig(
        product_id="plugin-vmware-nsx",
        product_name="Panorama Plugin for VMware NSX",
        base_url="/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-vmware-nsx",
        version_link_patterns=[
            "nsx-plugin-",
            "vmware-nsx-plugin-",
            "panorama-plugin-for-vmware-nsx-",
        ],
    ),
    "plugin-vmware-vcenter": PluginConfig(
        product_id="plugin-vmware-vcenter",
        product_name="Panorama Plugin for VMware vCenter",
        base_url="/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-vmware-vcenter",
        version_link_patterns=["vcenter-plugin-", "panorama-plugin-for-vmware-vcenter-"],
    ),
    "plugin-kubernetes": PluginConfig(
        product_id="plugin-kubernetes",
        product_name="Panorama Plugin for Kubernetes",
        base_url="/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-kubernetes",
        version_link_patterns=["kubernetes-plugin-", "panorama-plugin-for-kubernetes-"],
    ),
    "plugin-cisco-aci": PluginConfig(
        product_id="plugin-cisco-aci",
        product_name="Panorama Plugin for Cisco ACI",
        base_url="/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-cisco-aci",
        version_link_patterns=["aci-plugin-", "panorama-plugin-for-cisco-aci-"],
    ),
    "plugin-cisco-trustsec": PluginConfig(
        product_id="plugin-cisco-trustsec",
        product_name="Panorama Plugin for Cisco TrustSec",
        base_url="/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-cisco-trustsec",
        version_link_patterns=["trustsec-plugin-", "panorama-plugin-for-cisco-trustsec-"],
    ),
    "plugin-ztp": PluginConfig(
        product_id="plugin-ztp",
        product_name="Panorama Plugin for Zero Touch Provisioning",
        base_url="/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-zero-touch-provisioning",
        version_link_patterns=["ztp-plugin-", "zero-touch-provisioning-"],
    ),
    "plugin-clustering": PluginConfig(
        product_id="plugin-clustering",
        product_name="Panorama Plugin for Clustering",
        base_url="/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-clustering",
        version_link_patterns=["clustering-plugin-", "panorama-plugin-for-clustering-"],
    ),
}


class PluginCrawler(BaseCrawler):
    """Generic crawler for Panorama/VM-Series plugins.

    This handles all plugins that follow the standard table-based format
    with known issues and addressed issues pages.
    """

    def __init__(
        self,
        config: PluginConfig,
        headless: bool = True,
        verbose: bool = False,
        debug: bool = False,
        max_concurrency: int = 3,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ):
        """Initialize the plugin crawler.

        Args:
            config: Plugin configuration.
            headless: Whether to run browser in headless mode.
            verbose: Whether to print progress messages.
            debug: Whether to enable debug logging.
            max_concurrency: Maximum number of concurrent page fetches.
            max_retries: Maximum number of retry attempts.
            retry_delay: Base delay between retries.
        """
        super().__init__(
            headless=headless,
            verbose=verbose,
            debug=debug,
            max_concurrency=max_concurrency,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        self.config = config
        self.product_id = config.product_id
        self.product_name = config.product_name

    async def discover_versions(self) -> list[VersionInfo]:
        """Discover available versions for the plugin.

        Returns:
            List of VersionInfo with version strings and issue page URLs.
        """
        logger.debug(
            "Discovering %s versions from %s", self.config.product_name, self.config.base_url
        )

        version_infos: dict[str, VersionInfo] = {}

        def normalize_url(href: str) -> str:
            """Normalize a URL to a usable path."""
            href = re.sub(r"^/content/techdocs/en_US", "", href)
            href = re.sub(r"\.html$", "", href)
            return href

        def extract_version_from_url(href: str) -> str | None:
            """Extract version number from a URL."""
            for pattern in self.config.version_link_patterns:
                if pattern in href.lower():
                    after_pattern = href.lower().split(pattern)[-1]

                    match = re.match(r"(\d+)-(\d+)-(\d+)(?:-h\d+)?(?:[/-]|$|\.html)", after_pattern)
                    if match:
                        return f"{match.group(1)}.{match.group(2)}.{match.group(3)}"

                    match = re.match(r"(\d)(\d)(\d)(?:[/-]|$|\.html)", after_pattern)
                    if match:
                        return f"{match.group(1)}.{match.group(2)}.{match.group(3)}"

                    match = re.match(r"(\d)-?(\d)(?:[/-]|$|\.html)", after_pattern)
                    if match:
                        return f"{match.group(1)}.{match.group(2)}.0"

            return None

        try:
            soup = await self._fetch_page_with_semaphore(self.config.base_url)

            title = soup.find("title")
            title_text = title.get_text().lower() if title else ""
            if "404" in title_text or "not found" in title_text:
                logger.warning("Plugin index page not found: %s", self.config.base_url)
                return []

            for link in soup.find_all("a", href=True):
                href = link["href"]
                href_lower = href.lower()

                if not any(
                    kw in href_lower
                    for kw in self.config.known_issues_keywords
                    + self.config.addressed_issues_keywords
                ):
                    continue

                if not any(p in href_lower for p in self.config.version_link_patterns):
                    continue

                version = extract_version_from_url(href)
                if not version:
                    continue

                normalized_url = normalize_url(href)

                if version not in version_infos:
                    version_infos[version] = VersionInfo(
                        version=version,
                        known_issues_urls=[],
                        addressed_issues_urls=[],
                    )

                # Classify by last path segment to avoid false matches
                # (e.g., parent path "known-and-addressed/addressed-issues").
                last_segment = normalized_url.rstrip("/").rsplit("/", 1)[-1].lower()
                # Skip "known-and-addressed-issues" hub pages — they are
                # link-only indexes with no issue tables, so fetching
                # them is pure waste. Defensive: the same keyword-based
                # classification below would otherwise match both
                # "known" and "addressed" on these hub URLs.
                if "known-and-addressed" in last_segment:
                    continue
                is_addressed = any(
                    kw in last_segment for kw in self.config.addressed_issues_keywords
                )
                is_known = any(kw in last_segment for kw in self.config.known_issues_keywords)

                if (
                    is_addressed
                    and normalized_url not in version_infos[version].addressed_issues_urls
                ):
                    version_infos[version].addressed_issues_urls.append(normalized_url)
                    logger.debug("Found addressed issues URL for %s: %s", version, normalized_url)
                elif is_known and normalized_url not in version_infos[version].known_issues_urls:
                    version_infos[version].known_issues_urls.append(normalized_url)
                    logger.debug("Found known issues URL for %s: %s", version, normalized_url)

        except Exception as e:
            logger.error("Error discovering %s versions: %s", self.config.product_name, e)
            self._log(f"  Error discovering versions: {e}")

        sorted_versions = sorted(
            version_infos.values(),
            key=lambda v: self._version_sort_key(v.version),
            reverse=True,
        )

        logger.debug("Discovered %d %s versions", len(sorted_versions), self.config.product_name)
        return sorted_versions

    async def crawl(
        self,
        major_versions: list[str] | None = None,
        skip_versions: set[str] | None = None,
    ) -> CrawlResult:
        """Crawl plugin release notes.

        Args:
            major_versions: List of major versions to crawl (e.g., ["5-3", "5-2"]).
            skip_versions: Set of version strings to skip.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        skip_versions = skip_versions or set()
        failed_fetches: list[FailedFetch] = []

        self._log(f"Discovering available {self.config.product_name} versions...")
        discovered_versions = await self.discover_versions()

        if major_versions is not None:
            major_version_prefixes = [mv.replace("-", ".") for mv in major_versions]
            discovered_versions = [
                v
                for v in discovered_versions
                if any(v.version.startswith(prefix) for prefix in major_version_prefixes)
            ]

        if discovered_versions:
            versions_str = ", ".join(v.version for v in discovered_versions[:5])
            if len(discovered_versions) > 5:
                versions_str += f" (+{len(discovered_versions) - 5} more)"
            self._log(f"Found {len(discovered_versions)} versions: {versions_str}")

        all_product_versions: list[ProductVersion] = []

        versions_to_fetch = [v for v in discovered_versions if v.version not in skip_versions]
        skipped_count = len(discovered_versions) - len(versions_to_fetch)
        if skipped_count > 0:
            self._log(f"  Skipping {skipped_count} already-fetched versions")

        for version_info in versions_to_fetch:
            self._log(f"  Crawling {self.config.product_name} {version_info.version}...")

            fetch_tasks = []
            url_types = []

            for known_url in version_info.known_issues_urls:
                fetch_tasks.append(self._parse_issues_page(known_url))
                url_types.append(("known", known_url))

            for addressed_url in version_info.addressed_issues_urls:
                fetch_tasks.append(self._parse_issues_page(addressed_url))
                url_types.append(("addressed", addressed_url))

            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            known_issues = []
            addressed_issues = []

            for i, result in enumerate(results):
                issue_type, url = url_types[i]
                if isinstance(result, Exception):
                    # Record the failure for BOTH issue_types. Previously only
                    # the "known" branch appended a FailedFetch, so addressed-
                    # issue fetch errors disappeared from the retry pass and
                    # the fetch report entirely.
                    failed_fetches.append(
                        FailedFetch(
                            url=url,
                            error=str(result),
                            product=self.config.product_id,
                            version=version_info.version,
                            issue_type=issue_type,
                        )
                    )
                    logger.debug("Error fetching %s issues %s: %s", issue_type, url, result)
                elif issue_type == "known":
                    known_issues.extend(result)
                else:
                    addressed_issues.extend(result)

            known_issues = self._deduplicate_issues(known_issues)
            addressed_issues = self._deduplicate_issues(addressed_issues)

            if known_issues or addressed_issues:
                all_product_versions.append(
                    ProductVersion(
                        version=version_info.version,
                        known_issues=known_issues,
                        addressed_issues=addressed_issues,
                    )
                )
                self._log(
                    f"    {version_info.version}: {len(known_issues)} known, "
                    f"{len(addressed_issues)} addressed"
                )

        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(failed_fetches)
            failed_fetches = still_failed

        all_product_versions.sort(
            key=lambda v: self._version_sort_key(v.version),
            reverse=True,
        )

        return CrawlResult(
            product=Product(
                id=self.config.product_id,
                name=self.config.product_name,
                versions=all_product_versions,
            ),
            failed_fetches=failed_fetches,
        )

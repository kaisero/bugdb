"""Web crawler for Palo Alto Networks release notes."""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, Browser

from bugdb.models import BugDatabase, Issue, Metadata, Product, ProductVersion


def get_existing_versions(database: BugDatabase) -> dict[str, set[str]]:
    """Extract existing product versions from a BugDatabase.

    Args:
        database: Existing BugDatabase to extract versions from.

    Returns:
        Dict mapping product IDs to sets of version strings.
        Example: {"globalprotect": {"6.2.1", "6.2.0"}, "panos": {"12.1.5"}}
    """
    result: dict[str, set[str]] = {}
    for product in database.products:
        result[product.id] = {v.version for v in product.versions}
    return result


def merge_databases(existing: BugDatabase, new: BugDatabase) -> BugDatabase:
    """Merge two BugDatabases, combining products and versions.

    New versions are added to existing products. If a product doesn't exist
    in the existing database, it's added entirely. Versions are sorted
    after merging.

    Args:
        existing: The existing database to merge into.
        new: The new database with additional versions.

    Returns:
        A new BugDatabase with merged content.
    """
    # Create a dict of existing products by ID
    products_by_id: dict[str, Product] = {p.id: p for p in existing.products}

    for new_product in new.products:
        if new_product.id in products_by_id:
            # Merge versions into existing product
            existing_product = products_by_id[new_product.id]
            existing_versions = {v.version for v in existing_product.versions}

            # Add new versions that don't already exist
            merged_versions = list(existing_product.versions)
            for new_version in new_product.versions:
                if new_version.version not in existing_versions:
                    merged_versions.append(new_version)

            # Sort versions (newest first)
            merged_versions.sort(
                key=lambda v: _version_sort_key(v.version),
                reverse=True,
            )

            # Update the product with merged versions
            products_by_id[new_product.id] = Product(
                id=existing_product.id,
                name=existing_product.name,
                versions=merged_versions,
            )
        else:
            # Add new product entirely
            products_by_id[new_product.id] = new_product

    # Use metadata from existing database but update generated_at
    return BugDatabase(
        metadata=Metadata(
            generated_at=datetime.now(timezone.utc),
            version=existing.metadata.version,
            source=existing.metadata.source,
        ),
        products=list(products_by_id.values()),
    )


def _version_sort_key(version: str) -> tuple:
    """Create a sort key for version strings.

    Args:
        version: Version string like "6.2.8-h9" or "6.1.0".

    Returns:
        Tuple for sorting.
    """
    # Split into base version and suffix
    match = re.match(r"(\d+)\.(\d+)\.(\d+)(?:-(.+))?", version)
    if match:
        major, minor, patch = (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )
        suffix = match.group(4) or ""
        # Extract numeric part from suffix (e.g., "h9" -> 9, "c471" -> 471)
        suffix_num = 0
        suffix_match = re.search(r"(\d+)", suffix)
        if suffix_match:
            suffix_num = int(suffix_match.group(1))
        return (major, minor, patch, suffix_num)
    return (0, 0, 0, 0)


# Configure module logger
logger = logging.getLogger(__name__)

BASE_URL = "https://docs.paloaltonetworks.com"


def configure_logging(debug: bool = False) -> None:
    """Configure logging for the crawler module.

    Args:
        debug: If True, enables DEBUG level logging. Otherwise, INFO level.
    """
    level = logging.DEBUG if debug else logging.INFO
    handler = logging.StreamHandler()
    handler.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    # Clear existing handlers and add ours
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)


@dataclass
class VersionInfo:
    """Information about a product version."""

    version: str
    known_issues_urls: list[str]
    addressed_issues_urls: list[str]


class PaloAltoCrawler:
    """Async crawler for Palo Alto Networks release notes."""

    def __init__(
        self,
        headless: bool = True,
        verbose: bool = False,
        debug: bool = False,
        max_concurrency: int = 3,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ):
        """Initialize the crawler.

        Args:
            headless: Whether to run browser in headless mode.
            verbose: Whether to print progress messages.
            debug: Whether to enable debug logging (more detailed than verbose).
            max_concurrency: Maximum number of concurrent page fetches.
            max_retries: Maximum number of retry attempts for failed requests.
            retry_delay: Base delay between retries in seconds (exponential backoff).
        """
        self.headless = headless
        self.verbose = verbose
        self.debug = debug
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._semaphore: Optional[asyncio.Semaphore] = None

        # Configure logging if debug is enabled
        if debug:
            configure_logging(debug=True)

    async def __aenter__(self):
        logger.debug("Starting Playwright browser (headless=%s)", self.headless)
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._semaphore = asyncio.Semaphore(self.max_concurrency)
        logger.debug("Browser started, max_concurrency=%d", self.max_concurrency)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        logger.debug("Closing browser and Playwright")
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    def _log(self, message: str) -> None:
        """Print a log message if verbose mode is enabled."""
        if self.verbose:
            print(message)
        # Also log at info level for debug mode
        logger.info(message)

    async def _new_page(self) -> Page:
        """Create a new browser page."""
        return await self._browser.new_page()

    async def _fetch_page(
        self, page: Page, url: str, wait_time: int = 3000
    ) -> BeautifulSoup:
        """Fetch a page and return parsed HTML.

        Args:
            page: Playwright page instance.
            url: URL to fetch.
            wait_time: Time to wait for JS to render (ms).

        Returns:
            BeautifulSoup parsed HTML.
        """
        from urllib.parse import urljoin

        full_url = url if url.startswith("http") else urljoin(BASE_URL, url)
        logger.debug("Fetching page: %s", full_url)
        await page.goto(full_url, wait_until="networkidle")
        await page.wait_for_timeout(wait_time)
        content = await page.content()
        logger.debug("Page fetched successfully: %s (%d bytes)", full_url, len(content))
        return BeautifulSoup(content, "lxml")

    async def _fetch_page_with_semaphore(
        self, url: str, wait_time: int = 3000
    ) -> BeautifulSoup:
        """Fetch a page with concurrency control and retry logic.

        Creates a new page, fetches the URL, and closes the page.
        Uses semaphore to limit concurrent requests.
        Retries on transient failures with exponential backoff.

        Args:
            url: URL to fetch.
            wait_time: Time to wait for JS to render (ms).

        Returns:
            BeautifulSoup parsed HTML.

        Raises:
            Exception: If all retry attempts fail.
        """
        last_error = None

        for attempt in range(self.max_retries):
            logger.debug("Acquiring semaphore for: %s (attempt %d)", url, attempt + 1)
            async with self._semaphore:
                logger.debug("Semaphore acquired, creating new page for: %s", url)
                page = await self._new_page()
                try:
                    result = await self._fetch_page(page, url, wait_time)
                    logger.debug("Successfully fetched: %s", url)
                    return result
                except Exception as e:
                    last_error = e
                    logger.warning(
                        "Fetch failed for %s (attempt %d/%d): %s",
                        url, attempt + 1, self.max_retries, e
                    )
                    self._log(
                        f"  Retry {attempt + 1}/{self.max_retries} for {url}: {e}"
                    )
                finally:
                    await page.close()

            # Exponential backoff before retry
            if attempt < self.max_retries - 1:
                delay = self.retry_delay * (2 ** attempt)
                logger.debug("Waiting %.1f seconds before retry for: %s", delay, url)
                await asyncio.sleep(delay)

        # All retries failed
        raise last_error

    async def discover_globalprotect_versions(self) -> list[str]:
        """Discover available GlobalProtect major versions.

        Returns:
            List of major version strings (e.g., ["6-3", "6-2", "6-1", "6-0"]).
        """
        logger.debug("Discovering GlobalProtect versions")
        page = await self._new_page()

        # Navigate to a GlobalProtect release notes page to find version dropdown
        soup = await self._fetch_page(
            page, "/globalprotect/6-2/globalprotect-app-release-notes"
        )

        versions = set()
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "globalprotect" in href.lower() and "release-notes" in href.lower():
                # Extract major version pattern like 6-1, 6-2, 6-3
                # Handle both /release-notes/6-3 and /release-notes/6-3.html formats
                match = re.search(r"/release-notes/(\d+-\d+)(?:\.html)?(?:/|$)", href)
                if match:
                    versions.add(match.group(1))
                    logger.debug("Found GlobalProtect version: %s", match.group(1))

        await page.close()

        # Sort versions in descending order (newest first)
        sorted_versions = sorted(
            versions, key=lambda v: [int(x) for x in v.split("-")], reverse=True
        )
        logger.debug("Discovered %d GlobalProtect versions: %s",
                     len(sorted_versions), sorted_versions)
        return sorted_versions

    async def crawl_globalprotect(
        self,
        major_versions: Optional[list[str]] = None,
        skip_versions: Optional[set[str]] = None,
    ) -> Product:
        """Crawl GlobalProtect release notes for one or more major versions.

        Args:
            major_versions: List of major versions to crawl (e.g., ["6-2", "6-1"]).
                           If None, discovers and crawls all available versions.
            skip_versions: Set of version strings to skip (e.g., {"6.2.1", "6.2.0"}).
                          Used for incremental fetching to avoid re-fetching existing versions.

        Returns:
            Product with all versions and issues.
        """
        skip_versions = skip_versions or set()
        # Discover versions if not specified
        if major_versions is None:
            self._log("Discovering available GlobalProtect versions...")
            major_versions = await self.discover_globalprotect_versions()
            self._log(f"Found versions: {', '.join(major_versions)}")

        all_product_versions = []

        for major_version in major_versions:
            self._log(f"Crawling GlobalProtect {major_version.replace('-', '.')}...")

            # Fetch multiple pages to find all issue links
            # This handles different URL structures across versions
            pages_to_fetch = [
                f"/globalprotect/release-notes/{major_version}/globalprotect-addressed-issues",
                f"/globalprotect/release-notes/{major_version}/known-issues-related-to-gp-app",
                f"/globalprotect/{major_version}/globalprotect-app-release-notes",
            ]

            all_version_infos: dict[str, VersionInfo] = {}
            all_generic_known_urls: list[str] = []
            all_generic_addressed_urls: list[str] = []

            # Fetch index pages in parallel
            fetch_tasks = [
                self._fetch_page_with_semaphore(url) for url in pages_to_fetch
            ]
            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            for soup in results:
                if isinstance(soup, Exception):
                    continue

                title = soup.find("title")
                if title and "not found" in title.get_text().lower():
                    continue

                version_infos, generic_known_urls, generic_addressed_urls = (
                    self._extract_globalprotect_versions(soup, major_version)
                )

                # Merge version-specific infos
                for vi in version_infos:
                    if vi.version not in all_version_infos:
                        all_version_infos[vi.version] = VersionInfo(
                            version=vi.version,
                            known_issues_urls=[],
                            addressed_issues_urls=[],
                        )
                    for ku in vi.known_issues_urls:
                        if ku not in all_version_infos[vi.version].known_issues_urls:
                            all_version_infos[vi.version].known_issues_urls.append(ku)
                    for au in vi.addressed_issues_urls:
                        if au not in all_version_infos[vi.version].addressed_issues_urls:
                            all_version_infos[vi.version].addressed_issues_urls.append(
                                au
                            )

                # Merge generic URLs
                for ku in generic_known_urls:
                    if ku not in all_generic_known_urls:
                        all_generic_known_urls.append(ku)
                for au in generic_addressed_urls:
                    if au not in all_generic_addressed_urls:
                        all_generic_addressed_urls.append(au)

            if all_version_infos:
                # Filter out already-fetched versions
                versions_to_fetch = [
                    vi for vi in all_version_infos.values()
                    if vi.version not in skip_versions
                ]
                skipped_count = len(all_version_infos) - len(versions_to_fetch)
                if skipped_count > 0:
                    self._log(f"  Skipping {skipped_count} already-fetched versions")

                # Version-specific pages (6.2+, 6.3+ style)
                self._log(f"  Fetching {len(versions_to_fetch)} sub-versions")
                batch_results = await self._crawl_versions_parallel(versions_to_fetch)
                all_product_versions.extend(batch_results)
            elif all_generic_known_urls or all_generic_addressed_urls:
                # Generic pages with multiple versions (6.1, 6.0 style)
                self._log("  Parsing multi-version pages...")
                multi_version_results = await self._parse_multi_version_pages(
                    all_generic_known_urls, all_generic_addressed_urls
                )
                skipped_count = 0
                for pv in multi_version_results:
                    if pv.version in skip_versions:
                        skipped_count += 1
                        continue
                    if pv.known_issues or pv.addressed_issues:
                        all_product_versions.append(pv)
                        self._log(
                            f"    {pv.version}: {len(pv.known_issues)} known, "
                            f"{len(pv.addressed_issues)} addressed"
                        )
                if skipped_count > 0:
                    self._log(f"  Skipped {skipped_count} already-fetched versions")
            else:
                self._log(f"  No issues found for {major_version}")

        # Sort versions (newest first)
        all_product_versions.sort(
            key=lambda v: self._version_sort_key(v.version),
            reverse=True,
        )

        return Product(
            id="globalprotect",
            name="GlobalProtect",
            versions=all_product_versions,
        )

    def _version_sort_key(self, version: str) -> tuple:
        """Create a sort key for version strings.

        Args:
            version: Version string like "6.2.8-h9" or "6.1.0".

        Returns:
            Tuple for sorting.
        """
        # Split into base version and suffix
        match = re.match(r"(\d+)\.(\d+)\.(\d+)(?:-(.+))?", version)
        if match:
            major, minor, patch = (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            )
            suffix = match.group(4) or ""
            # Extract numeric part from suffix (e.g., "h9" -> 9, "c471" -> 471)
            suffix_num = 0
            suffix_match = re.search(r"(\d+)", suffix)
            if suffix_match:
                suffix_num = int(suffix_match.group(1))
            return (major, minor, patch, suffix_num)
        return (0, 0, 0, 0)

    def _extract_globalprotect_versions(
        self, soup: BeautifulSoup, major_version: str
    ) -> tuple[list[VersionInfo], list[str], list[str]]:
        """Extract version information from GlobalProtect release notes page.

        Args:
            soup: Parsed HTML of the release notes page.
            major_version: The major version being crawled (e.g., "6-2").

        Returns:
            Tuple of (version_specific_infos, generic_known_urls, generic_addressed_urls).
            For newer versions (6.2+), returns version-specific infos with empty generic lists.
            For older versions (6.1, 6.0), returns empty version list with generic URLs.
        """
        versions: dict[str, VersionInfo] = {}
        generic_known_urls: list[str] = []
        generic_addressed_urls: list[str] = []

        # Find all links to known issues and addressed issues pages
        for link in soup.find_all("a", href=True):
            href = link["href"]
            text = link.get_text(strip=True)

            # Check if this is a known issues or addressed issues link
            is_known = "known-issues" in href.lower() or "known issues" in text.lower()
            is_addressed = "addressed" in href.lower() or "addressed" in text.lower()

            if not is_known and not is_addressed:
                continue

            # Extract version from URL only (not text) to determine if page is version-specific
            # Text like "GlobalProtect App 6.1.2" shouldn't make a generic page version-specific
            version = self._extract_version_from_url(href)

            if version:
                # Version-specific page (e.g., 6.2.1 Known Issues)
                if version not in versions:
                    versions[version] = VersionInfo(
                        version=version,
                        known_issues_urls=[],
                        addressed_issues_urls=[],
                    )

                if is_known and href not in versions[version].known_issues_urls:
                    versions[version].known_issues_urls.append(href)
                elif is_addressed and href not in versions[version].addressed_issues_urls:
                    versions[version].addressed_issues_urls.append(href)
            else:
                # Generic page without version in URL (e.g., older 6.1, 6.0 structure)
                if is_known and href not in generic_known_urls:
                    generic_known_urls.append(href)
                elif is_addressed and href not in generic_addressed_urls:
                    generic_addressed_urls.append(href)

        return list(versions.values()), generic_known_urls, generic_addressed_urls

    def _extract_version_from_text(self, text: str) -> Optional[str]:
        """Extract version number from text.

        Args:
            text: Text that may contain a version number.

        Returns:
            Version string or None.
        """
        # Match patterns like "6.2.1", "6.2.8-h9", "6.2.8-c471"
        match = re.search(r"(\d+\.\d+\.\d+)(?:-([a-zA-Z0-9]+))?", text)
        if match:
            version = match.group(1)
            suffix = match.group(2)
            # Exclude page type indicators from being captured as version suffixes
            if suffix and suffix.lower() not in ("known", "addressed", "issues"):
                version += f"-{suffix}"
            return version
        return None

    def _extract_version_from_url(self, url: str) -> Optional[str]:
        """Extract version number from URL.

        Args:
            url: URL that may contain a version number.

        Returns:
            Version string or None.
        """
        # Match patterns in URLs like "6-2-1" -> "6.2.1"
        match = re.search(r"(\d+)-(\d+)-(\d+)(?:-([a-zA-Z0-9]+))?", url)
        if match:
            version = f"{match.group(1)}.{match.group(2)}.{match.group(3)}"
            suffix = match.group(4)
            # Exclude page type indicators from being captured as version suffixes
            if suffix and suffix.lower() not in ("known", "addressed", "issues"):
                version += f"-{suffix}"
            return version
        return None

    async def _crawl_version(self, version_info: VersionInfo) -> ProductVersion:
        """Crawl a specific version's known and addressed issues.

        Args:
            version_info: Version information with URLs.

        Returns:
            ProductVersion with issues.
        """
        known_issues = []
        addressed_issues = []

        # Gather all URLs to fetch
        all_urls = []
        url_types = []

        for url in version_info.known_issues_urls:
            all_urls.append(url)
            url_types.append("known")

        for url in version_info.addressed_issues_urls:
            all_urls.append(url)
            url_types.append("addressed")

        # Fetch all pages in parallel
        fetch_tasks = [self._parse_issues_page(url) for url in all_urls]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        # Process results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                continue
            if url_types[i] == "known":
                known_issues.extend(result)
            else:
                addressed_issues.extend(result)

        # Deduplicate by bug_id
        known_issues = self._deduplicate_issues(known_issues)
        addressed_issues = self._deduplicate_issues(addressed_issues)

        return ProductVersion(
            version=version_info.version,
            known_issues=known_issues,
            addressed_issues=addressed_issues,
        )

    async def _crawl_versions_parallel(
        self, version_infos: list[VersionInfo]
    ) -> list[ProductVersion]:
        """Crawl multiple versions in parallel.

        Args:
            version_infos: List of version information objects.

        Returns:
            List of ProductVersion objects.
        """
        tasks = [self._crawl_version(vi) for vi in version_infos]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        product_versions = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self._log(f"    Error crawling {version_infos[i].version}: {result}")
                continue

            pv = result
            if pv.known_issues or pv.addressed_issues:
                product_versions.append(pv)
                self._log(
                    f"    {pv.version}: {len(pv.known_issues)} known, "
                    f"{len(pv.addressed_issues)} addressed"
                )

        return product_versions

    async def _parse_multi_version_pages(
        self,
        known_urls: list[str],
        addressed_urls: list[str],
    ) -> list[ProductVersion]:
        """Parse pages that contain multiple versions with section headers.

        These pages have h3 headers like "GlobalProtect 6.1.12 Addressed Issues (Android)"
        followed by tables with issues for that specific version.

        Args:
            known_urls: URLs to known issues pages.
            addressed_urls: URLs to addressed issues pages.

        Returns:
            List of ProductVersion objects, one per version found.
        """
        # Dict to collect issues by version
        known_by_version: dict[str, list[Issue]] = {}
        addressed_by_version: dict[str, list[Issue]] = {}

        # Fetch all pages in parallel
        all_urls = known_urls + addressed_urls
        url_types = ["known"] * len(known_urls) + ["addressed"] * len(addressed_urls)

        fetch_tasks = [
            self._parse_multi_version_issues_page(url) for url in all_urls
        ]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        # Process results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                continue

            version_issues = result
            target_dict = known_by_version if url_types[i] == "known" else addressed_by_version

            for version, issues in version_issues.items():
                if version not in target_dict:
                    target_dict[version] = []
                target_dict[version].extend(issues)

        # Combine into ProductVersion objects
        all_versions = set(known_by_version.keys()) | set(addressed_by_version.keys())
        results = []

        for version in all_versions:
            known = self._deduplicate_issues(known_by_version.get(version, []))
            addressed = self._deduplicate_issues(addressed_by_version.get(version, []))
            results.append(
                ProductVersion(
                    version=version,
                    known_issues=known,
                    addressed_issues=addressed,
                )
            )

        return results

    async def _parse_multi_version_issues_page(self, url: str) -> dict[str, list[Issue]]:
        """Parse a page with multiple version sections.

        Args:
            url: URL of the issues page.

        Returns:
            Dict mapping version strings to lists of Issue objects.
        """
        results: dict[str, list[Issue]] = {}

        try:
            soup = await self._fetch_page_with_semaphore(url)

            # Find all elements in document order and track current version
            # when we see a version header, update current version
            # when we see a table, associate it with current version
            current_version = None

            # Get all h3, h4, and table elements in document order
            for element in soup.find_all(["h3", "h4", "table"]):
                if element.name in ["h3", "h4"]:
                    # Check if this is a version header
                    header_text = element.get_text(strip=True)
                    version_match = re.search(
                        r"GlobalProtect(?:\s+App)?\s+(\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+)?)",
                        header_text,
                        re.IGNORECASE,
                    )
                    if version_match:
                        current_version = version_match.group(1)
                elif element.name == "table" and current_version:
                    # Parse this table and associate with current version
                    issues = self._parse_issues_table(element)
                    if issues:
                        if current_version not in results:
                            results[current_version] = []
                        results[current_version].extend(issues)

        except Exception as e:
            self._log(f"Error parsing multi-version page {url}: {e}")

        return results

    def _parse_issues_table(self, table) -> list[Issue]:
        """Parse issues from a single table element.

        Args:
            table: BeautifulSoup table element.

        Returns:
            List of Issue objects.
        """
        issues = []

        # Check if this is an issues table by looking at headers
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        logger.debug("Table headers: %s", headers)

        # Look for "issue" or bug ID column
        issue_col = None
        desc_col = None

        for i, header in enumerate(headers):
            if "issue" in header or "bug" in header or "id" in header:
                issue_col = i
            elif "description" in header or "summary" in header:
                desc_col = i

        if issue_col is None:
            logger.debug("No issue column found in table, skipping")
            return issues

        logger.debug("Found issue column at index %d, description at index %s",
                     issue_col, desc_col)

        # Parse rows
        rows = table.find_all("tr")[1:]  # Skip header row
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(issue_col, desc_col or 0):
                continue

            bug_id = cells[issue_col].get_text(strip=True)
            description = (
                cells[desc_col].get_text(strip=True) if desc_col is not None else ""
            )

            # Validate bug_id format (e.g., GPC-12345, PAN-12345)
            if not re.match(r"^[A-Z]+-\d+$", bug_id):
                logger.debug("Skipping invalid bug ID: %s", bug_id)
                continue

            logger.debug("Parsed issue: %s", bug_id)
            issues.append(
                Issue(
                    bug_id=bug_id,
                    description=description,
                )
            )

        logger.debug("Parsed %d issues from table", len(issues))
        return issues

    async def _parse_issues_page(self, url: str) -> list[Issue]:
        """Parse issues from a known/addressed issues page.

        Args:
            url: URL of the issues page.

        Returns:
            List of Issue objects.
        """
        issues = []
        logger.debug("Parsing issues page: %s", url)

        try:
            soup = await self._fetch_page_with_semaphore(url)

            # Find tables with issue data
            tables = soup.find_all("table")
            logger.debug("Found %d tables on page: %s", len(tables), url)

            for table in tables:
                # Check if this is an issues table by looking at headers
                headers = [
                    th.get_text(strip=True).lower() for th in table.find_all("th")
                ]

                # Look for "issue" or bug ID column
                issue_col = None
                desc_col = None

                for i, header in enumerate(headers):
                    if "issue" in header or "bug" in header or "id" in header:
                        issue_col = i
                    elif "description" in header or "summary" in header:
                        desc_col = i

                if issue_col is None:
                    continue

                # Parse rows
                for row in table.find_all("tr")[1:]:  # Skip header row
                    cells = row.find_all(["td", "th"])
                    if len(cells) <= max(issue_col, desc_col or 0):
                        continue

                    bug_id = cells[issue_col].get_text(strip=True)
                    description = (
                        cells[desc_col].get_text(strip=True)
                        if desc_col is not None
                        else ""
                    )

                    # Validate bug_id format (e.g., GPC-12345, PAN-12345)
                    if not re.match(r"^[A-Z]+-\d+$", bug_id):
                        logger.debug("Skipping invalid bug ID: %s", bug_id)
                        continue

                    issues.append(
                        Issue(
                            bug_id=bug_id,
                            description=description,
                        )
                    )

        except Exception as e:
            logger.error("Error parsing %s: %s", url, e)
            self._log(f"Error parsing {url}: {e}")

        logger.debug("Parsed %d issues from page: %s", len(issues), url)
        return issues

    def _deduplicate_issues(self, issues: list[Issue]) -> list[Issue]:
        """Remove duplicate issues by bug_id.

        Args:
            issues: List of issues that may contain duplicates.

        Returns:
            Deduplicated list of issues.
        """
        seen = set()
        unique = []
        for issue in issues:
            if issue.bug_id not in seen:
                seen.add(issue.bug_id)
                unique.append(issue)
        return unique

    async def discover_prisma_access_agent_versions(self) -> list[str]:
        """Discover available Prisma Access Agent major versions.

        Returns:
            List of major version strings (e.g., ["26-1", "25-2", "25-1"]).
        """
        page = await self._new_page()

        # Navigate to the known issues index page to find version links
        soup = await self._fetch_page(
            page,
            "/prisma-access-agent/release-notes/prisma-access-agent-release-information"
            "/prisma-access-agent-known-issues",
        )

        versions = set()
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "prisma-access-agent" in href.lower() and (
                "known-issues" in href.lower() or "addressed" in href.lower()
            ):
                # Extract version pattern like 26-1-2, 26-1, 25-2-1
                # Pattern: prisma-access-agent-XX-Y[-Z]-known-issues
                match = re.search(
                    r"prisma-access-agent-(\d+-\d+)(?:-\d+)?-(?:known-issues|addressed-issues)",
                    href,
                )
                if match:
                    versions.add(match.group(1))

        await page.close()

        # Sort versions in descending order (newest first)
        return sorted(
            versions, key=lambda v: [int(x) for x in v.split("-")], reverse=True
        )

    async def crawl_prisma_access_agent(
        self,
        major_versions: Optional[list[str]] = None,
        skip_versions: Optional[set[str]] = None,
    ) -> Product:
        """Crawl Prisma Access Agent release notes for one or more major versions.

        Args:
            major_versions: List of major versions to crawl (e.g., ["26-1", "25-2"]).
                           If None, discovers and crawls all available versions.
            skip_versions: Set of version strings to skip (e.g., {"26.1.2", "25.2.1"}).
                          Used for incremental fetching to avoid re-fetching existing versions.

        Returns:
            Product with all versions and issues.
        """
        skip_versions = skip_versions or set()
        # Discover versions if not specified
        if major_versions is None:
            self._log("Discovering available Prisma Access Agent versions...")
            major_versions = await self.discover_prisma_access_agent_versions()
            self._log(f"Found versions: {', '.join(major_versions)}")

        all_product_versions = []

        for major_version in major_versions:
            self._log(
                f"Crawling Prisma Access Agent {major_version.replace('-', '.')}..."
            )

            # Fetch the index pages to find all sub-version links
            known_issues_index = (
                "/prisma-access-agent/release-notes/prisma-access-agent-release-information"
                "/prisma-access-agent-known-issues"
            )
            addressed_issues_index = (
                "/prisma-access-agent/release-notes/prisma-access-agent-release-information"
                "/prisma-access-agent-addressed-issues"
            )

            version_infos: dict[str, VersionInfo] = {}

            # Fetch both index pages in parallel
            fetch_tasks = [
                self._fetch_page_with_semaphore(known_issues_index),
                self._fetch_page_with_semaphore(addressed_issues_index),
            ]
            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            # Parse known issues index page for version links
            if not isinstance(results[0], Exception):
                soup = results[0]
                for link in soup.find_all("a", href=True):
                    href = link["href"]
                    version = self._extract_prisma_access_agent_version(
                        href, major_version
                    )
                    if version:
                        if version not in version_infos:
                            version_infos[version] = VersionInfo(
                                version=version,
                                known_issues_urls=[],
                                addressed_issues_urls=[],
                            )
                        if href not in version_infos[version].known_issues_urls:
                            version_infos[version].known_issues_urls.append(href)

            # Parse addressed issues index page for version links
            if not isinstance(results[1], Exception):
                soup = results[1]
                for link in soup.find_all("a", href=True):
                    href = link["href"]
                    version = self._extract_prisma_access_agent_version(
                        href, major_version
                    )
                    if version:
                        if version not in version_infos:
                            version_infos[version] = VersionInfo(
                                version=version,
                                known_issues_urls=[],
                                addressed_issues_urls=[],
                            )
                        if href not in version_infos[version].addressed_issues_urls:
                            version_infos[version].addressed_issues_urls.append(href)

            if version_infos:
                # Filter out already-fetched versions
                versions_to_fetch = [
                    vi for vi in version_infos.values()
                    if vi.version not in skip_versions
                ]
                skipped_count = len(version_infos) - len(versions_to_fetch)
                if skipped_count > 0:
                    self._log(f"  Skipping {skipped_count} already-fetched versions")

                # Crawl versions in parallel
                self._log(f"  Fetching {len(versions_to_fetch)} sub-versions")
                batch_results = await self._crawl_versions_parallel(versions_to_fetch)
                all_product_versions.extend(batch_results)
            else:
                # Try direct URL for the major version (e.g., 26-1)
                version_str = major_version.replace("-", ".")
                if version_str in skip_versions:
                    self._log(f"  Skipping already-fetched version {version_str}")
                else:
                    self._log("  Trying direct version URLs...")
                    version_info = VersionInfo(
                        version=version_str,
                        known_issues_urls=[
                            f"/prisma-access-agent/release-notes/prisma-access-agent-release-information"
                            f"/prisma-access-agent-known-issues"
                            f"/prisma-access-agent-{major_version}-known-issues"
                        ],
                        addressed_issues_urls=[
                            f"/prisma-access-agent/release-notes/prisma-access-agent-release-information"
                            f"/prisma-access-agent-addressed-issues"
                            f"/prisma-access-agent-{major_version}-addressed-issues"
                        ],
                    )
                    pv = await self._crawl_version(version_info)
                    if pv.known_issues or pv.addressed_issues:
                        all_product_versions.append(pv)
                        self._log(
                            f"    {pv.version}: {len(pv.known_issues)} known, "
                            f"{len(pv.addressed_issues)} addressed"
                        )

        # Sort versions (newest first)
        all_product_versions.sort(
            key=lambda v: self._version_sort_key(v.version),
            reverse=True,
        )

        return Product(
            id="prisma-access-agent",
            name="Prisma Access Agent",
            versions=all_product_versions,
        )

    def _extract_prisma_access_agent_version(
        self, url: str, major_version: str
    ) -> Optional[str]:
        """Extract Prisma Access Agent version from URL if it matches the major version.

        Args:
            url: URL that may contain a version number.
            major_version: The major version to filter by (e.g., "26-1").

        Returns:
            Version string (e.g., "26.1.2") or None.
        """
        # Match patterns like prisma-access-agent-26-1-2-known-issues
        match = re.search(
            r"prisma-access-agent-(\d+)-(\d+)(?:-(\d+))?-(?:known-issues|addressed-issues)",
            url,
        )
        if match:
            major = match.group(1)
            minor = match.group(2)
            patch = match.group(3)

            # Check if this matches the requested major version
            url_major_version = f"{major}-{minor}"
            if url_major_version != major_version:
                return None

            if patch:
                return f"{major}.{minor}.{patch}"
            else:
                return f"{major}.{minor}"

        return None

    async def discover_panos_versions(self) -> list[str]:
        """Discover available PAN-OS major versions.

        Returns:
            List of major version strings (e.g., ["12-1", "11-2", "11-1"]).
        """
        versions = set()

        # Navigate to PAN-OS release notes pages to find version links in dropdown
        # Check both NGFW (12.x+) and PAN-OS (11.x and older) URL patterns
        pages_to_check = [
            "/ngfw/release-notes/12-1/features-introduced-in-pan-os",
            "/pan-os/11-2/pan-os-release-notes",
        ]

        # Fetch pages in parallel
        fetch_tasks = [
            self._fetch_page_with_semaphore(url) for url in pages_to_check
        ]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for soup in results:
            if isinstance(soup, Exception):
                continue

            for link in soup.find_all("a", href=True):
                href = link["href"]

                # Pattern 1: NGFW format (12.x+)
                # /ngfw/release-notes/12-1/...
                match = re.search(r"/ngfw/release-notes/(\d+-\d+)", href)
                if match:
                    versions.add(match.group(1))
                    continue

                # Pattern 2: PAN-OS format (11.x and older)
                # /pan-os/11-2/pan-os-release-notes/...
                match = re.search(r"/pan-os/(\d+-\d+)/pan-os-release-notes", href)
                if match:
                    versions.add(match.group(1))
                    continue

                # Pattern 3: Just /pan-os/XX-X/ links
                match = re.search(r"/pan-os/(\d+-\d+)(?:/|$)", href)
                if match:
                    versions.add(match.group(1))

        # Sort versions in descending order (newest first)
        return sorted(
            versions, key=lambda v: [int(x) for x in v.split("-")], reverse=True
        )

    def _get_panos_url_pattern(self, major_version: str) -> str:
        """Determine which URL pattern to use for a PAN-OS version.

        Args:
            major_version: Major version string (e.g., "12-1", "11-2").

        Returns:
            URL pattern type: "ngfw" for 12.x+, "panos" for 11.x and older.
        """
        major_num = int(major_version.split("-")[0])
        return "ngfw" if major_num >= 12 else "panos"

    async def crawl_panos(
        self,
        major_versions: Optional[list[str]] = None,
        skip_versions: Optional[set[str]] = None,
    ) -> Product:
        """Crawl PAN-OS release notes for one or more major versions.

        Args:
            major_versions: List of major versions to crawl (e.g., ["12-1", "11-2"]).
                           If None, discovers and crawls all available versions.
            skip_versions: Set of version strings to skip (e.g., {"12.1.5", "11.2.4"}).
                          Used for incremental fetching to avoid re-fetching existing versions.

        Returns:
            Product with all versions and issues.
        """
        skip_versions = skip_versions or set()
        # Discover versions if not specified
        if major_versions is None:
            self._log("Discovering available PAN-OS versions...")
            major_versions = await self.discover_panos_versions()
            self._log(f"Found versions: {', '.join(major_versions)}")

        all_product_versions = []

        for major_version in major_versions:
            self._log(f"Crawling PAN-OS {major_version.replace('-', '.')}...")

            # Determine URL pattern based on version
            url_pattern = self._get_panos_url_pattern(major_version)

            # Build index URLs based on pattern
            if url_pattern == "ngfw":
                # 12.x+ uses /ngfw/release-notes/12-1/...
                index_urls = [
                    f"/ngfw/release-notes/{major_version}/features-introduced-in-pan-os",
                    f"/ngfw/release-notes/{major_version}",
                ]
            else:
                # 11.x and older uses /pan-os/11-2/pan-os-release-notes/...
                index_urls = [
                    f"/pan-os/{major_version}/pan-os-release-notes",
                ]

            version_infos: dict[str, VersionInfo] = {}

            # Fetch index pages in parallel
            fetch_tasks = [
                self._fetch_page_with_semaphore(url) for url in index_urls
            ]
            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            for soup in results:
                if isinstance(soup, Exception):
                    continue

                # Find all links to known-and-addressed-issues pages
                for link in soup.find_all("a", href=True):
                    href = link["href"]

                    # Look for patterns like pan-os-12-1-5-known-and-addressed-issues
                    version = self._extract_panos_version_from_url(href, major_version)
                    if version:
                        if version not in version_infos:
                            version_dashed = version.replace(".", "-")

                            # Build URLs based on pattern
                            if url_pattern == "ngfw":
                                known_url = (
                                    f"/ngfw/release-notes/{major_version}"
                                    f"/pan-os-{version_dashed}-known-and-addressed-issues"
                                    f"/pan-os-{version_dashed}-known-issues"
                                )
                                addressed_url = (
                                    f"/ngfw/release-notes/{major_version}"
                                    f"/pan-os-{version_dashed}-known-and-addressed-issues"
                                    f"/pan-os-{version_dashed}-addressed-issues"
                                )
                            else:
                                known_url = (
                                    f"/pan-os/{major_version}/pan-os-release-notes"
                                    f"/pan-os-{version_dashed}-known-and-addressed-issues"
                                    f"/pan-os-{version_dashed}-known-issues"
                                )
                                addressed_url = (
                                    f"/pan-os/{major_version}/pan-os-release-notes"
                                    f"/pan-os-{version_dashed}-known-and-addressed-issues"
                                    f"/pan-os-{version_dashed}-addressed-issues"
                                )

                            version_infos[version] = VersionInfo(
                                version=version,
                                known_issues_urls=[known_url],
                                addressed_issues_urls=[addressed_url],
                            )

            if version_infos:
                # Filter out already-fetched versions
                versions_to_fetch = [
                    vi for vi in version_infos.values()
                    if vi.version not in skip_versions
                ]
                skipped_count = len(version_infos) - len(versions_to_fetch)
                if skipped_count > 0:
                    self._log(f"  Skipping {skipped_count} already-fetched versions")

                # Crawl versions in parallel
                self._log(f"  Fetching {len(versions_to_fetch)} sub-versions")
                batch_results = await self._crawl_versions_parallel(versions_to_fetch)
                all_product_versions.extend(batch_results)
            else:
                self._log(f"  No sub-versions found for {major_version}")

        # Sort versions (newest first)
        all_product_versions.sort(
            key=lambda v: self._version_sort_key(v.version),
            reverse=True,
        )

        return Product(
            id="panos",
            name="PAN-OS",
            versions=all_product_versions,
        )

    def _extract_panos_version_from_url(
        self, url: str, major_version: str
    ) -> Optional[str]:
        """Extract PAN-OS version from URL if it matches the major version.

        Args:
            url: URL that may contain a version number.
            major_version: The major version to filter by (e.g., "12-1").

        Returns:
            Version string (e.g., "12.1.5") or None.
        """
        # Match patterns like pan-os-12-1-5-known-and-addressed-issues
        # or pan-os-12-1-5-addressed-issues
        match = re.search(
            r"pan-os-(\d+)-(\d+)-(\d+)(?:-[a-zA-Z0-9]+)?-(?:known|addressed)", url
        )
        if match:
            major = match.group(1)
            minor = match.group(2)
            patch = match.group(3)

            # Check if this matches the requested major version
            url_major_version = f"{major}-{minor}"
            if url_major_version != major_version:
                return None

            return f"{major}.{minor}.{patch}"

        return None


async def _crawl_globalprotect_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Async implementation of GlobalProtect crawler."""
    async with PaloAltoCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        product = await crawler.crawl_globalprotect(major_versions, skip_versions)

        # Build source description
        if major_versions:
            versions_str = ", ".join(v.replace("-", ".") for v in major_versions)
            source = f"Palo Alto Networks GlobalProtect {versions_str} Release Notes"
        else:
            source = "Palo Alto Networks GlobalProtect Release Notes (All Versions)"

        return BugDatabase(
            metadata=Metadata(
                generated_at=datetime.now(timezone.utc),
                version="1.0.0",
                source=source,
            ),
            products=[product],
        )


async def _crawl_prisma_access_agent_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Async implementation of Prisma Access Agent crawler."""
    async with PaloAltoCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        product = await crawler.crawl_prisma_access_agent(major_versions, skip_versions)

        # Build source description
        if major_versions:
            versions_str = ", ".join(v.replace("-", ".") for v in major_versions)
            source = (
                f"Palo Alto Networks Prisma Access Agent {versions_str} Release Notes"
            )
        else:
            source = (
                "Palo Alto Networks Prisma Access Agent Release Notes (All Versions)"
            )

        return BugDatabase(
            metadata=Metadata(
                generated_at=datetime.now(timezone.utc),
                version="1.0.0",
                source=source,
            ),
            products=[product],
        )


async def _crawl_panos_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Async implementation of PAN-OS crawler."""
    async with PaloAltoCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        product = await crawler.crawl_panos(major_versions, skip_versions)

        # Build source description
        if major_versions:
            versions_str = ", ".join(v.replace("-", ".") for v in major_versions)
            source = f"Palo Alto Networks PAN-OS {versions_str} Release Notes"
        else:
            source = "Palo Alto Networks PAN-OS Release Notes (All Versions)"

        return BugDatabase(
            metadata=Metadata(
                generated_at=datetime.now(timezone.utc),
                version="1.0.0",
                source=source,
            ),
            products=[product],
        )


def crawl_globalprotect(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Crawl GlobalProtect release notes and return a BugDatabase.

    Args:
        major_versions: List of major versions to crawl (e.g., ["6-2", "6-1"]).
                       If None, discovers and crawls all available versions.
        headless: Whether to run browser in headless mode.
        verbose: Whether to print progress messages.
        debug: Whether to enable debug logging.
        max_concurrency: Maximum number of concurrent page fetches.
        skip_versions: Set of version strings to skip for incremental fetching.

    Returns:
        BugDatabase with GlobalProtect issues.
    """
    return asyncio.run(
        _crawl_globalprotect_async(
            major_versions, headless, verbose, debug, max_concurrency, skip_versions
        )
    )


def crawl_prisma_access_agent(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Crawl Prisma Access Agent release notes and return a BugDatabase.

    Args:
        major_versions: List of major versions to crawl (e.g., ["26-1", "25-2"]).
                       If None, discovers and crawls all available versions.
        headless: Whether to run browser in headless mode.
        verbose: Whether to print progress messages.
        debug: Whether to enable debug logging.
        max_concurrency: Maximum number of concurrent page fetches.
        skip_versions: Set of version strings to skip for incremental fetching.

    Returns:
        BugDatabase with Prisma Access Agent issues.
    """
    return asyncio.run(
        _crawl_prisma_access_agent_async(
            major_versions, headless, verbose, debug, max_concurrency, skip_versions
        )
    )


def crawl_panos(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Crawl PAN-OS release notes and return a BugDatabase.

    Args:
        major_versions: List of major versions to crawl (e.g., ["12-1", "11-2"]).
                       If None, discovers and crawls all available versions.
        headless: Whether to run browser in headless mode.
        verbose: Whether to print progress messages.
        debug: Whether to enable debug logging.
        max_concurrency: Maximum number of concurrent page fetches.
        skip_versions: Set of version strings to skip for incremental fetching.

    Returns:
        BugDatabase with PAN-OS issues.
    """
    return asyncio.run(
        _crawl_panos_async(
            major_versions, headless, verbose, debug, max_concurrency, skip_versions
        )
    )

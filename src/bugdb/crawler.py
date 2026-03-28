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


def extract_workaround(description: str) -> tuple[str, Optional[str]]:
    """Extract workaround text from an issue description.

    Looks for patterns like "Workaround: <text>" or "Workaround:<text>" in the
    description and extracts the workaround text, returning the cleaned description
    and the workaround separately.

    Args:
        description: The full issue description that may contain a workaround.

    Returns:
        Tuple of (cleaned_description, workaround). If no workaround is found,
        workaround will be None and description is returned unchanged.
    """
    if not description:
        return description, None

    # Pattern to match "Workaround:" followed by text
    # Handles variations like:
    # - "Workaround: text here"
    # - "Workaround:text here"
    # - "WORKAROUND: text here"
    # - Multi-line workarounds (until end of string or next section header)
    pattern = r"(?i)\bworkaround\s*:\s*(.+?)(?=\n(?:[A-Z][a-z]+\s*:|$)|$)"

    match = re.search(pattern, description, re.DOTALL | re.IGNORECASE)

    if match:
        workaround = match.group(1).strip()

        # Remove the workaround section from description
        cleaned_description = description[:match.start()].strip()

        # Also remove any text after the workaround that was captured
        remaining = description[match.end():].strip()
        if remaining:
            cleaned_description = f"{cleaned_description} {remaining}".strip() if cleaned_description else remaining

        # Replace newlines with spaces and clean up multiple spaces
        cleaned_description = re.sub(r'\s+', ' ', cleaned_description).strip()
        workaround = re.sub(r'\s+', ' ', workaround).strip()

        # Don't return empty workarounds
        if workaround:
            return cleaned_description, workaround

    return description, None


def extract_fix_info_from_description(
    description: str, existing_fix_info: Optional[str] = None
) -> tuple[str, Optional[str]]:
    """Extract fix information from an issue description.

    Looks for patterns like "This issue is resolved in <version>" in the
    description and extracts it as fix_info. If existing_fix_info is provided
    (e.g., from the bug ID column), it will be reformatted if it matches the
    "This issue is resolved in..." pattern.

    Args:
        description: The issue description that may contain fix information.
        existing_fix_info: Any fix_info already extracted from the bug ID.

    Returns:
        Tuple of (cleaned_description, fix_info). If no fix info is found
        and no existing_fix_info provided, fix_info will be None.
    """
    # Reformat existing_fix_info if it matches the "This issue is resolved in..." pattern
    if existing_fix_info:
        existing_match = re.match(
            r"(?i)^This\s+issue\s+is\s+resolved\s+in\s+(.+?)\.?$",
            existing_fix_info.strip()
        )
        if existing_match:
            existing_fix_info = f"Resolved in {existing_match.group(1).strip()}"

    if not description:
        return description, existing_fix_info

    # If we already have fix_info from elsewhere, don't extract again
    if existing_fix_info:
        return description, existing_fix_info

    # Pattern to match "This issue is resolved in <version/text>"
    # Handles variations like:
    # - "This issue is resolved in ION 6.3.3."
    # - "This issue is resolved in release 6.5.1."
    # - "This issue is resolved in Prisma SD-WAN ION 6.4.2."
    pattern = r"(?i)\bThis\s+issue\s+is\s+resolved\s+in\s+(.+?)(?:\.(?:\s|$)|$)"

    match = re.search(pattern, description, re.IGNORECASE)

    if match:
        fix_info = match.group(1).strip()

        # Remove the fix info sentence from description
        cleaned_description = description[:match.start()].strip()

        # Add any remaining text after the match
        remaining = description[match.end():].strip()
        if remaining:
            cleaned_description = f"{cleaned_description} {remaining}".strip() if cleaned_description else remaining

        # Clean up multiple spaces
        cleaned_description = re.sub(r'\s+', ' ', cleaned_description).strip()

        # Format the fix_info consistently
        fix_info = f"Resolved in {fix_info}"

        if fix_info and cleaned_description:
            return cleaned_description, fix_info

    return description, existing_fix_info


def extract_bug_id_and_fix_info(raw_bug_id: str) -> tuple[str, Optional[str]]:
    """Extract bug ID and additional fix information from a raw bug ID string.

    Some bug IDs include text like "EPM-4616Resolved in Prisma Access Agent 25.3".
    This function extracts the clean bug ID and any additional fix information.

    Args:
        raw_bug_id: The raw bug ID string that may contain additional text.

    Returns:
        Tuple of (bug_id, fix_info). If no fix info is found, fix_info will be None.
        If the raw string is not a valid bug ID format, returns (raw_bug_id, None).
    """
    if not raw_bug_id:
        return raw_bug_id, None

    # Pattern to extract bug ID (e.g., EPM-4616, PAN-12345) followed by optional text
    match = re.match(r"^([A-Z]+-\d+)(.*)$", raw_bug_id.strip())

    if match:
        bug_id = match.group(1)
        fix_info = match.group(2).strip() if match.group(2) else None

        # Return the cleaned fix_info, or None if empty
        if fix_info:
            return bug_id, fix_info

        return bug_id, None

    return raw_bug_id, None


def extract_affected_components(description: str) -> tuple[str, Optional[list[str]]]:
    """Extract affected components from the start of a description.

    Descriptions may start with parenthesized text like "(NGFW Clusters)" or
    "(PA-5500 Series firewalls only)" indicating affected components/platforms.
    This function extracts those and returns them as a list.

    Args:
        description: The issue description that may start with parenthesized components.

    Returns:
        Tuple of (cleaned_description, affected_components). If no components found,
        affected_components will be None.
    """
    if not description:
        return description, None

    # Pattern to match one or more parenthesized groups at the start
    # Examples: "(NGFW Clusters)", "(PA-5500 Series firewalls only)", "(Different ABC) (Another XYZ)"
    components = []
    cleaned = description.strip()

    # Keep extracting parenthesized text from the start
    while cleaned.startswith("("):
        match = re.match(r"^\(([^)]+)\)\s*", cleaned)
        if match:
            component = match.group(1).strip()
            if component:
                components.append(component)
            cleaned = cleaned[match.end():].strip()
        else:
            break

    if components:
        return cleaned, components

    return description, None


def table_to_text(table) -> str:
    """Convert an HTML table element to a plain text representation.

    Args:
        table: BeautifulSoup table element.

    Returns:
        Text representation of the table with rows separated by semicolons
        and cells separated by colons.
    """
    rows = []
    for tr in table.find_all("tr"):
        cells = [cell.get_text(strip=True) for cell in tr.find_all(["td", "th"])]
        if cells:
            rows.append(": ".join(cells))
    return "; ".join(rows)


def extract_cell_text_with_tables(cell) -> str:
    """Extract text from a table cell, converting any nested tables to text.

    Args:
        cell: BeautifulSoup td/th element.

    Returns:
        Text content with nested tables converted to inline text.
    """
    # Clone the cell to avoid modifying the original
    from copy import copy
    cell_copy = copy(cell)

    # Find all nested tables and replace them with text representation
    nested_tables = cell_copy.find_all("table")
    for nested_table in nested_tables:
        table_text = table_to_text(nested_table)
        nested_table.replace_with(f" [{table_text}] ")

    # Get the text content
    text = cell_copy.get_text(strip=True)
    return text


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
        # First try to find headers directly in thead or first row
        headers = []
        thead = table.find("thead")
        if thead:
            headers = [th.get_text(strip=True).lower() for th in thead.find_all("th")]
        else:
            first_row = table.find("tr")
            if first_row:
                headers = [th.get_text(strip=True).lower() for th in first_row.find_all("th")]

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

        # Parse rows (only direct children, not nested table rows)
        # If there's a tbody, use rows from there (header is in thead)
        tbody = table.find("tbody")
        if tbody:
            rows = tbody.find_all("tr", recursive=False)
        else:
            # No tbody, find all rows and skip header
            rows = table.find_all("tr", recursive=False)
            if not rows:
                rows = table.find_all("tr")
            # Skip first row if it's the header
            if rows and rows[0].find("th"):
                rows = rows[1:]

        for row in rows:
            # Skip rows that belong to nested tables
            if row.find_parent("table") != table and row.find_parent("tbody", recursive=False) is None:
                continue

            cells = row.find_all(["td", "th"], recursive=False)
            if len(cells) <= max(issue_col, desc_col or 0):
                continue

            raw_bug_id = cells[issue_col].get_text(strip=True)
            # Use extract_cell_text_with_tables to convert nested tables to text
            raw_description = (
                extract_cell_text_with_tables(cells[desc_col]) if desc_col is not None else ""
            )

            # Extract bug ID and fix info (e.g., "EPM-4616Resolved in..." -> "EPM-4616", "Resolved in...")
            bug_id, fix_info = extract_bug_id_and_fix_info(raw_bug_id)

            # Validate bug_id format (e.g., GPC-12345, PAN-12345)
            if not re.match(r"^[A-Z]+-\d+$", bug_id):
                logger.debug("Skipping invalid bug ID: %s", raw_bug_id)
                continue

            # Extract workaround from description if present
            description, workaround = extract_workaround(raw_description)

            # Extract fix info from description (e.g., "This issue is resolved in...")
            description, fix_info = extract_fix_info_from_description(description, fix_info)

            # Extract affected components from description start (e.g., "(NGFW Clusters)")
            description, affected_components = extract_affected_components(description)

            logger.debug("Parsed issue: %s (fix_info: %s, workaround: %s, components: %s)",
                        bug_id, fix_info is not None, workaround is not None,
                        affected_components is not None)
            issues.append(
                Issue(
                    bug_id=bug_id,
                    description=description,
                    workaround=workaround,
                    fix_info=fix_info,
                    affected_components=affected_components,
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

            # Find tables with issue data (only top-level, not nested tables)
            tables = soup.find_all("table")
            logger.debug("Found %d tables on page: %s", len(tables), url)

            for table in tables:
                # Skip nested tables (tables inside another table's cell)
                if table.find_parent("table"):
                    logger.debug("Skipping nested table")
                    continue

                # Check if this is an issues table by looking at headers
                headers = [
                    th.get_text(strip=True).lower() for th in table.find_all("th", recursive=False)
                    if not th.find_parent("table", recursive=False) or th.find_parent("table") == table
                ]
                # If no direct headers found, try finding them in thead
                if not headers:
                    thead = table.find("thead")
                    if thead:
                        headers = [th.get_text(strip=True).lower() for th in thead.find_all("th")]
                    else:
                        # Try first row
                        first_row = table.find("tr")
                        if first_row:
                            headers = [th.get_text(strip=True).lower() for th in first_row.find_all("th")]

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

                # Parse rows (only direct children, not nested table rows)
                # If there's a tbody, use rows from there (header is in thead)
                tbody = table.find("tbody")
                if tbody:
                    rows = tbody.find_all("tr", recursive=False)
                else:
                    # No tbody, find all rows and skip header
                    rows = table.find_all("tr", recursive=False)
                    if not rows:
                        rows = table.find_all("tr")
                    # Skip first row if it's the header
                    if rows and rows[0].find("th"):
                        rows = rows[1:]

                for row in rows:
                    # Skip rows from nested tables
                    if row.find_parent("table") != table:
                        continue

                    cells = row.find_all(["td", "th"], recursive=False)
                    if len(cells) <= max(issue_col, desc_col or 0):
                        continue

                    raw_bug_id = cells[issue_col].get_text(strip=True)
                    # Use extract_cell_text_with_tables to convert nested tables to text
                    raw_description = (
                        extract_cell_text_with_tables(cells[desc_col])
                        if desc_col is not None
                        else ""
                    )

                    # Extract bug ID and fix info (e.g., "EPM-4616Resolved in..." -> "EPM-4616", "Resolved in...")
                    bug_id, fix_info = extract_bug_id_and_fix_info(raw_bug_id)

                    # Validate bug_id format (e.g., GPC-12345, PAN-12345)
                    if not re.match(r"^[A-Z]+-\d+$", bug_id):
                        logger.debug("Skipping invalid bug ID: %s", raw_bug_id)
                        continue

                    # Extract workaround from description if present
                    description, workaround = extract_workaround(raw_description)

                    # Extract fix info from description
                    description, fix_info = extract_fix_info_from_description(description, fix_info)

                    # Extract affected components from description start (e.g., "(NGFW Clusters)")
                    description, affected_components = extract_affected_components(description)

                    issues.append(
                        Issue(
                            bug_id=bug_id,
                            description=description,
                            workaround=workaround,
                            fix_info=fix_info,
                            affected_components=affected_components,
                        )
                    )

        except Exception as e:
            logger.error("Error parsing %s: %s", url, e)
            self._log(f"Error parsing {url}: {e}")

        logger.debug("Parsed %d issues from page: %s", len(issues), url)
        return issues

    def _deduplicate_issues(self, issues: list[Issue]) -> list[Issue]:
        """Remove duplicate issues by bug_id, release_date, and description.

        Issues with the same bug_id but different release_dates or descriptions
        are kept. Only true duplicates (same bug_id, release_date, AND description)
        are removed.

        Args:
            issues: List of issues that may contain duplicates.

        Returns:
            Deduplicated list of issues.
        """
        seen = set()
        unique = []
        for issue in issues:
            # Use (bug_id, release_date, description_hash) as the deduplication key
            # Use first 100 chars of description to handle minor variations
            desc_key = (issue.description or "")[:100]
            key = (issue.bug_id, issue.release_date, desc_key)
            if key not in seen:
                seen.add(key)
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

    async def discover_prisma_access_versions(self) -> list[str]:
        """Discover available Prisma Access major versions.

        Returns:
            List of major version strings (e.g., ["6-1", "5-2", "5-1"]).
        """
        logger.debug("Discovering Prisma Access versions")
        page = await self._new_page()

        # Navigate to a Prisma Access release notes page to find version links
        soup = await self._fetch_page(
            page, "/prisma-access/release-notes/6-1/prisma-access-about"
        )

        versions = set()
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "prisma-access" in href.lower() and "release-notes" in href.lower():
                # Extract major version pattern like 6-1, 5-2
                match = re.search(r"/release-notes/(\d+-\d+)(?:/|$)", href)
                if match:
                    versions.add(match.group(1))
                    logger.debug("Found Prisma Access version: %s", match.group(1))

        await page.close()

        # Sort versions in descending order (newest first)
        sorted_versions = sorted(
            versions, key=lambda v: [int(x) for x in v.split("-")], reverse=True
        )
        logger.debug("Discovered %d Prisma Access versions: %s",
                     len(sorted_versions), sorted_versions)
        return sorted_versions

    async def crawl_prisma_access(
        self,
        major_versions: Optional[list[str]] = None,
        skip_versions: Optional[set[str]] = None,
    ) -> Product:
        """Crawl Prisma Access release notes for one or more major versions.

        Args:
            major_versions: List of major versions to crawl (e.g., ["6-1", "5-2"]).
                           If None, discovers and crawls all available versions.
            skip_versions: Set of version strings to skip (e.g., {"6.1.1", "5.2.0"}).
                          Used for incremental fetching to avoid re-fetching existing versions.

        Returns:
            Product with all versions and issues.
        """
        skip_versions = skip_versions or set()

        # Discover versions if not specified
        if major_versions is None:
            self._log("Discovering available Prisma Access versions...")
            major_versions = await self.discover_prisma_access_versions()
            self._log(f"Found versions: {', '.join(major_versions)}")

        all_product_versions = []

        for major_version in major_versions:
            version_str = major_version.replace("-", ".")
            self._log(f"Crawling Prisma Access {version_str}...")

            if version_str in skip_versions:
                self._log(f"  Skipping already-fetched version {version_str}")
                continue

            # Build URLs for this major version
            known_issues_url = (
                f"/prisma-access/release-notes/{major_version}"
                f"/prisma-access-about/prisma-access-known-issues"
            )
            addressed_issues_url = (
                f"/prisma-access/release-notes/{major_version}"
                f"/prisma-access-about/prisma-access-addressed-issues"
            )

            # Fetch both pages
            fetch_tasks = [
                self._parse_prisma_access_issues_page(known_issues_url, "known", major_version),
                self._parse_prisma_access_issues_page(addressed_issues_url, "addressed", major_version),
            ]
            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            # Collect issues by version
            known_by_version: dict[str, list[Issue]] = {}
            addressed_by_version: dict[str, list[Issue]] = {}

            # Process known issues
            if not isinstance(results[0], Exception):
                for version, issues in results[0].items():
                    if version not in skip_versions:
                        known_by_version[version] = issues

            # Process addressed issues
            if not isinstance(results[1], Exception):
                for version, issues in results[1].items():
                    if version not in skip_versions:
                        addressed_by_version[version] = issues

            # Combine into ProductVersion objects
            all_versions_set = set(known_by_version.keys()) | set(addressed_by_version.keys())

            for ver in all_versions_set:
                known = self._deduplicate_issues(known_by_version.get(ver, []))
                addressed = self._deduplicate_issues(addressed_by_version.get(ver, []))

                if known or addressed:
                    all_product_versions.append(
                        ProductVersion(
                            version=ver,
                            known_issues=known,
                            addressed_issues=addressed,
                        )
                    )
                    self._log(
                        f"    {ver}: {len(known)} known, {len(addressed)} addressed"
                    )

        # Sort versions (newest first)
        all_product_versions.sort(
            key=lambda v: self._version_sort_key(v.version),
            reverse=True,
        )

        return Product(
            id="prisma-access",
            name="Prisma Access",
            versions=all_product_versions,
        )

    async def _parse_prisma_access_issues_page(
        self, url: str, issue_type: str, major_version: str
    ) -> dict[str, list[Issue]]:
        """Parse a Prisma Access issues page with multiple sections.

        The page contains sections for the major version and also for
        minor versions (addressed) or features (known issues).

        Args:
            url: URL of the issues page.
            issue_type: Either "known" or "addressed".
            major_version: The major version being parsed (e.g., "6-1").

        Returns:
            Dict mapping version strings to lists of Issue objects.
        """
        results: dict[str, list[Issue]] = {}
        base_version = major_version.replace("-", ".")

        try:
            soup = await self._fetch_page_with_semaphore(url)

            # Track current context (version or feature)
            current_version = base_version
            current_feature = None

            # Find all h2, h3, h4 headers and tables
            for element in soup.find_all(["h2", "h3", "h4", "table"]):
                if element.name in ["h2", "h3", "h4"]:
                    header_text = element.get_text(strip=True)

                    # Check for version header (e.g., "6.1.1 Addressed Issues", "6.1.0-h5")
                    version_match = re.search(
                        r"(\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+)?)",
                        header_text,
                    )
                    if version_match:
                        current_version = version_match.group(1)
                        current_feature = None
                        logger.debug("Found version header: %s", current_version)
                        continue

                    # Check for feature header (for known issues)
                    # e.g., "Dynamic Privileges Access Known Issues"
                    if issue_type == "known":
                        # Common feature patterns
                        feature_patterns = [
                            r"^(.+?)\s+Known\s+Issues?$",
                            r"^Known\s+Issues?\s+(?:for|in|with)\s+(.+)$",
                            r"^(.+?)\s+Limitations?$",
                        ]
                        for pattern in feature_patterns:
                            feature_match = re.match(pattern, header_text, re.IGNORECASE)
                            if feature_match:
                                feature_name = feature_match.group(1).strip()
                                # Skip generic headers (exact matches and "Prisma Access X.X" patterns)
                                feature_lower = feature_name.lower()
                                is_generic = (
                                    feature_lower in ["prisma access", "general", ""]
                                    or feature_lower.startswith("prisma access ")
                                )
                                if not is_generic:
                                    current_feature = feature_name
                                    logger.debug("Found feature header: %s", current_feature)
                                break

                elif element.name == "table":
                    # Skip nested tables
                    if element.find_parent("table"):
                        continue

                    # Parse issues from this table
                    issues = self._parse_issues_table_with_feature(element, current_feature)

                    if issues:
                        if current_version not in results:
                            results[current_version] = []
                        results[current_version].extend(issues)

        except Exception as e:
            logger.error("Error parsing Prisma Access page %s: %s", url, e)
            self._log(f"  Error parsing {url}: {e}")

        return results

    def _parse_issues_table_with_feature(
        self, table, feature: Optional[str] = None
    ) -> list[Issue]:
        """Parse issues from a table, adding feature as affected_component.

        Args:
            table: BeautifulSoup table element.
            feature: Optional feature name to add to affected_components.

        Returns:
            List of Issue objects.
        """
        issues = []

        # Get headers
        headers = []
        thead = table.find("thead")
        if thead:
            headers = [th.get_text(strip=True).lower() for th in thead.find_all("th")]
        else:
            first_row = table.find("tr")
            if first_row:
                headers = [th.get_text(strip=True).lower() for th in first_row.find_all("th")]

        # Find column indices
        issue_col = None
        desc_col = None

        for i, header in enumerate(headers):
            if "issue" in header or "bug" in header or "id" in header:
                issue_col = i
            elif "description" in header or "summary" in header:
                desc_col = i

        if issue_col is None:
            return issues

        # Parse rows
        tbody = table.find("tbody")
        if tbody:
            rows = tbody.find_all("tr", recursive=False)
        else:
            rows = table.find_all("tr", recursive=False)
            if not rows:
                rows = table.find_all("tr")
            if rows and rows[0].find("th"):
                rows = rows[1:]

        for row in rows:
            if row.find_parent("table") != table and row.find_parent("tbody") is None:
                continue

            cells = row.find_all(["td", "th"], recursive=False)
            if len(cells) <= max(issue_col, desc_col or 0):
                continue

            raw_bug_id = cells[issue_col].get_text(strip=True)
            raw_description = (
                extract_cell_text_with_tables(cells[desc_col])
                if desc_col is not None
                else ""
            )

            # Extract bug ID and fix info
            bug_id, fix_info = extract_bug_id_and_fix_info(raw_bug_id)

            # Validate bug_id format
            if not re.match(r"^[A-Z]+-\d+$", bug_id):
                continue

            # Extract workaround
            description, workaround = extract_workaround(raw_description)

            # Extract fix info from description
            description, fix_info = extract_fix_info_from_description(description, fix_info)

            # Extract affected components from description
            description, affected_components = extract_affected_components(description)

            # Add feature as affected component if present
            if feature:
                if affected_components:
                    # Prepend feature to existing components
                    affected_components = [feature] + affected_components
                else:
                    affected_components = [feature]

            issues.append(
                Issue(
                    bug_id=bug_id,
                    description=description,
                    workaround=workaround,
                    fix_info=fix_info,
                    affected_components=affected_components,
                )
            )

        return issues

    async def discover_prisma_sdwan_versions(self) -> list[str]:
        """Discover available Prisma SD-WAN major versions.

        The version dropdown is JavaScript-rendered, so we probe for known
        version patterns by checking if the URLs exist.

        Returns:
            List of major version strings (e.g., ["6-5", "6-4", "6-3"]).
        """
        logger.debug("Discovering Prisma SD-WAN versions by probing URLs")

        # Known version patterns to check (newest first)
        # Prisma SD-WAN versions typically follow 6-x or 5-x patterns
        candidate_versions = [
            "6-5", "6-4", "6-3", "6-2", "6-1", "6-0",
            "5-6", "5-5", "5-4", "5-3", "5-2", "5-1", "5-0",
        ]

        valid_versions = []

        async def check_version(version: str) -> Optional[str]:
            """Check if a version URL exists."""
            url = (
                f"/prisma-sd-wan/release-notes/{version}"
                f"/prisma-sd-wan-ion-device-release-{version}"
            )
            try:
                soup = await self._fetch_page_with_semaphore(url)
                # Check if page has actual content (not a 404 or error page)
                title = soup.find("title")
                title_text = title.get_text().lower() if title else ""
                if "404" in title_text or "not found" in title_text or "error" in title_text:
                    return None
                # Check for a valid h1 header
                h1 = soup.find("h1")
                if h1 and "release" in h1.get_text().lower():
                    logger.debug("Found valid Prisma SD-WAN version: %s", version)
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
        logger.debug("Discovered %d Prisma SD-WAN versions: %s",
                     len(sorted_versions), sorted_versions)
        return sorted_versions

    async def crawl_prisma_sdwan(
        self,
        major_versions: Optional[list[str]] = None,
        skip_versions: Optional[set[str]] = None,
    ) -> Product:
        """Crawl Prisma SD-WAN release notes for one or more major versions.

        Args:
            major_versions: List of major versions to crawl (e.g., ["6-5", "6-4"]).
                           If None, discovers and crawls all available versions.
            skip_versions: Set of version strings to skip (e.g., {"6.5.0", "6.4.1"}).
                          Used for incremental fetching to avoid re-fetching existing versions.

        Returns:
            Product with all versions and issues.
        """
        skip_versions = skip_versions or set()

        # Discover versions if not specified
        if major_versions is None:
            self._log("Discovering available Prisma SD-WAN versions...")
            major_versions = await self.discover_prisma_sdwan_versions()
            self._log(f"Found versions: {', '.join(major_versions)}")

        all_product_versions = []

        for major_version in major_versions:
            version_str = major_version.replace("-", ".")
            self._log(f"Crawling Prisma SD-WAN {version_str}...")

            # Build URLs for this major version
            # URL patterns differ between versions:
            # - Newer (6-5): /known-issues-in-prisma-sd-wan-ion-release
            # - Older (6-4, etc.): /known-issues-in-prisma-sd-wan-ion-release-6-4.html
            base_path = (
                f"/prisma-sd-wan/release-notes/{major_version}"
                f"/prisma-sd-wan-ion-device-release-{major_version}"
            )

            # Try both URL patterns for each page type
            known_urls = [
                f"{base_path}/known-issues-in-prisma-sd-wan-ion-release",
                f"{base_path}/known-issues-in-prisma-sd-wan-ion-release-{major_version}.html",
            ]
            addressed_urls = [
                f"{base_path}/addressed-issues-in-prisma-sd-wan-ion-release",
                f"{base_path}/addressed-issues-in-prisma-sd-wan-ion-release-{major_version}.html",
            ]

            # Fetch pages, trying alternate URLs if primary fails
            fetch_tasks = [
                self._parse_prisma_sdwan_issues_page_with_fallback(
                    known_urls, "known", major_version
                ),
                self._parse_prisma_sdwan_issues_page_with_fallback(
                    addressed_urls, "addressed", major_version
                ),
            ]
            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            # Collect issues by version
            known_by_version: dict[str, list[Issue]] = {}
            addressed_by_version: dict[str, list[Issue]] = {}

            # Process known issues
            if not isinstance(results[0], Exception):
                for version, issues in results[0].items():
                    if version not in skip_versions:
                        known_by_version[version] = issues

            # Process addressed issues
            if not isinstance(results[1], Exception):
                for version, issues in results[1].items():
                    if version not in skip_versions:
                        addressed_by_version[version] = issues

            # Combine into ProductVersion objects
            all_versions_set = set(known_by_version.keys()) | set(addressed_by_version.keys())

            for ver in all_versions_set:
                known = self._deduplicate_issues(known_by_version.get(ver, []))
                addressed = self._deduplicate_issues(addressed_by_version.get(ver, []))

                if known or addressed:
                    all_product_versions.append(
                        ProductVersion(
                            version=ver,
                            known_issues=known,
                            addressed_issues=addressed,
                        )
                    )
                    self._log(
                        f"    {ver}: {len(known)} known, {len(addressed)} addressed"
                    )

        # Sort versions (newest first)
        all_product_versions.sort(
            key=lambda v: self._version_sort_key(v.version),
            reverse=True,
        )

        return Product(
            id="prisma-sdwan",
            name="Prisma SD-WAN",
            versions=all_product_versions,
        )

    async def _parse_prisma_sdwan_issues_page_with_fallback(
        self, urls: list[str], issue_type: str, major_version: str
    ) -> dict[str, list[Issue]]:
        """Try multiple URLs to parse Prisma SD-WAN issues page.

        Args:
            urls: List of URLs to try (in order).
            issue_type: Either "known" or "addressed".
            major_version: The major version being parsed (e.g., "6-5").

        Returns:
            Dict mapping version strings to lists of Issue objects.
        """
        for url in urls:
            result = await self._parse_prisma_sdwan_issues_page(
                url, issue_type, major_version
            )
            # If we got any results, return them
            if result:
                return result
        # No results from any URL
        return {}

    async def _parse_prisma_sdwan_issues_page(
        self, url: str, issue_type: str, major_version: str
    ) -> dict[str, list[Issue]]:
        """Parse a Prisma SD-WAN issues page.

        The page contains issue tables, potentially with version headers
        for different minor releases.

        Args:
            url: URL of the issues page.
            issue_type: Either "known" or "addressed".
            major_version: The major version being parsed (e.g., "6-5").

        Returns:
            Dict mapping version strings to lists of Issue objects.
        """
        results: dict[str, list[Issue]] = {}
        base_version = major_version.replace("-", ".")

        try:
            soup = await self._fetch_page_with_semaphore(url)

            # Track current version context
            current_version = base_version

            # Find all headers and tables
            for element in soup.find_all(["h2", "h3", "h4", "table"]):
                if element.name in ["h2", "h3", "h4"]:
                    header_text = element.get_text(strip=True)

                    # Check for version header (e.g., "6.5.1 Addressed Issues", "ION 6.5.0")
                    version_match = re.search(
                        r"(\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+)?)",
                        header_text,
                    )
                    if version_match:
                        current_version = version_match.group(1)
                        logger.debug("Found version header: %s", current_version)
                        continue

                elif element.name == "table":
                    # Skip nested tables
                    if element.find_parent("table"):
                        continue

                    # Parse issues from this table
                    issues = self._parse_issues_table(element)

                    if issues:
                        if current_version not in results:
                            results[current_version] = []
                        results[current_version].extend(issues)

        except Exception as e:
            logger.error("Error parsing Prisma SD-WAN page %s: %s", url, e)
            self._log(f"  Error parsing {url}: {e}")

        return results

    async def crawl_cloud_ngfw_azure(self) -> Product:
        """Crawl Cloud NGFW for Azure release notes.

        Cloud NGFW for Azure is a SaaS product with no version dropdown.
        All known and addressed issues are on single pages.

        Returns:
            Product with a single "SaaS" version containing all issues.
        """
        self._log("Crawling Cloud NGFW for Azure...")

        known_issues_url = (
            "/cloud-ngfw-azure/release-notes/cloud-ngfw-for-azure-known-issues"
        )
        addressed_issues_url = (
            "/cloud-ngfw-azure/release-notes/cloud-ngfw-for-azure-addressed-issues"
        )

        # Fetch both pages in parallel
        fetch_tasks = [
            self._fetch_page_with_semaphore(known_issues_url),
            self._fetch_page_with_semaphore(addressed_issues_url),
        ]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        known_issues: list[Issue] = []
        addressed_issues: list[Issue] = []

        # Parse known issues
        if not isinstance(results[0], Exception):
            soup = results[0]
            for table in soup.find_all("table"):
                # Skip nested tables
                if table.find_parent("table"):
                    continue
                issues = self._parse_issues_table(table)
                known_issues.extend(issues)
            self._log(f"  Found {len(known_issues)} known issues")
        else:
            self._log(f"  Error fetching known issues: {results[0]}")

        # Parse addressed issues
        if not isinstance(results[1], Exception):
            soup = results[1]
            for table in soup.find_all("table"):
                # Skip nested tables
                if table.find_parent("table"):
                    continue
                issues = self._parse_issues_table(table)
                addressed_issues.extend(issues)
            self._log(f"  Found {len(addressed_issues)} addressed issues")
        else:
            self._log(f"  Error fetching addressed issues: {results[1]}")

        # Deduplicate issues
        known_issues = self._deduplicate_issues(known_issues)
        addressed_issues = self._deduplicate_issues(addressed_issues)

        # Create a single version for SaaS product
        version = ProductVersion(
            version="SaaS",
            known_issues=known_issues,
            addressed_issues=addressed_issues,
        )

        return Product(
            id="cloud-ngfw-azure",
            name="Cloud NGFW for Azure",
            versions=[version] if known_issues or addressed_issues else [],
        )

    async def crawl_cloud_ngfw_aws(self) -> Product:
        """Crawl Cloud NGFW for AWS release notes.

        Cloud NGFW for AWS is a SaaS product with no version dropdown.
        It only has a known issues page (no addressed issues).

        Returns:
            Product with a single "SaaS" version containing known issues.
        """
        self._log("Crawling Cloud NGFW for AWS...")

        known_issues_url = (
            "/cloud-ngfw-aws/release-notes/cloud-ngfw-for-aws-known-issues"
        )

        known_issues: list[Issue] = []

        try:
            soup = await self._fetch_page_with_semaphore(known_issues_url)
            for table in soup.find_all("table"):
                # Skip nested tables
                if table.find_parent("table"):
                    continue
                issues = self._parse_issues_table(table)
                known_issues.extend(issues)
            self._log(f"  Found {len(known_issues)} known issues")
        except Exception as e:
            self._log(f"  Error fetching known issues: {e}")

        # Deduplicate issues
        known_issues = self._deduplicate_issues(known_issues)

        # Create a single version for SaaS product
        version = ProductVersion(
            version="SaaS",
            known_issues=known_issues,
            addressed_issues=[],
        )

        return Product(
            id="cloud-ngfw-aws",
            name="Cloud NGFW for AWS",
            versions=[version] if known_issues else [],
        )

    async def crawl_adem(self) -> Product:
        """Crawl Autonomous DEM (ADEM) release notes.

        ADEM issues are organized by agent version with release dates.
        The format includes headers like "Autonomous DEM Agent 5.9 Addressed Issues"
        followed by release dates and issue tables.

        Returns:
            Product with versions organized by agent version.
        """
        self._log("Crawling Autonomous DEM...")

        known_issues_url = (
            "/autonomous-dem/release-notes/ai-powered-adem-release-notes"
            "/release-updates-release-notes-doc/known-issues-adem"
        )
        addressed_issues_url = (
            "/autonomous-dem/release-notes/ai-powered-adem-release-notes"
            "/release-updates-release-notes-doc/addressed-issues-adem"
        )

        # Fetch both pages in parallel
        fetch_tasks = [
            self._fetch_page_with_semaphore(known_issues_url),
            self._fetch_page_with_semaphore(addressed_issues_url),
        ]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        # Parse known issues (simpler format - no release dates)
        known_by_version: dict[str, list[Issue]] = {}
        if not isinstance(results[0], Exception):
            known_by_version = self._parse_adem_issues_page(results[0], "known")
            total_known = sum(len(issues) for issues in known_by_version.values())
            self._log(f"  Found {total_known} known issues across {len(known_by_version)} versions")
        else:
            self._log(f"  Error fetching known issues: {results[0]}")

        # Parse addressed issues (with release dates)
        addressed_by_version: dict[str, list[Issue]] = {}
        if not isinstance(results[1], Exception):
            addressed_by_version = self._parse_adem_issues_page(results[1], "addressed")
            total_addressed = sum(len(issues) for issues in addressed_by_version.values())
            self._log(f"  Found {total_addressed} addressed issues across {len(addressed_by_version)} versions")
        else:
            self._log(f"  Error fetching addressed issues: {results[1]}")

        # Combine into ProductVersion objects
        all_versions_set = set(known_by_version.keys()) | set(addressed_by_version.keys())
        all_product_versions = []

        for ver in all_versions_set:
            known = self._deduplicate_issues(known_by_version.get(ver, []))
            addressed = self._deduplicate_issues(addressed_by_version.get(ver, []))

            if known or addressed:
                all_product_versions.append(
                    ProductVersion(
                        version=ver,
                        known_issues=known,
                        addressed_issues=addressed,
                    )
                )

        # Sort versions (newest first)
        all_product_versions.sort(
            key=lambda v: self._version_sort_key(v.version),
            reverse=True,
        )

        return Product(
            id="adem",
            name="Autonomous DEM",
            versions=all_product_versions,
        )

    def _parse_adem_issues_page(
        self, soup: BeautifulSoup, issue_type: str
    ) -> dict[str, list[Issue]]:
        """Parse an ADEM issues page organized by agent version.

        The page structure has headers like:
        - "Autonomous DEM Agent 5.9 Addressed Issues" or "Autonomous DEM Agent 5.9 Known Issues"
        - Under each, release dates like "March 2024" or specific dates
        - Then issue tables

        Args:
            soup: BeautifulSoup parsed page.
            issue_type: Either "known" or "addressed".

        Returns:
            Dict mapping version strings to lists of Issue objects.
        """
        results: dict[str, list[Issue]] = {}
        current_version = "Unknown"
        current_release_date: Optional[str] = None

        # Find all headers and tables
        for element in soup.find_all(["h2", "h3", "h4", "p", "table"]):
            if element.name in ["h2", "h3", "h4"]:
                header_text = element.get_text(strip=True)

                # Check for agent version header (e.g., "Autonomous DEM Agent 5.9 Addressed Issues")
                version_match = re.search(
                    r"(?:Autonomous\s+DEM\s+)?Agent\s+(\d+\.\d+)",
                    header_text,
                    re.IGNORECASE,
                )
                if version_match:
                    current_version = version_match.group(1)
                    current_release_date = None  # Reset for new version
                    logger.debug("Found ADEM version header: %s", current_version)
                    continue

                # Check for date header (e.g., "March 2024", "March 15, 2024")
                date_match = self._parse_adem_date(header_text)
                if date_match:
                    current_release_date = date_match
                    logger.debug("Found ADEM release date: %s", current_release_date)
                    continue

            elif element.name == "p":
                # Dates might also be in paragraph tags
                text = element.get_text(strip=True)
                date_match = self._parse_adem_date(text)
                if date_match:
                    current_release_date = date_match
                    continue

            elif element.name == "table":
                # Skip nested tables
                if element.find_parent("table"):
                    continue

                # Parse issues from this table
                issues = self._parse_issues_table(element)

                # Add release date to addressed issues
                if issue_type == "addressed" and current_release_date:
                    for issue in issues:
                        issue.release_date = current_release_date

                if issues:
                    if current_version not in results:
                        results[current_version] = []
                    results[current_version].extend(issues)

        return results

    def _parse_adem_date(self, text: str) -> Optional[str]:
        """Parse a date string from ADEM release notes.

        Handles formats like:
        - "March 2024" -> "2024-03-01"
        - "March 15, 2024" -> "2024-03-15"
        - "2024-03-15" -> "2024-03-15"

        Args:
            text: Text that may contain a date.

        Returns:
            Date in YYYY-MM-DD format, or None if not a date.
        """
        text = text.strip()

        # Month name to number mapping
        months = {
            "january": "01", "february": "02", "march": "03", "april": "04",
            "may": "05", "june": "06", "july": "07", "august": "08",
            "september": "09", "october": "10", "november": "11", "december": "12",
        }

        # Try "Month Day, Year" format (e.g., "March 15, 2024")
        match = re.match(
            r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$",
            text,
        )
        if match:
            month_name = match.group(1).lower()
            day = match.group(2).zfill(2)
            year = match.group(3)
            if month_name in months:
                return f"{year}-{months[month_name]}-{day}"

        # Try "Month Year" format (e.g., "March 2024")
        match = re.match(
            r"^([A-Za-z]+)\s+(\d{4})$",
            text,
        )
        if match:
            month_name = match.group(1).lower()
            year = match.group(2)
            if month_name in months:
                return f"{year}-{months[month_name]}-01"

        # Try ISO format (e.g., "2024-03-15")
        match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
        if match:
            return text

        return None

    async def crawl_scm(self) -> Product:
        """Crawl Strata Cloud Manager (SCM) release notes.

        SCM is a SaaS service with versioned releases like 2025.r5.0.
        Known issues are organized by component (Configuration Management, Command Center, etc.).
        Addressed issues include version numbers or dates.

        Returns:
            Product with versions and issues.
        """
        self._log("Crawling Strata Cloud Manager...")

        known_issues_url = "/strata-cloud-manager/release-notes/known-issues"
        addressed_issues_url = "/strata-cloud-manager/release-notes/addressed-issues"

        # Fetch both pages in parallel
        fetch_tasks = [
            self._fetch_page_with_semaphore(known_issues_url),
            self._fetch_page_with_semaphore(addressed_issues_url),
        ]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        # Parse known issues (organized by component)
        known_by_version: dict[str, list[Issue]] = {}
        if not isinstance(results[0], Exception):
            known_by_version = self._parse_scm_known_issues_page(results[0])
            total_known = sum(len(issues) for issues in known_by_version.values())
            self._log(f"  Found {total_known} known issues")
        else:
            self._log(f"  Error fetching known issues: {results[0]}")

        # Parse addressed issues (organized by version/date and component)
        addressed_by_version: dict[str, list[Issue]] = {}
        if not isinstance(results[1], Exception):
            addressed_by_version = self._parse_scm_addressed_issues_page(results[1])
            total_addressed = sum(len(issues) for issues in addressed_by_version.values())
            self._log(f"  Found {total_addressed} addressed issues")
        else:
            self._log(f"  Error fetching addressed issues: {results[1]}")

        # Combine into ProductVersion objects
        all_versions_set = set(known_by_version.keys()) | set(addressed_by_version.keys())
        all_product_versions = []

        for ver in all_versions_set:
            known = self._deduplicate_issues(known_by_version.get(ver, []))
            addressed = self._deduplicate_issues(addressed_by_version.get(ver, []))

            if known or addressed:
                all_product_versions.append(
                    ProductVersion(
                        version=ver,
                        known_issues=known,
                        addressed_issues=addressed,
                    )
                )

        # Sort versions (newest first) - SCM versions like 2025.r5.0
        all_product_versions.sort(
            key=lambda v: self._scm_version_sort_key(v.version),
            reverse=True,
        )

        return Product(
            id="scm",
            name="Strata Cloud Manager",
            versions=all_product_versions,
        )

    def _scm_version_sort_key(self, version: str) -> tuple:
        """Create a sort key for SCM version strings.

        Handles versions like:
        - "2025.r5.0" -> (2025, 5, 0)
        - "2024.r12.1" -> (2024, 12, 1)
        - "Unknown" -> (0, 0, 0)

        Args:
            version: Version string.

        Returns:
            Tuple for sorting.
        """
        if version == "Unknown":
            return (0, 0, 0)

        # Match SCM version pattern: YYYY.rN.M
        match = re.match(r"(\d{4})\.r(\d+)\.(\d+)", version)
        if match:
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

        return (0, 0, 0)

    def _parse_scm_known_issues_page(self, soup: BeautifulSoup) -> dict[str, list[Issue]]:
        """Parse SCM known issues page organized by component.

        The page has component headers like:
        - "Configuration Management Known Issues"
        - "Command Center Known Issues"

        Issues are associated with the component that precedes them.
        All known issues go into a single "SaaS" version bucket.

        Args:
            soup: BeautifulSoup parsed page.

        Returns:
            Dict mapping version strings to lists of Issue objects.
        """
        results: dict[str, list[Issue]] = {}
        current_component: Optional[str] = None

        # Component patterns to look for
        component_pattern = re.compile(
            r"^(.*?)\s*Known\s*Issues?$",
            re.IGNORECASE,
        )

        for element in soup.find_all(["h2", "h3", "h4", "table"]):
            if element.name in ["h2", "h3", "h4"]:
                header_text = element.get_text(strip=True)

                # Check for component header
                comp_match = component_pattern.match(header_text)
                if comp_match:
                    component_name = comp_match.group(1).strip()
                    if component_name:
                        current_component = component_name
                        logger.debug("Found SCM component: %s", current_component)
                    continue

            elif element.name == "table":
                # Skip nested tables
                if element.find_parent("table"):
                    continue

                # Parse issues from this table
                issues = self._parse_issues_table(element)

                # Add component to affected_components if we have one
                if current_component:
                    for issue in issues:
                        if issue.affected_components:
                            if current_component not in issue.affected_components:
                                issue.affected_components.append(current_component)
                        else:
                            issue.affected_components = [current_component]

                if issues:
                    # All known issues go into "SaaS" version
                    if "SaaS" not in results:
                        results["SaaS"] = []
                    results["SaaS"].extend(issues)

        return results

    def _parse_scm_addressed_issues_page(
        self, soup: BeautifulSoup
    ) -> dict[str, list[Issue]]:
        """Parse SCM addressed issues page organized by version and component.

        The page has two types of tables:
        1. Main table with empty headers and bug IDs concatenated with versions
           (e.g., "ADI-478552025.r5.0" = bug ID + version concatenated)
        2. Component-specific tables with "ID" and "Description" headers

        Args:
            soup: BeautifulSoup parsed page.

        Returns:
            Dict mapping version strings to lists of Issue objects.
        """
        results: dict[str, list[Issue]] = {}
        current_version = "Unknown"
        current_component: Optional[str] = None
        current_release_date: Optional[str] = None

        # Version pattern: YYYY.rN.M
        version_pattern = re.compile(r"(\d{4}\.r\d+\.\d+)")

        # Component patterns
        component_keywords = [
            "Configuration Management",
            "Command Center",
            "Insights",
            "Activity",
            "Health",
            "Incidents",
            "Policy",
            "Tenancy",
            "Identity",
            "Objects",
            "Workflows",
            "Network",
            "SASE",
        ]

        for element in soup.find_all(["h2", "h3", "h4", "p", "table"]):
            if element.name in ["h2", "h3", "h4"]:
                header_text = element.get_text(strip=True)

                # Check for version header (e.g., "2025.r5.0")
                version_match = version_pattern.search(header_text)
                if version_match:
                    current_version = version_match.group(1)
                    current_component = None  # Reset component for new version
                    current_release_date = None
                    logger.debug("Found SCM version: %s", current_version)
                    continue

                # Check for date header (e.g., "September 2024")
                date_match = self._parse_adem_date(header_text)
                if date_match:
                    # If we find a date without a version, use "Unknown" version
                    if current_version == "Unknown" or not version_pattern.search(header_text):
                        current_release_date = date_match
                        current_version = "Unknown"
                    logger.debug("Found SCM release date: %s", date_match)
                    continue

                # Check for component header
                for comp in component_keywords:
                    if comp.lower() in header_text.lower():
                        current_component = comp
                        logger.debug("Found SCM component: %s", current_component)
                        break

            elif element.name == "table":
                # Skip nested tables
                if element.find_parent("table"):
                    continue

                # Check if this is the main SCM table with empty headers
                # and concatenated bug ID/version format
                issues = self._parse_scm_main_addressed_table(element, results)

                # If not the main table format, try standard parsing
                if not issues:
                    issues = self._parse_issues_table(element)

                    # Add component to affected_components
                    if current_component:
                        for issue in issues:
                            if issue.affected_components:
                                if current_component not in issue.affected_components:
                                    issue.affected_components.append(current_component)
                            else:
                                issue.affected_components = [current_component]

                    # Add release date if available
                    if current_release_date:
                        for issue in issues:
                            issue.release_date = current_release_date

                    if issues:
                        if current_version not in results:
                            results[current_version] = []
                        results[current_version].extend(issues)

        return results

    def _parse_scm_main_addressed_table(
        self, table, results: dict[str, list[Issue]]
    ) -> bool:
        """Parse the main SCM addressed issues table with various bug ID formats.

        This table has:
        - Empty headers
        - First column: Bug ID in one of these formats:
          - Concatenated with version: "ADI-478552025.r5.0"
          - Concatenated with date: "ADI-38973September 2024"
          - Bug ID only: "ADI-23167"
        - Second column: Description

        Args:
            table: BeautifulSoup table element.
            results: Dict to add parsed issues to (modified in place).

        Returns:
            True if this table was the main SCM table and was processed,
            False otherwise (use standard parsing).
        """
        # Check for empty headers
        headers = []
        thead = table.find("thead")
        if thead:
            headers = [th.get_text(strip=True).lower() for th in thead.find_all("th")]
        else:
            first_row = table.find("tr")
            if first_row:
                headers = [th.get_text(strip=True).lower() for th in first_row.find_all("th")]

        # Only process tables with empty or no headers
        if headers and any(h.strip() for h in headers):
            return False

        # Get rows
        tbody = table.find("tbody")
        if tbody:
            rows = tbody.find_all("tr", recursive=False)
        else:
            rows = table.find_all("tr", recursive=False)
            if not rows:
                rows = table.find_all("tr")
            # Skip header row if present
            if rows and rows[0].find("th"):
                rows = rows[1:]

        # Patterns for different formats:
        # 1. Bug ID + version: "ADI-478552025.r5.0"
        version_pattern = re.compile(r"^([A-Z]+-\d+)(\d{4}\.r\d+\.\d+)$")
        # 2. Bug ID + date: "ADI-38973September 2024"
        date_pattern = re.compile(r"^([A-Z]+-\d+)([A-Z][a-z]+\s+\d{4})$")
        # 3. Bug ID only: "ADI-23167"
        bug_only_pattern = re.compile(r"^([A-Z]+-\d+)$")

        parsed_any = False
        for row in rows:
            cells = row.find_all(["td", "th"], recursive=False)
            if len(cells) < 2:
                continue

            raw_id = cells[0].get_text(strip=True)
            raw_description = extract_cell_text_with_tables(cells[1])

            bug_id = None
            version = "Unknown"
            release_date = None

            # Try to match each format
            match = version_pattern.match(raw_id)
            if match:
                bug_id = match.group(1)
                version = match.group(2)
            else:
                match = date_pattern.match(raw_id)
                if match:
                    bug_id = match.group(1)
                    date_str = match.group(2)
                    release_date = self._parse_adem_date(date_str)
                else:
                    match = bug_only_pattern.match(raw_id)
                    if match:
                        bug_id = match.group(1)

            if not bug_id:
                continue

            # Extract workaround from description
            description, workaround = extract_workaround(raw_description)

            # Extract fix info from description
            description, fix_info = extract_fix_info_from_description(description, None)

            # Extract affected components from description
            description, affected_components = extract_affected_components(description)

            logger.debug(
                "Parsed SCM main table issue: %s (version: %s, release_date: %s)",
                bug_id, version, release_date
            )

            issue = Issue(
                bug_id=bug_id,
                description=description,
                workaround=workaround,
                fix_info=fix_info,
                affected_components=affected_components,
                release_date=release_date,
            )

            if version not in results:
                results[version] = []
            results[version].append(issue)
            parsed_any = True

        return parsed_any


async def _crawl_cloud_ngfw_azure_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Async implementation of Cloud NGFW for Azure crawler.

    Note: major_versions and skip_versions are accepted for API compatibility
    but ignored since Cloud NGFW for Azure is a SaaS product without versions.
    """
    async with PaloAltoCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        product = await crawler.crawl_cloud_ngfw_azure()

        return BugDatabase(
            metadata=Metadata(
                generated_at=datetime.now(timezone.utc),
                version="1.0.0",
                source="Palo Alto Networks Cloud NGFW for Azure Release Notes",
            ),
            products=[product],
        )


async def _crawl_cloud_ngfw_aws_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Async implementation of Cloud NGFW for AWS crawler.

    Note: major_versions and skip_versions are accepted for API compatibility
    but ignored since Cloud NGFW for AWS is a SaaS product without versions.
    """
    async with PaloAltoCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        product = await crawler.crawl_cloud_ngfw_aws()

        return BugDatabase(
            metadata=Metadata(
                generated_at=datetime.now(timezone.utc),
                version="1.0.0",
                source="Palo Alto Networks Cloud NGFW for AWS Release Notes",
            ),
            products=[product],
        )


async def _crawl_adem_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Async implementation of Autonomous DEM crawler.

    Note: major_versions and skip_versions are accepted for API compatibility
    but currently ignored as ADEM versions are auto-discovered from page structure.
    """
    async with PaloAltoCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        product = await crawler.crawl_adem()

        return BugDatabase(
            metadata=Metadata(
                generated_at=datetime.now(timezone.utc),
                version="1.0.0",
                source="Palo Alto Networks Autonomous DEM Release Notes",
            ),
            products=[product],
        )


async def _crawl_scm_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Async implementation of Strata Cloud Manager crawler.

    Note: major_versions and skip_versions are accepted for API compatibility
    but currently ignored as SCM versions are auto-discovered from page structure.
    """
    async with PaloAltoCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        product = await crawler.crawl_scm()

        return BugDatabase(
            metadata=Metadata(
                generated_at=datetime.now(timezone.utc),
                version="1.0.0",
                source="Palo Alto Networks Strata Cloud Manager Release Notes",
            ),
            products=[product],
        )


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


async def _crawl_prisma_access_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Async implementation of Prisma Access crawler."""
    async with PaloAltoCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        product = await crawler.crawl_prisma_access(major_versions, skip_versions)

        # Build source description
        if major_versions:
            versions_str = ", ".join(v.replace("-", ".") for v in major_versions)
            source = f"Palo Alto Networks Prisma Access {versions_str} Release Notes"
        else:
            source = "Palo Alto Networks Prisma Access Release Notes (All Versions)"

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


async def _crawl_prisma_sdwan_async(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Async implementation of Prisma SD-WAN crawler."""
    async with PaloAltoCrawler(
        headless=headless, verbose=verbose, debug=debug, max_concurrency=max_concurrency
    ) as crawler:
        product = await crawler.crawl_prisma_sdwan(major_versions, skip_versions)

        # Build source description
        if major_versions:
            versions_str = ", ".join(v.replace("-", ".") for v in major_versions)
            source = f"Palo Alto Networks Prisma SD-WAN {versions_str} Release Notes"
        else:
            source = "Palo Alto Networks Prisma SD-WAN Release Notes (All Versions)"

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


def crawl_prisma_access(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Crawl Prisma Access release notes and return a BugDatabase.

    Args:
        major_versions: List of major versions to crawl (e.g., ["6-1", "5-2"]).
                       If None, discovers and crawls all available versions.
        headless: Whether to run browser in headless mode.
        verbose: Whether to print progress messages.
        debug: Whether to enable debug logging.
        max_concurrency: Maximum number of concurrent page fetches.
        skip_versions: Set of version strings to skip for incremental fetching.

    Returns:
        BugDatabase with Prisma Access issues.
    """
    return asyncio.run(
        _crawl_prisma_access_async(
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


def crawl_prisma_sdwan(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Crawl Prisma SD-WAN release notes and return a BugDatabase.

    Args:
        major_versions: List of major versions to crawl (e.g., ["6-5", "6-4"]).
                       If None, discovers and crawls all available versions.
        headless: Whether to run browser in headless mode.
        verbose: Whether to print progress messages.
        debug: Whether to enable debug logging.
        max_concurrency: Maximum number of concurrent page fetches.
        skip_versions: Set of version strings to skip for incremental fetching.

    Returns:
        BugDatabase with Prisma SD-WAN issues.
    """
    return asyncio.run(
        _crawl_prisma_sdwan_async(
            major_versions, headless, verbose, debug, max_concurrency, skip_versions
        )
    )


def crawl_cloud_ngfw_azure(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Crawl Cloud NGFW for Azure release notes and return a BugDatabase.

    Cloud NGFW for Azure is a SaaS product without version releases.
    All issues are on single known/addressed issues pages.

    Note: major_versions and skip_versions are accepted for API compatibility
    but ignored since this is a versionless SaaS product.

    Args:
        major_versions: Ignored (kept for API compatibility).
        headless: Whether to run browser in headless mode.
        verbose: Whether to print progress messages.
        debug: Whether to enable debug logging.
        max_concurrency: Maximum number of concurrent page fetches.
        skip_versions: Ignored (kept for API compatibility).

    Returns:
        BugDatabase with Cloud NGFW for Azure issues.
    """
    return asyncio.run(
        _crawl_cloud_ngfw_azure_async(
            major_versions, headless, verbose, debug, max_concurrency, skip_versions
        )
    )


def crawl_cloud_ngfw_aws(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Crawl Cloud NGFW for AWS release notes and return a BugDatabase.

    Cloud NGFW for AWS is a SaaS product without version releases.
    It only has a known issues page (no addressed issues).

    Note: major_versions and skip_versions are accepted for API compatibility
    but ignored since this is a versionless SaaS product.

    Args:
        major_versions: Ignored (kept for API compatibility).
        headless: Whether to run browser in headless mode.
        verbose: Whether to print progress messages.
        debug: Whether to enable debug logging.
        max_concurrency: Maximum number of concurrent page fetches.
        skip_versions: Ignored (kept for API compatibility).

    Returns:
        BugDatabase with Cloud NGFW for AWS issues.
    """
    return asyncio.run(
        _crawl_cloud_ngfw_aws_async(
            major_versions, headless, verbose, debug, max_concurrency, skip_versions
        )
    )


def crawl_adem(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Crawl Autonomous DEM release notes and return a BugDatabase.

    ADEM issues are organized by agent version with release dates for fixes.

    Note: major_versions and skip_versions are accepted for API compatibility
    but currently ignored as versions are auto-discovered from page structure.

    Args:
        major_versions: Ignored (kept for API compatibility).
        headless: Whether to run browser in headless mode.
        verbose: Whether to print progress messages.
        debug: Whether to enable debug logging.
        max_concurrency: Maximum number of concurrent page fetches.
        skip_versions: Ignored (kept for API compatibility).

    Returns:
        BugDatabase with Autonomous DEM issues.
    """
    return asyncio.run(
        _crawl_adem_async(
            major_versions, headless, verbose, debug, max_concurrency, skip_versions
        )
    )


def crawl_scm(
    major_versions: Optional[list[str]] = None,
    headless: bool = True,
    verbose: bool = False,
    debug: bool = False,
    max_concurrency: int = 3,
    skip_versions: Optional[set[str]] = None,
) -> BugDatabase:
    """Crawl Strata Cloud Manager release notes and return a BugDatabase.

    SCM issues are organized by component and version (e.g., 2025.r5.0).
    Older releases may only have dates instead of version numbers.

    Note: major_versions and skip_versions are accepted for API compatibility
    but currently ignored as versions are auto-discovered from page structure.

    Args:
        major_versions: Ignored (kept for API compatibility).
        headless: Whether to run browser in headless mode.
        verbose: Whether to print progress messages.
        debug: Whether to enable debug logging.
        max_concurrency: Maximum number of concurrent page fetches.
        skip_versions: Ignored (kept for API compatibility).

    Returns:
        BugDatabase with Strata Cloud Manager issues.
    """
    return asyncio.run(
        _crawl_scm_async(
            major_versions, headless, verbose, debug, max_concurrency, skip_versions
        )
    )

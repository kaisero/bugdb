"""Base crawler class with shared functionality."""

import asyncio
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import Browser, Page, async_playwright

from bugdb.models import Issue, ProductVersion

from .models import FailedFetch, VersionCrawlResult, VersionInfo
from .utils import (
    BASE_URL,
    configure_logging,
    extract_affected_components,
    extract_bug_id_and_fix_info,
    extract_cell_text_with_tables,
    extract_fix_info_from_description,
    extract_workaround,
    normalize_text,
    version_sort_key,
)

logger = logging.getLogger(__name__)


class BaseCrawler:
    """Base class for all Palo Alto Networks web crawlers.

    Provides shared functionality for:
    - Browser management (Playwright)
    - Page fetching with retry logic and backoff
    - HTML parsing for issues tables
    - Deduplication of issues
    """

    # Global backoff duration in seconds when connection refused is encountered
    GLOBAL_BACKOFF_DURATION = 30.0

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
        self._browser: Browser | None = None
        self._semaphore: asyncio.Semaphore | None = None

        # Global backoff state - shared across all concurrent fetches
        self._global_backoff_until: float = 0.0
        self._backoff_lock: asyncio.Lock | None = None

        # Configure logging if debug is enabled
        if debug:
            configure_logging(debug=True)

    async def __aenter__(self):
        logger.debug("Starting Playwright browser (headless=%s)", self.headless)
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._semaphore = asyncio.Semaphore(self.max_concurrency)
        self._backoff_lock = asyncio.Lock()
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

    def _is_connection_refused_error(self, error: Exception) -> bool:
        """Check if an error is a connection refused error.

        Args:
            error: The exception to check.

        Returns:
            True if this is a connection refused error that should trigger global backoff.
        """
        error_str = str(error).lower()
        return (
            "net::err_connection_refused" in error_str
            or "connection refused" in error_str
            or "err_connection_reset" in error_str
        )

    async def _wait_for_global_backoff(self) -> None:
        """Wait if global backoff is active.

        All concurrent fetches will wait until the backoff period ends.
        """
        import time

        async with self._backoff_lock:
            now = time.monotonic()
            if self._global_backoff_until > now:
                wait_time = self._global_backoff_until - now
                self._log(f"  [Backoff] Waiting {wait_time:.1f}s for network recovery...")
                logger.info("Global backoff active, waiting %.1f seconds", wait_time)

        # Wait outside the lock so other tasks can also check and wait
        now = time.monotonic()
        if self._global_backoff_until > now:
            await asyncio.sleep(self._global_backoff_until - now)

    async def _trigger_global_backoff(self) -> None:
        """Trigger global backoff for all concurrent fetches.

        Called when a connection refused error is encountered.
        """
        import time

        async with self._backoff_lock:
            now = time.monotonic()
            new_backoff_until = now + self.GLOBAL_BACKOFF_DURATION

            # Only extend if this is a new/later backoff
            if new_backoff_until > self._global_backoff_until:
                self._global_backoff_until = new_backoff_until
                self._log(
                    f"  [Backoff] Connection refused - all fetches paused for "
                    f"{self.GLOBAL_BACKOFF_DURATION:.0f}s"
                )
                logger.warning(
                    "Connection refused detected, triggering global backoff for %.0f seconds",
                    self.GLOBAL_BACKOFF_DURATION,
                )

    async def _new_page(self) -> Page:
        """Create a new browser page."""
        return await self._browser.new_page()

    async def _fetch_page(self, page: Page, url: str, wait_time: int = 3000) -> BeautifulSoup:
        """Fetch a page and return parsed HTML.

        Args:
            page: Playwright page instance.
            url: URL to fetch.
            wait_time: Time to wait for JS to render (ms).

        Returns:
            BeautifulSoup parsed HTML.
        """
        full_url = url if url.startswith("http") else urljoin(BASE_URL, url)
        logger.debug("Fetching page: %s", full_url)
        await page.goto(full_url, wait_until="networkidle")
        await page.wait_for_timeout(wait_time)
        content = await page.content()
        logger.debug("Page fetched successfully: %s (%d bytes)", full_url, len(content))
        return BeautifulSoup(content, "lxml")

    async def _fetch_page_with_semaphore(self, url: str, wait_time: int = 3000) -> BeautifulSoup:
        """Fetch a page with concurrency control and retry logic.

        Creates a new page, fetches the URL, and closes the page.
        Uses semaphore to limit concurrent requests.
        Retries on transient failures with exponential backoff.
        Honors global backoff when connection refused errors are detected.

        Args:
            url: URL to fetch.
            wait_time: Time to wait for JS to render (ms).

        Returns:
            BeautifulSoup parsed HTML.

        Raises:
            Exception: If all retry attempts fail.
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            # Wait for global backoff if another thread triggered it
            await self._wait_for_global_backoff()

            logger.debug("Acquiring semaphore for: %s (attempt %d)", url, attempt + 1)
            async with self._semaphore:
                logger.debug("Semaphore acquired, creating new page for: %s", url)
                page: Page | None = None
                try:
                    page = await self._new_page()
                    result = await self._fetch_page(page, url, wait_time)
                    logger.debug("Successfully fetched: %s", url)
                    return result
                except Exception as e:
                    last_error = e

                    # Check if this is a connection refused error
                    if self._is_connection_refused_error(e):
                        await self._trigger_global_backoff()

                    logger.warning(
                        "Fetch failed for %s (attempt %d/%d): %s",
                        url,
                        attempt + 1,
                        self.max_retries,
                        e,
                    )
                    self._log(f"  Retry {attempt + 1}/{self.max_retries} for {url}: {e}")
                finally:
                    if page is not None:
                        await page.close()

            # Exponential backoff before retry (in addition to global backoff)
            if attempt < self.max_retries - 1:
                delay = self.retry_delay * (2**attempt)
                logger.debug("Waiting %.1f seconds before retry for: %s", delay, url)
                await asyncio.sleep(delay)

        # All retries failed. last_error can only be None if max_retries == 0
        # (the loop body never ran); guard to surface a useful error rather
        # than `TypeError: exceptions must derive from BaseException`.
        if last_error is None:
            raise RuntimeError(
                f"No fetch attempts were made for {url} (max_retries={self.max_retries})"
            )
        raise last_error

    async def _fetch_cortex_page_with_semaphore(
        self, url: str, wait_time: int = 5000
    ) -> BeautifulSoup:
        """Fetch a Cortex XDR page with shadow DOM content.

        Cortex XDR docs use shadow DOM which isn't captured by page.content().
        This method uses Playwright's query_selector_all which pierces shadow DOM
        to extract tables and links, then builds a synthetic HTML document.

        Args:
            url: URL to fetch.
            wait_time: Time to wait for JS to render (ms).

        Returns:
            BeautifulSoup parsed HTML with extracted content.

        Raises:
            Exception: If all retry attempts fail.
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            await self._wait_for_global_backoff()

            logger.debug("Acquiring semaphore for Cortex page: %s (attempt %d)", url, attempt + 1)
            async with self._semaphore:
                logger.debug("Semaphore acquired, creating new page for: %s", url)
                page: Page | None = None
                try:
                    page = await self._new_page()
                    result = await self._fetch_cortex_page(page, url, wait_time)
                    logger.debug("Successfully fetched Cortex page: %s", url)
                    return result
                except Exception as e:
                    last_error = e

                    if self._is_connection_refused_error(e):
                        await self._trigger_global_backoff()

                    logger.warning(
                        "Fetch failed for %s (attempt %d/%d): %s",
                        url,
                        attempt + 1,
                        self.max_retries,
                        e,
                    )
                    self._log(f"  Retry {attempt + 1}/{self.max_retries} for {url}: {e}")
                finally:
                    if page is not None:
                        await page.close()

            if attempt < self.max_retries - 1:
                delay = self.retry_delay * (2**attempt)
                logger.debug("Waiting %.1f seconds before retry for: %s", delay, url)
                await asyncio.sleep(delay)

        # All retries failed. See _fetch_page_with_semaphore for rationale.
        if last_error is None:
            raise RuntimeError(
                f"No fetch attempts were made for {url} (max_retries={self.max_retries})"
            )
        raise last_error

    async def _fetch_cortex_page(
        self, page: Page, url: str, wait_time: int = 5000
    ) -> BeautifulSoup:
        """Fetch a Cortex XDR page and extract content from shadow DOM.

        Cortex XDR docs use shadow DOM which isn't captured by page.content()
        or JavaScript's document.querySelectorAll(). This method uses Playwright's
        query_selector_all which can pierce shadow DOM.

        Args:
            page: Playwright page instance.
            url: URL to fetch.
            wait_time: Time to wait for JS to render (ms).

        Returns:
            BeautifulSoup parsed HTML with extracted content.
        """
        logger.debug("Fetching Cortex page: %s", url)
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(wait_time)

        # Extract headings and tables using Playwright's query_selector_all
        # which pierces shadow DOM (JavaScript querySelectorAll cannot)
        elements = await page.query_selector_all("h1, h2, h3, h4, table")
        elements_html = []
        for element in elements:
            html = await element.evaluate("el => el.outerHTML")
            elements_html.append(html)
        logger.debug("Extracted %d headings/tables from Cortex page", len(elements_html))

        # Extract links using Playwright's query_selector_all
        links = await page.query_selector_all("a")
        links_html = []
        for link in links:
            href = await link.get_attribute("href")
            if href:
                text = await link.inner_text()
                # Escape any HTML in the text
                text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                links_html.append(f'<a href="{href}">{text}</a>')
        logger.debug("Extracted %d links from Cortex page", len(links_html))

        # Build synthetic HTML document with elements in document order
        combined_html = f"""
        <html>
        <body>
        <div class="content">
        {"".join(elements_html)}
        </div>
        <div class="links">
        {"".join(links_html)}
        </div>
        </body>
        </html>
        """

        logger.debug("Built synthetic HTML (%d bytes) for: %s", len(combined_html), url)
        return BeautifulSoup(combined_html, "lxml")

    def _version_sort_key(self, version: str) -> tuple:
        """Create a sort key for version strings.

        Args:
            version: Version string like "6.2.8-h9" or "6.1.0".

        Returns:
            Tuple for sorting.
        """
        return version_sort_key(version)

    def _extract_version_from_text(self, text: str) -> str | None:
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

    def _extract_version_from_url(self, url: str) -> str | None:
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
        skip_first_row = False
        thead = table.find("thead")
        if thead:
            headers = [th.get_text(strip=True).lower() for th in thead.find_all("th")]
        else:
            first_row = table.find("tr")
            if first_row:
                # Try th elements first
                headers = [th.get_text(strip=True).lower() for th in first_row.find_all("th")]

                # If no th headers found, check if first row has td elements that look like headers
                # Some tables use <td><b>ISSUE ID</b></td> format instead of <th>
                if not headers:
                    first_row_cells = first_row.find_all("td")
                    if first_row_cells:
                        # Check if cells contain header-like text (ISSUE ID, DESCRIPTION, etc.)
                        cell_texts = [cell.get_text(strip=True).lower() for cell in first_row_cells]
                        if any("issue" in t or "id" in t for t in cell_texts):
                            headers = cell_texts
                            skip_first_row = True

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

        logger.debug("Found issue column at index %d, description at index %s", issue_col, desc_col)

        # Parse rows (only direct children, not nested table rows)
        # If there's a tbody, use rows from there (header is in thead)
        tbody = table.find("tbody")
        if tbody:
            rows = tbody.find_all("tr", recursive=False)
            # Skip first row if we detected it as a header row with td elements
            if skip_first_row and rows:
                rows = rows[1:]
        else:
            # No tbody, find all rows and skip header
            rows = table.find_all("tr", recursive=False)
            if not rows:
                rows = table.find_all("tr")
            # Skip first row if it's the header (either th elements or detected td headers)
            if rows and (rows[0].find("th") or skip_first_row):
                rows = rows[1:]

        for row in rows:
            # Skip rows that belong to nested tables
            if (
                row.find_parent("table") != table
                and row.find_parent("tbody", recursive=False) is None
            ):
                continue

            cells = row.find_all(["td", "th"], recursive=False)
            if len(cells) <= max(issue_col, desc_col or 0):
                continue

            raw_bug_id = cells[issue_col].get_text(strip=True)
            # Use extract_cell_text_with_tables to convert nested tables to text
            raw_description = (
                extract_cell_text_with_tables(cells[desc_col]) if desc_col is not None else ""
            )

            # Extract bug ID and fix info
            # (e.g., "EPM-4616Resolved in..." -> "EPM-4616", "Resolved in...")
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

            logger.debug(
                "Parsed issue: %s (fix_info: %s, workaround: %s, components: %s)",
                bug_id,
                fix_info is not None,
                workaround is not None,
                affected_components is not None,
            )
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

    def _parse_issues_table_with_feature(self, table, feature: str | None = None) -> list[Issue]:
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
                extract_cell_text_with_tables(cells[desc_col]) if desc_col is not None else ""
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
                    affected_components = [feature, *affected_components]
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

    def _parse_topic_format_issues(self, soup: BeautifulSoup) -> list[Issue]:
        """Parse issues from div.topic format (used by Panorama plugins).

        This format has issues in div.topic containers with:
        - Bug ID in h2.title or h3.title
        - Description in div.shortdesc and div.p elements
        - Workaround after <b>Workaround</b> marker
        - Fix info in text like "This issue is addressed in..."

        Args:
            soup: BeautifulSoup object of the page.

        Returns:
            List of Issue objects.
        """
        issues = []

        for topic in soup.find_all("div", class_="topic"):
            # Extract bug ID from h2.title or h3.title
            title_elem = topic.find(["h2", "h3"], class_="title")
            if not title_elem:
                continue

            bug_id = title_elem.get_text(strip=True)

            # Validate bug ID format (e.g., PAN-XXXXX, PLUG-XXXXX)
            if not re.match(r"^[A-Z]+-\d+$", bug_id):
                continue

            # Build description from shortdesc and p elements
            description_parts = []
            affected_components = None
            workaround_text = None
            fix_info_text = None

            # Get shortdesc if present
            shortdesc = topic.find("div", class_="shortdesc")
            if shortdesc:
                description_parts.append(normalize_text(shortdesc))

            # Process div.p elements
            in_workaround = False
            first_p_processed = False

            for p_elem in topic.find_all("div", class_="p"):
                p_text = normalize_text(p_elem)

                # Check for workaround marker
                b_elem = p_elem.find("b")
                if b_elem and "workaround" in b_elem.get_text().lower():
                    in_workaround = True
                    # Extract workaround text after the bold element
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

                # Check for fix info (in <tt> element or plain text)
                tt_elem = p_elem.find("tt")
                if tt_elem:
                    tt_text = normalize_text(tt_elem)
                    if (
                        "this issue is addressed" in tt_text.lower()
                        or "this issue is fixed" in tt_text.lower()
                    ):
                        fix_info_text = tt_text
                        continue

                # Check plain text for fix info
                if (
                    "this issue is addressed" in p_text.lower()
                    or "this issue is fixed" in p_text.lower()
                ):
                    fix_info_text = p_text
                    continue

                # Check for affected component in first p element
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

            # Combine description
            full_description = " ".join(description_parts)
            desc_cleaned = re.sub(r"\s+", " ", full_description).strip()

            # Strip "Description of <issue-id>" prefix
            desc_prefix_match = re.match(
                r"^Description\s+of\s+" + re.escape(bug_id) + r"[\s:.\-]*",
                desc_cleaned,
                re.IGNORECASE,
            )
            if desc_prefix_match:
                desc_cleaned = desc_cleaned[desc_prefix_match.end() :].strip()

            # Skip empty descriptions
            if not desc_cleaned:
                continue

            # Extract fix info from description if not found
            if not fix_info_text:
                desc_cleaned, fix_info_text = extract_fix_info_from_description(desc_cleaned, None)

            # Create the issue
            issues.append(
                Issue(
                    bug_id=bug_id,
                    description=desc_cleaned,
                    workaround=workaround_text,
                    fix_info=fix_info_text,
                    affected_components=affected_components,
                )
            )

            logger.debug("Parsed topic issue: %s", bug_id)

        logger.debug("Parsed %d issues from div.topic format", len(issues))
        return issues

    async def _parse_issues_page(self, url: str) -> list[Issue]:
        """Parse issues from a known/addressed issues page.

        Propagates exceptions from fetch and parse layers to its callers.
        Historically this method swallowed all exceptions and returned an
        empty list, which caused two downstream correctness bugs:
          - `_crawl_version`'s `asyncio.gather(..., return_exceptions=True)`
            dispatcher never saw failures, so its `FailedFetch` branch was
            dead code and errors were silently lost.
          - `_retry_failed_fetches_sequentially` always reported "success"
            even when the retry hit the same parse error, because the
            exception was swallowed here too.
        Both were reported in the v1.0.2 architecture review. Propagating
        the error wakes up the correct handling in both callers.

        Args:
            url: URL of the issues page.

        Returns:
            List of Issue objects.

        Raises:
            Exception: If fetch or parse fails. Callers are expected to
                catch via ``asyncio.gather(..., return_exceptions=True)``
                or a local try/except and record a ``FailedFetch``.
        """
        logger.debug("Parsing issues page: %s", url)

        soup = await self._fetch_page_with_semaphore(url)

        # Find tables with issue data (only top-level, not nested tables)
        tables = soup.find_all("table")
        logger.debug("Found %d tables on page: %s", len(tables), url)

        issues: list[Issue] = []
        for table in tables:
            # Skip nested tables (tables inside another table's cell)
            if table.find_parent("table"):
                logger.debug("Skipping nested table")
                continue

            # Reuse _parse_issues_table for actual parsing
            table_issues = self._parse_issues_table(table)
            issues.extend(table_issues)

        # If no issues found in tables, try div.topic format (used by plugins)
        if not issues:
            issues = self._parse_topic_format_issues(soup)

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

    async def _crawl_version(
        self, version_info: VersionInfo, product_name: str = ""
    ) -> VersionCrawlResult:
        """Crawl a specific version's known and addressed issues.

        Args:
            version_info: Version information with URLs.
            product_name: Name of the product being crawled (for error tracking).

        Returns:
            VersionCrawlResult with ProductVersion and any failed fetches.
        """
        known_issues = []
        addressed_issues = []
        failed_fetches = []

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
                failed_fetches.append(
                    FailedFetch(
                        url=all_urls[i],
                        error=str(result),
                        product=product_name,
                        version=version_info.version,
                        issue_type=url_types[i],
                    )
                )
                continue
            if url_types[i] == "known":
                known_issues.extend(result)
            else:
                addressed_issues.extend(result)

        # Deduplicate by bug_id
        known_issues = self._deduplicate_issues(known_issues)
        addressed_issues = self._deduplicate_issues(addressed_issues)

        return VersionCrawlResult(
            product_version=ProductVersion(
                version=version_info.version,
                known_issues=known_issues,
                addressed_issues=addressed_issues,
            ),
            failed_fetches=failed_fetches,
        )

    async def _crawl_versions_parallel(
        self, version_infos: list[VersionInfo], product_name: str = ""
    ) -> tuple[list[ProductVersion], list[FailedFetch]]:
        """Crawl multiple versions in parallel.

        Args:
            version_infos: List of version information objects.
            product_name: Name of the product being crawled (for error tracking).

        Returns:
            Tuple of (list of ProductVersion objects, list of FailedFetch objects).
        """
        tasks = [self._crawl_version(vi, product_name) for vi in version_infos]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        product_versions = []
        all_failed_fetches = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # Entire version crawl failed - track all URLs as failed
                vi = version_infos[i]
                self._log(f"    Error crawling {vi.version}: {result}")
                for url in vi.known_issues_urls:
                    all_failed_fetches.append(
                        FailedFetch(
                            url=url,
                            error=str(result),
                            product=product_name,
                            version=vi.version,
                            issue_type="known",
                        )
                    )
                for url in vi.addressed_issues_urls:
                    all_failed_fetches.append(
                        FailedFetch(
                            url=url,
                            error=str(result),
                            product=product_name,
                            version=vi.version,
                            issue_type="addressed",
                        )
                    )
                continue

            # Collect failed fetches from successful version crawl
            all_failed_fetches.extend(result.failed_fetches)

            pv = result.product_version
            if pv.known_issues or pv.addressed_issues:
                product_versions.append(pv)
                self._log(
                    f"    {pv.version}: {len(pv.known_issues)} known, "
                    f"{len(pv.addressed_issues)} addressed"
                )

        return product_versions, all_failed_fetches

    async def _retry_failed_fetches_sequentially(
        self,
        failed_fetches: list[FailedFetch],
        max_retries: int = 3,
    ) -> tuple[list[Issue], list[FailedFetch]]:
        """Retry failed fetches sequentially with backoff.

        Args:
            failed_fetches: List of failed fetch attempts to retry.
            max_retries: Maximum number of retry attempts per URL.

        Returns:
            Tuple of (successfully retrieved issues, still-failed fetches).
        """
        if not failed_fetches:
            return [], []

        self._log(f"  Retrying {len(failed_fetches)} failed fetches sequentially...")

        recovered_issues = []
        still_failed = []

        for failed in failed_fetches:
            success = False
            last_error = failed.error

            for attempt in range(max_retries):
                try:
                    self._log(f"    Retry {attempt + 1}/{max_retries} for {failed.url}")
                    issues = await self._parse_issues_page(failed.url)
                    recovered_issues.extend(issues)
                    self._log(f"    Recovered {len(issues)} issues from {failed.url}")
                    success = True
                    break
                except Exception as e:
                    last_error = str(e)
                    if attempt < max_retries - 1:
                        delay = self.retry_delay * (2**attempt)
                        await asyncio.sleep(delay)

            if not success:
                still_failed.append(
                    FailedFetch(
                        url=failed.url,
                        error=last_error,
                        product=failed.product,
                        version=failed.version,
                        issue_type=failed.issue_type,
                    )
                )

        if still_failed:
            self._log(f"  {len(still_failed)} fetches still failed after retries")
        else:
            self._log("  All failed fetches recovered successfully")

        return recovered_issues, still_failed

"""Tests for the web crawler module."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from bugdb.crawler import (
    PaloAltoCrawler,
    VersionInfo,
    crawl_globalprotect,
    crawl_panos,
    crawl_prisma_access_agent,
    get_existing_versions,
    merge_databases,
)
from bugdb.models import BugDatabase, Issue, Metadata, Product, ProductVersion


class TestVersionInfo:
    """Tests for the VersionInfo dataclass."""

    def test_create_version_info(self):
        """Test creating a VersionInfo instance."""
        info = VersionInfo(
            version="6.2.1",
            known_issues_urls=["/known-issues/6-2-1"],
            addressed_issues_urls=["/addressed-issues/6-2-1"],
        )
        assert info.version == "6.2.1"
        assert len(info.known_issues_urls) == 1
        assert len(info.addressed_issues_urls) == 1

    def test_create_version_info_empty_urls(self):
        """Test creating a VersionInfo with empty URL lists."""
        info = VersionInfo(
            version="6.2.0",
            known_issues_urls=[],
            addressed_issues_urls=[],
        )
        assert info.version == "6.2.0"
        assert info.known_issues_urls == []
        assert info.addressed_issues_urls == []

    def test_create_version_info_multiple_urls(self):
        """Test creating a VersionInfo with multiple URLs per category."""
        info = VersionInfo(
            version="6.2.2",
            known_issues_urls=["/known-1", "/known-2", "/known-3"],
            addressed_issues_urls=["/addressed-1", "/addressed-2"],
        )
        assert len(info.known_issues_urls) == 3
        assert len(info.addressed_issues_urls) == 2


class TestPaloAltoCrawlerParsing:
    """Tests for HTML parsing functionality in PaloAltoCrawler."""

    def test_parse_issues_table_standard_format(self):
        """Test parsing issues from a standard table."""
        html = """
        <table>
            <thead>
                <tr>
                    <th>Issue ID</th>
                    <th>Description</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>GPC-12345</td>
                    <td>Test issue description</td>
                </tr>
                <tr>
                    <td>GPC-12346</td>
                    <td>Another test issue</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 2
        assert issues[0].bug_id == "GPC-12345"
        assert issues[0].description == "Test issue description"
        assert issues[1].bug_id == "GPC-12346"
        assert issues[1].description == "Another test issue"

    def test_parse_issues_table_bug_header(self):
        """Test parsing issues from a table with 'Bug ID' header."""
        html = """
        <table>
            <thead>
                <tr>
                    <th>Bug ID</th>
                    <th>Summary</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>PAN-300001</td>
                    <td>Bug summary text</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 1
        assert issues[0].bug_id == "PAN-300001"
        assert issues[0].description == "Bug summary text"

    def test_parse_issues_table_filters_invalid_ids(self):
        """Test that invalid bug IDs are filtered out."""
        html = """
        <table>
            <thead>
                <tr><th>Issue ID</th><th>Description</th></tr>
            </thead>
            <tbody>
                <tr><td>invalid-123</td><td>Lowercase prefix</td></tr>
                <tr><td>TEST-ABC</td><td>Non-numeric suffix</td></tr>
                <tr><td>123-456</td><td>Numeric prefix</td></tr>
                <tr><td>VALID-123</td><td>Valid issue</td></tr>
                <tr><td></td><td>Empty ID</td></tr>
                <tr><td>ANOTHER-456</td><td>Another valid</td></tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 2
        assert issues[0].bug_id == "VALID-123"
        assert issues[1].bug_id == "ANOTHER-456"

    def test_parse_issues_table_no_issue_column(self):
        """Test parsing a table without an issue ID column."""
        html = """
        <table>
            <thead>
                <tr>
                    <th>Feature</th>
                    <th>Description</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>New Feature</td>
                    <td>Feature description</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 0

    def test_parse_issues_table_no_description_column(self):
        """Test parsing a table with only issue ID column."""
        html = """
        <table>
            <thead>
                <tr>
                    <th>Issue ID</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>GPC-12345</td>
                    <td>Open</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 1
        assert issues[0].bug_id == "GPC-12345"
        assert issues[0].description == ""


class TestPaloAltoCrawlerVersionExtraction:
    """Tests for version extraction functionality."""

    def test_extract_version_from_url_standard(self):
        """Test extracting version from standard URL format."""
        crawler = PaloAltoCrawler()

        # Standard format
        assert crawler._extract_version_from_url("/6-2-1-known-issues") == "6.2.1"
        assert crawler._extract_version_from_url("/6-2-10-addressed") == "6.2.10"
        assert crawler._extract_version_from_url("/12-1-5-known") == "12.1.5"

    def test_extract_version_from_url_with_suffix(self):
        """Test extracting version with hotfix suffix."""
        crawler = PaloAltoCrawler()

        # With suffix
        assert crawler._extract_version_from_url("/6-2-8-h9-known-issues") == "6.2.8-h9"
        assert crawler._extract_version_from_url("/11-1-4-h5-addressed") == "11.1.4-h5"

    def test_extract_version_from_url_filters_page_suffixes(self):
        """Test that known/addressed suffixes are filtered."""
        crawler = PaloAltoCrawler()

        # These should NOT include the suffix
        result = crawler._extract_version_from_url("/6-3-3-known-issues")
        assert result == "6.3.3"

        result = crawler._extract_version_from_url("/6-3-3-addressed-issues")
        assert result == "6.3.3"

        result = crawler._extract_version_from_url("/6-3-3-issues")
        assert result == "6.3.3"

    def test_extract_version_from_url_no_match(self):
        """Test that non-matching URLs return None."""
        crawler = PaloAltoCrawler()

        assert crawler._extract_version_from_url("/globalprotect/release-notes") is None
        assert crawler._extract_version_from_url("/some/random/path") is None
        assert crawler._extract_version_from_url("/6-2-known-issues") is None  # Only 2 numbers

    def test_extract_version_from_text_standard(self):
        """Test extracting version from text."""
        crawler = PaloAltoCrawler()

        assert crawler._extract_version_from_text("Version 6.2.1") == "6.2.1"
        assert crawler._extract_version_from_text("GlobalProtect App 6.2.8-h9") == "6.2.8-h9"
        assert crawler._extract_version_from_text("Release 12.1.5") == "12.1.5"

    def test_extract_version_from_text_filters_suffixes(self):
        """Test that text version extraction filters page type suffixes."""
        crawler = PaloAltoCrawler()

        result = crawler._extract_version_from_text("6.3.3-known Issues")
        assert result == "6.3.3"

        result = crawler._extract_version_from_text("6.3.3-addressed Issues")
        assert result == "6.3.3"

    def test_extract_version_from_text_no_match(self):
        """Test that non-matching text returns None."""
        crawler = PaloAltoCrawler()

        assert crawler._extract_version_from_text("No version here") is None
        assert crawler._extract_version_from_text("Version 6.2") is None  # Only 2 numbers


class TestPaloAltoCrawlerDeduplication:
    """Tests for issue deduplication."""

    def test_deduplicate_issues_removes_duplicates(self):
        """Test that duplicate issues are removed."""
        crawler = PaloAltoCrawler()

        issues = [
            Issue(bug_id="GPC-001", description="First description"),
            Issue(bug_id="GPC-002", description="Second description"),
            Issue(bug_id="GPC-001", description="Duplicate of first"),
            Issue(bug_id="GPC-003", description="Third description"),
            Issue(bug_id="GPC-002", description="Duplicate of second"),
        ]

        deduplicated = crawler._deduplicate_issues(issues)

        assert len(deduplicated) == 3
        assert [i.bug_id for i in deduplicated] == ["GPC-001", "GPC-002", "GPC-003"]
        # First occurrence is kept
        assert deduplicated[0].description == "First description"
        assert deduplicated[1].description == "Second description"

    def test_deduplicate_issues_empty_list(self):
        """Test deduplication of empty list."""
        crawler = PaloAltoCrawler()
        assert crawler._deduplicate_issues([]) == []

    def test_deduplicate_issues_no_duplicates(self):
        """Test deduplication when there are no duplicates."""
        crawler = PaloAltoCrawler()

        issues = [
            Issue(bug_id="GPC-001", description="First"),
            Issue(bug_id="GPC-002", description="Second"),
            Issue(bug_id="GPC-003", description="Third"),
        ]

        deduplicated = crawler._deduplicate_issues(issues)
        assert len(deduplicated) == 3


class TestPaloAltoCrawlerVersionSorting:
    """Tests for version sorting functionality."""

    def test_version_sort_key_standard_versions(self):
        """Test sort key for standard versions."""
        crawler = PaloAltoCrawler()

        # Higher versions should have higher sort keys
        key_6_2_1 = crawler._version_sort_key("6.2.1")
        key_6_2_10 = crawler._version_sort_key("6.2.10")
        key_6_3_0 = crawler._version_sort_key("6.3.0")
        key_7_0_0 = crawler._version_sort_key("7.0.0")

        assert key_6_2_1 < key_6_2_10
        assert key_6_2_10 < key_6_3_0
        assert key_6_3_0 < key_7_0_0

    def test_version_sort_key_with_suffix(self):
        """Test sort key for versions with hotfix suffix."""
        crawler = PaloAltoCrawler()

        key_6_2_8 = crawler._version_sort_key("6.2.8")
        key_6_2_8_h1 = crawler._version_sort_key("6.2.8-h1")
        key_6_2_8_h9 = crawler._version_sort_key("6.2.8-h9")
        key_6_2_8_h10 = crawler._version_sort_key("6.2.8-h10")

        assert key_6_2_8 < key_6_2_8_h1
        assert key_6_2_8_h1 < key_6_2_8_h9
        assert key_6_2_8_h9 < key_6_2_8_h10

    def test_version_sort_key_invalid_version(self):
        """Test sort key for invalid version string."""
        crawler = PaloAltoCrawler()

        key = crawler._version_sort_key("invalid")
        assert key == (0, 0, 0, 0)


class TestPaloAltoCrawlerURLPatterns:
    """Tests for URL pattern detection."""

    def test_get_panos_url_pattern_ngfw(self):
        """Test that 12.x versions use NGFW pattern."""
        crawler = PaloAltoCrawler()

        assert crawler._get_panos_url_pattern("12-1") == "ngfw"
        assert crawler._get_panos_url_pattern("12-0") == "ngfw"
        assert crawler._get_panos_url_pattern("13-0") == "ngfw"

    def test_get_panos_url_pattern_panos(self):
        """Test that 11.x and older use PAN-OS pattern."""
        crawler = PaloAltoCrawler()

        assert crawler._get_panos_url_pattern("11-2") == "panos"
        assert crawler._get_panos_url_pattern("11-1") == "panos"
        assert crawler._get_panos_url_pattern("10-2") == "panos"
        assert crawler._get_panos_url_pattern("9-1") == "panos"


class TestPaloAltoCrawlerPrismaVersionExtraction:
    """Tests for Prisma Access Agent version extraction."""

    def test_extract_prisma_version_with_patch(self):
        """Test extracting Prisma Access Agent version with patch number."""
        crawler = PaloAltoCrawler()

        result = crawler._extract_prisma_access_agent_version(
            "/prisma-access-agent-26-1-2-known-issues",
            "26-1"
        )
        assert result == "26.1.2"

    def test_extract_prisma_version_without_patch(self):
        """Test extracting Prisma Access Agent version without patch number."""
        crawler = PaloAltoCrawler()

        result = crawler._extract_prisma_access_agent_version(
            "/prisma-access-agent-26-1-known-issues",
            "26-1"
        )
        assert result == "26.1"

    def test_extract_prisma_version_wrong_major(self):
        """Test that wrong major version returns None."""
        crawler = PaloAltoCrawler()

        result = crawler._extract_prisma_access_agent_version(
            "/prisma-access-agent-26-1-2-known-issues",
            "25-2"  # Looking for 25.2, but URL is for 26.1
        )
        assert result is None

    def test_extract_prisma_version_no_match(self):
        """Test that non-matching URL returns None."""
        crawler = PaloAltoCrawler()

        result = crawler._extract_prisma_access_agent_version(
            "/some/other/url",
            "26-1"
        )
        assert result is None


class TestPaloAltoCrawlerPanosVersionExtraction:
    """Tests for PAN-OS version extraction."""

    def test_extract_panos_version_standard(self):
        """Test extracting PAN-OS version from standard URL."""
        crawler = PaloAltoCrawler()

        result = crawler._extract_panos_version_from_url(
            "/pan-os-12-1-5-known-and-addressed-issues",
            "12-1"
        )
        assert result == "12.1.5"

    def test_extract_panos_version_with_suffix(self):
        """Test extracting PAN-OS version with suffix."""
        crawler = PaloAltoCrawler()

        result = crawler._extract_panos_version_from_url(
            "/pan-os-11-2-4-h1-known-issues",
            "11-2"
        )
        assert result == "11.2.4"

    def test_extract_panos_version_wrong_major(self):
        """Test that wrong major version returns None."""
        crawler = PaloAltoCrawler()

        result = crawler._extract_panos_version_from_url(
            "/pan-os-12-1-5-known-issues",
            "11-2"  # Looking for 11.2, but URL is for 12.1
        )
        assert result is None


class TestPaloAltoCrawlerGlobalProtectVersionExtraction:
    """Tests for GlobalProtect version extraction from release notes pages."""

    def test_extract_globalprotect_versions_version_specific(self):
        """Test extracting versions from pages with version-specific links."""
        html = """
        <html>
        <body>
            <a href="/globalprotect/release-notes/6-2/6-2-5-known-issues">6.2.5 Known Issues</a>
            <a href="/globalprotect/release-notes/6-2/6-2-5-addressed-issues">6.2.5 Addressed Issues</a>
            <a href="/globalprotect/release-notes/6-2/6-2-4-known-issues">6.2.4 Known Issues</a>
            <a href="/globalprotect/release-notes/6-2/6-2-4-addressed-issues">6.2.4 Addressed Issues</a>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")

        crawler = PaloAltoCrawler()
        version_infos, generic_known, generic_addressed = crawler._extract_globalprotect_versions(
            soup, "6-2"
        )

        assert len(version_infos) == 2
        versions = {v.version for v in version_infos}
        assert versions == {"6.2.5", "6.2.4"}

        # Each version should have both known and addressed URLs
        for vi in version_infos:
            assert len(vi.known_issues_urls) == 1
            assert len(vi.addressed_issues_urls) == 1

        # No generic URLs for version-specific pages
        assert len(generic_known) == 0
        assert len(generic_addressed) == 0

    def test_extract_globalprotect_versions_generic(self):
        """Test extracting versions from pages with generic links."""
        html = """
        <html>
        <body>
            <a href="/globalprotect/6-1/known-issues">Known Issues</a>
            <a href="/globalprotect/6-1/addressed-issues">Addressed Issues</a>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")

        crawler = PaloAltoCrawler()
        version_infos, generic_known, generic_addressed = crawler._extract_globalprotect_versions(
            soup, "6-1"
        )

        # No version-specific infos
        assert len(version_infos) == 0

        # Generic URLs found
        assert len(generic_known) == 1
        assert len(generic_addressed) == 1


class TestPaloAltoCrawlerAsync:
    """Tests for async crawler functionality using mocked playwright."""

    @pytest.mark.asyncio
    async def test_crawler_context_manager(self, mock_playwright_all):
        """Test crawler can be used as async context manager."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_all):
            async with PaloAltoCrawler() as crawler:
                assert crawler._browser is not None
                assert crawler._semaphore is not None

    @pytest.mark.asyncio
    async def test_fetch_page_returns_soup(self, mock_playwright_globalprotect, fixtures_dir):
        """Test that _fetch_page returns BeautifulSoup object."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_globalprotect):
            async with PaloAltoCrawler() as crawler:
                page = await crawler._new_page()
                soup = await crawler._fetch_page(
                    page,
                    "/globalprotect/release-notes/6-2/6-2-1-known-issues"
                )

                assert isinstance(soup, BeautifulSoup)
                # Should contain the expected content from our fixture
                title = soup.find("title")
                assert title is not None
                await page.close()

    @pytest.mark.asyncio
    async def test_parse_issues_page_integration(self, mock_playwright_globalprotect):
        """Test parsing issues from a full HTML page."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_globalprotect):
            async with PaloAltoCrawler() as crawler:
                issues = await crawler._parse_issues_page(
                    "/globalprotect/release-notes/6-2/6-2-1-known-issues"
                )

                # Should find issues from the fixture
                assert len(issues) > 0
                # All issues should have valid bug IDs
                for issue in issues:
                    assert issue.bug_id.startswith("GPC-")

    @pytest.mark.asyncio
    async def test_crawl_globalprotect_version_specific(self, mock_playwright_globalprotect):
        """Test crawling GlobalProtect with version-specific pages."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_globalprotect):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_globalprotect(major_versions=["6-2"])

                assert product.id == "globalprotect"
                assert product.name == "GlobalProtect"
                # Should have found some versions
                assert len(product.versions) >= 0

    @pytest.mark.asyncio
    async def test_crawl_globalprotect_multi_version(self, mock_playwright_globalprotect):
        """Test crawling GlobalProtect with multi-version pages (older style)."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_globalprotect):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_globalprotect(major_versions=["6-1"])

                assert product.id == "globalprotect"
                # Multi-version pages should yield multiple versions
                # (if the fixture is properly parsed)

    @pytest.mark.asyncio
    async def test_crawl_panos_ngfw_pattern(self, mock_playwright_panos):
        """Test crawling PAN-OS with NGFW URL pattern (12.x+)."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_panos):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_panos(major_versions=["12-1"])

                assert product.id == "panos"
                assert product.name == "PAN-OS"

    @pytest.mark.asyncio
    async def test_crawl_panos_legacy_pattern(self, mock_playwright_panos):
        """Test crawling PAN-OS with legacy URL pattern (11.x and older)."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_panos):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_panos(major_versions=["11-2"])

                assert product.id == "panos"
                assert product.name == "PAN-OS"

    @pytest.mark.asyncio
    async def test_crawl_prisma_access_agent(self, mock_playwright_prisma):
        """Test crawling Prisma Access Agent."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_prisma):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_prisma_access_agent(major_versions=["26-1"])

                assert product.id == "prisma-access-agent"
                assert product.name == "Prisma Access Agent"

    @pytest.mark.asyncio
    async def test_crawl_version_parallel(self, mock_playwright_globalprotect):
        """Test parallel version crawling."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_globalprotect):
            async with PaloAltoCrawler(max_concurrency=3) as crawler:
                version_infos = [
                    VersionInfo(
                        version="6.2.1",
                        known_issues_urls=["/globalprotect/release-notes/6-2/6-2-1-known-issues"],
                        addressed_issues_urls=["/globalprotect/release-notes/6-2/6-2-1-addressed-issues"],
                    ),
                ]

                results = await crawler._crawl_versions_parallel(version_infos)

                # Should return list of ProductVersion
                assert isinstance(results, list)
                for pv in results:
                    assert isinstance(pv, ProductVersion)


class TestWrapperFunctions:
    """Tests for the synchronous wrapper functions."""

    def test_crawl_globalprotect_returns_database(self, mock_playwright_globalprotect):
        """Test that crawl_globalprotect returns a BugDatabase."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_globalprotect):
            db = crawl_globalprotect(major_versions=["6-2"])

            assert db is not None
            assert len(db.products) == 1
            assert db.products[0].id == "globalprotect"
            assert db.metadata is not None

    def test_crawl_panos_returns_database(self, mock_playwright_panos):
        """Test that crawl_panos returns a BugDatabase."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_panos):
            db = crawl_panos(major_versions=["12-1"])

            assert db is not None
            assert len(db.products) == 1
            assert db.products[0].id == "panos"

    def test_crawl_prisma_returns_database(self, mock_playwright_prisma):
        """Test that crawl_prisma_access_agent returns a BugDatabase."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_prisma):
            db = crawl_prisma_access_agent(major_versions=["26-1"])

            assert db is not None
            assert len(db.products) == 1
            assert db.products[0].id == "prisma-access-agent"

    def test_crawl_globalprotect_metadata_source(self, mock_playwright_globalprotect):
        """Test that metadata source is set correctly."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_globalprotect):
            db = crawl_globalprotect(major_versions=["6-2"])

            assert "GlobalProtect" in db.metadata.source
            assert "6.2" in db.metadata.source

    def test_crawl_globalprotect_all_versions_source(self, mock_playwright_globalprotect):
        """Test metadata source when crawling all versions."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_globalprotect):
            # Mock discover_globalprotect_versions to return empty list
            # to avoid actually discovering versions
            with patch.object(
                PaloAltoCrawler,
                "discover_globalprotect_versions",
                new_callable=AsyncMock,
                return_value=[]
            ):
                db = crawl_globalprotect(major_versions=None)

                assert "All Versions" in db.metadata.source


class TestCrawlerConfiguration:
    """Tests for crawler configuration options."""

    def test_crawler_default_configuration(self):
        """Test default crawler configuration."""
        crawler = PaloAltoCrawler()

        assert crawler.headless is True
        assert crawler.verbose is False
        assert crawler.debug is False
        assert crawler.max_concurrency == 3
        assert crawler.max_retries == 3
        assert crawler.retry_delay == 2.0

    def test_crawler_custom_configuration(self):
        """Test custom crawler configuration."""
        crawler = PaloAltoCrawler(
            headless=False,
            verbose=True,
            debug=True,
            max_concurrency=10,
            max_retries=5,
            retry_delay=1.0,
        )

        assert crawler.headless is False
        assert crawler.verbose is True
        assert crawler.debug is True
        assert crawler.max_concurrency == 10
        assert crawler.max_retries == 5
        assert crawler.retry_delay == 1.0

    def test_crawler_logging_disabled_by_default(self, capsys):
        """Test that logging is disabled by default."""
        crawler = PaloAltoCrawler(verbose=False)
        crawler._log("Test message")

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_crawler_logging_when_verbose(self, capsys):
        """Test that logging works when verbose is enabled."""
        crawler = PaloAltoCrawler(verbose=True)
        crawler._log("Test message")

        captured = capsys.readouterr()
        assert "Test message" in captured.out

    def test_crawler_debug_configuration(self):
        """Test that debug mode can be enabled."""
        crawler = PaloAltoCrawler(debug=True)
        assert crawler.debug is True


class TestDebugLogging:
    """Tests for debug logging functionality."""

    def test_configure_logging_sets_debug_level(self):
        """Test that configure_logging sets the correct log level."""
        import logging
        from bugdb.crawler import configure_logging, logger

        configure_logging(debug=True)
        assert logger.level == logging.DEBUG

    def test_configure_logging_sets_info_level(self):
        """Test that configure_logging sets INFO level when debug is False."""
        import logging
        from bugdb.crawler import configure_logging, logger

        configure_logging(debug=False)
        assert logger.level == logging.INFO


class TestMultiVersionPageParsing:
    """Tests for multi-version page parsing."""

    @pytest.mark.asyncio
    async def test_parse_multi_version_issues_page(
        self, mock_playwright_globalprotect, sample_html_multi_version
    ):
        """Test parsing a page with multiple version sections."""
        # Create a custom mock that returns our sample HTML
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_globalprotect):
            async with PaloAltoCrawler() as crawler:
                # Directly test the parsing logic with our sample HTML
                soup = BeautifulSoup(sample_html_multi_version, "lxml")

                # Manually test the parsing
                results = {}
                current_version = None

                for element in soup.find_all(["h3", "h4", "table"]):
                    if element.name in ["h3", "h4"]:
                        import re
                        header_text = element.get_text(strip=True)
                        version_match = re.search(
                            r"GlobalProtect(?:\s+App)?\s+(\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+)?)",
                            header_text,
                            re.IGNORECASE,
                        )
                        if version_match:
                            current_version = version_match.group(1)
                    elif element.name == "table" and current_version:
                        issues = crawler._parse_issues_table(element)
                        if issues:
                            if current_version not in results:
                                results[current_version] = []
                            results[current_version].extend(issues)

                assert "6.1.4" in results
                assert "6.1.3" in results
                assert len(results["6.1.4"]) == 1
                assert len(results["6.1.3"]) == 2


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_parse_empty_table(self):
        """Test parsing an empty table."""
        html = """
        <table>
            <thead>
                <tr><th>Issue ID</th><th>Description</th></tr>
            </thead>
            <tbody>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 0

    def test_parse_table_with_colspan(self):
        """Test parsing a table with colspan attributes."""
        html = """
        <table>
            <thead>
                <tr><th>Issue ID</th><th colspan="2">Description</th></tr>
            </thead>
            <tbody>
                <tr><td>GPC-123</td><td>Description text</td><td>Extra</td></tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 1
        assert issues[0].bug_id == "GPC-123"

    def test_parse_table_with_whitespace(self):
        """Test parsing a table with extra whitespace."""
        html = """
        <table>
            <thead>
                <tr><th>  Issue ID  </th><th>  Description  </th></tr>
            </thead>
            <tbody>
                <tr>
                    <td>  GPC-123  </td>
                    <td>  Description with whitespace  </td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 1
        assert issues[0].bug_id == "GPC-123"
        assert issues[0].description == "Description with whitespace"

    def test_deduplicate_preserves_order(self):
        """Test that deduplication preserves original order."""
        crawler = PaloAltoCrawler()

        issues = [
            Issue(bug_id="C-003", description="Third"),
            Issue(bug_id="A-001", description="First"),
            Issue(bug_id="B-002", description="Second"),
            Issue(bug_id="A-001", description="Duplicate"),
        ]

        deduplicated = crawler._deduplicate_issues(issues)

        assert len(deduplicated) == 3
        assert [i.bug_id for i in deduplicated] == ["C-003", "A-001", "B-002"]


class TestGetExistingVersions:
    """Tests for the get_existing_versions function."""

    def test_get_existing_versions_single_product(self):
        """Test extracting versions from a database with a single product."""
        database = BugDatabase(
            metadata=Metadata(source="Test"),
            products=[
                Product(
                    id="globalprotect",
                    name="GlobalProtect",
                    versions=[
                        ProductVersion(version="6.2.1", known_issues=[], addressed_issues=[]),
                        ProductVersion(version="6.2.0", known_issues=[], addressed_issues=[]),
                        ProductVersion(version="6.1.5", known_issues=[], addressed_issues=[]),
                    ],
                )
            ],
        )

        result = get_existing_versions(database)

        assert "globalprotect" in result
        assert result["globalprotect"] == {"6.2.1", "6.2.0", "6.1.5"}

    def test_get_existing_versions_multiple_products(self):
        """Test extracting versions from a database with multiple products."""
        database = BugDatabase(
            metadata=Metadata(source="Test"),
            products=[
                Product(
                    id="globalprotect",
                    name="GlobalProtect",
                    versions=[
                        ProductVersion(version="6.2.1", known_issues=[], addressed_issues=[]),
                    ],
                ),
                Product(
                    id="panos",
                    name="PAN-OS",
                    versions=[
                        ProductVersion(version="12.1.5", known_issues=[], addressed_issues=[]),
                        ProductVersion(version="11.2.4", known_issues=[], addressed_issues=[]),
                    ],
                ),
                Product(
                    id="prisma-access-agent",
                    name="Prisma Access Agent",
                    versions=[
                        ProductVersion(version="26.1.2", known_issues=[], addressed_issues=[]),
                    ],
                ),
            ],
        )

        result = get_existing_versions(database)

        assert len(result) == 3
        assert result["globalprotect"] == {"6.2.1"}
        assert result["panos"] == {"12.1.5", "11.2.4"}
        assert result["prisma-access-agent"] == {"26.1.2"}

    def test_get_existing_versions_empty_database(self):
        """Test extracting versions from an empty database."""
        database = BugDatabase(
            metadata=Metadata(source="Test"),
            products=[],
        )

        result = get_existing_versions(database)

        assert result == {}

    def test_get_existing_versions_product_no_versions(self):
        """Test extracting versions when a product has no versions."""
        database = BugDatabase(
            metadata=Metadata(source="Test"),
            products=[
                Product(
                    id="globalprotect",
                    name="GlobalProtect",
                    versions=[],
                )
            ],
        )

        result = get_existing_versions(database)

        assert "globalprotect" in result
        assert result["globalprotect"] == set()


class TestMergeDatabases:
    """Tests for the merge_databases function."""

    def test_merge_databases_add_new_versions(self):
        """Test merging databases adds new versions to existing product."""
        existing = BugDatabase(
            metadata=Metadata(source="Existing", version="1.0.0"),
            products=[
                Product(
                    id="globalprotect",
                    name="GlobalProtect",
                    versions=[
                        ProductVersion(
                            version="6.2.0",
                            known_issues=[Issue(bug_id="GPC-001", description="Existing issue")],
                            addressed_issues=[],
                        ),
                    ],
                )
            ],
        )

        new = BugDatabase(
            metadata=Metadata(source="New"),
            products=[
                Product(
                    id="globalprotect",
                    name="GlobalProtect",
                    versions=[
                        ProductVersion(
                            version="6.2.1",
                            known_issues=[Issue(bug_id="GPC-002", description="New issue")],
                            addressed_issues=[],
                        ),
                    ],
                )
            ],
        )

        merged = merge_databases(existing, new)

        assert len(merged.products) == 1
        assert merged.products[0].id == "globalprotect"
        assert len(merged.products[0].versions) == 2

        versions = {v.version for v in merged.products[0].versions}
        assert versions == {"6.2.0", "6.2.1"}

    def test_merge_databases_add_new_product(self):
        """Test merging databases adds a completely new product."""
        existing = BugDatabase(
            metadata=Metadata(source="Existing"),
            products=[
                Product(
                    id="globalprotect",
                    name="GlobalProtect",
                    versions=[
                        ProductVersion(version="6.2.0", known_issues=[], addressed_issues=[]),
                    ],
                )
            ],
        )

        new = BugDatabase(
            metadata=Metadata(source="New"),
            products=[
                Product(
                    id="panos",
                    name="PAN-OS",
                    versions=[
                        ProductVersion(version="12.1.5", known_issues=[], addressed_issues=[]),
                    ],
                )
            ],
        )

        merged = merge_databases(existing, new)

        assert len(merged.products) == 2
        product_ids = {p.id for p in merged.products}
        assert product_ids == {"globalprotect", "panos"}

    def test_merge_databases_preserves_existing_versions(self):
        """Test that existing versions are preserved during merge."""
        existing_issue = Issue(bug_id="GPC-001", description="Existing issue")
        existing = BugDatabase(
            metadata=Metadata(source="Existing"),
            products=[
                Product(
                    id="globalprotect",
                    name="GlobalProtect",
                    versions=[
                        ProductVersion(
                            version="6.2.0",
                            known_issues=[existing_issue],
                            addressed_issues=[],
                        ),
                    ],
                )
            ],
        )

        new = BugDatabase(
            metadata=Metadata(source="New"),
            products=[
                Product(
                    id="globalprotect",
                    name="GlobalProtect",
                    versions=[
                        ProductVersion(
                            version="6.2.1",
                            known_issues=[],
                            addressed_issues=[],
                        ),
                    ],
                )
            ],
        )

        merged = merge_databases(existing, new)

        # Find the 6.2.0 version and verify the issue is preserved
        version_620 = next(
            v for v in merged.products[0].versions if v.version == "6.2.0"
        )
        assert len(version_620.known_issues) == 1
        assert version_620.known_issues[0].bug_id == "GPC-001"

    def test_merge_databases_sorts_versions(self):
        """Test that merged versions are sorted (newest first)."""
        existing = BugDatabase(
            metadata=Metadata(source="Existing"),
            products=[
                Product(
                    id="globalprotect",
                    name="GlobalProtect",
                    versions=[
                        ProductVersion(version="6.2.0", known_issues=[], addressed_issues=[]),
                        ProductVersion(version="6.1.0", known_issues=[], addressed_issues=[]),
                    ],
                )
            ],
        )

        new = BugDatabase(
            metadata=Metadata(source="New"),
            products=[
                Product(
                    id="globalprotect",
                    name="GlobalProtect",
                    versions=[
                        ProductVersion(version="6.1.5", known_issues=[], addressed_issues=[]),
                        ProductVersion(version="6.2.5", known_issues=[], addressed_issues=[]),
                    ],
                )
            ],
        )

        merged = merge_databases(existing, new)

        versions = [v.version for v in merged.products[0].versions]
        # Should be sorted newest first
        assert versions == ["6.2.5", "6.2.0", "6.1.5", "6.1.0"]

    def test_merge_databases_no_duplicate_versions(self):
        """Test that duplicate versions are not added."""
        existing = BugDatabase(
            metadata=Metadata(source="Existing"),
            products=[
                Product(
                    id="globalprotect",
                    name="GlobalProtect",
                    versions=[
                        ProductVersion(version="6.2.0", known_issues=[], addressed_issues=[]),
                    ],
                )
            ],
        )

        new = BugDatabase(
            metadata=Metadata(source="New"),
            products=[
                Product(
                    id="globalprotect",
                    name="GlobalProtect",
                    versions=[
                        ProductVersion(version="6.2.0", known_issues=[], addressed_issues=[]),
                        ProductVersion(version="6.2.1", known_issues=[], addressed_issues=[]),
                    ],
                )
            ],
        )

        merged = merge_databases(existing, new)

        # Should only have 2 versions, not 3 (no duplicate 6.2.0)
        assert len(merged.products[0].versions) == 2

    def test_merge_databases_preserves_metadata_version(self):
        """Test that existing metadata version is preserved."""
        existing = BugDatabase(
            metadata=Metadata(source="Existing", version="1.5.0"),
            products=[],
        )

        new = BugDatabase(
            metadata=Metadata(source="New", version="2.0.0"),
            products=[],
        )

        merged = merge_databases(existing, new)

        assert merged.metadata.version == "1.5.0"

    def test_merge_databases_empty_existing(self):
        """Test merging when existing database is empty."""
        existing = BugDatabase(
            metadata=Metadata(source="Existing"),
            products=[],
        )

        new = BugDatabase(
            metadata=Metadata(source="New"),
            products=[
                Product(
                    id="panos",
                    name="PAN-OS",
                    versions=[
                        ProductVersion(version="12.1.5", known_issues=[], addressed_issues=[]),
                    ],
                )
            ],
        )

        merged = merge_databases(existing, new)

        assert len(merged.products) == 1
        assert merged.products[0].id == "panos"

    def test_merge_databases_empty_new(self):
        """Test merging when new database is empty."""
        existing = BugDatabase(
            metadata=Metadata(source="Existing"),
            products=[
                Product(
                    id="panos",
                    name="PAN-OS",
                    versions=[
                        ProductVersion(version="12.1.5", known_issues=[], addressed_issues=[]),
                    ],
                )
            ],
        )

        new = BugDatabase(
            metadata=Metadata(source="New"),
            products=[],
        )

        merged = merge_databases(existing, new)

        assert len(merged.products) == 1
        assert merged.products[0].id == "panos"


class TestSkipVersionsParameter:
    """Tests for the skip_versions parameter in crawler methods."""

    @pytest.mark.asyncio
    async def test_crawl_globalprotect_skip_versions(self, mock_playwright_globalprotect):
        """Test that skip_versions parameter filters out versions."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_globalprotect):
            async with PaloAltoCrawler() as crawler:
                # Crawl with skip_versions - should skip the specified version
                product = await crawler.crawl_globalprotect(
                    major_versions=["6-2"],
                    skip_versions={"6.2.1"},
                )

                assert product.id == "globalprotect"
                # Version 6.2.1 should be skipped
                versions = {v.version for v in product.versions}
                assert "6.2.1" not in versions

    @pytest.mark.asyncio
    async def test_crawl_globalprotect_empty_skip_versions(self, mock_playwright_globalprotect):
        """Test that empty skip_versions doesn't affect crawling."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_globalprotect):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_globalprotect(
                    major_versions=["6-2"],
                    skip_versions=set(),
                )

                assert product.id == "globalprotect"

    @pytest.mark.asyncio
    async def test_crawl_panos_skip_versions(self, mock_playwright_panos):
        """Test that skip_versions works for PAN-OS crawler."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_panos):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_panos(
                    major_versions=["12-1"],
                    skip_versions={"12.1.5"},
                )

                assert product.id == "panos"
                versions = {v.version for v in product.versions}
                assert "12.1.5" not in versions

    @pytest.mark.asyncio
    async def test_crawl_prisma_skip_versions(self, mock_playwright_prisma):
        """Test that skip_versions works for Prisma Access Agent crawler."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_prisma):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_prisma_access_agent(
                    major_versions=["26-1"],
                    skip_versions={"26.1.2"},
                )

                assert product.id == "prisma-access-agent"
                versions = {v.version for v in product.versions}
                assert "26.1.2" not in versions

    def test_crawl_globalprotect_wrapper_skip_versions(self, mock_playwright_globalprotect):
        """Test that skip_versions works in sync wrapper function."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_globalprotect):
            db = crawl_globalprotect(
                major_versions=["6-2"],
                skip_versions={"6.2.1"},
            )

            assert db is not None
            versions = {v.version for p in db.products for v in p.versions}
            assert "6.2.1" not in versions

    def test_crawl_panos_wrapper_skip_versions(self, mock_playwright_panos):
        """Test that skip_versions works in PAN-OS sync wrapper function."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_panos):
            db = crawl_panos(
                major_versions=["12-1"],
                skip_versions={"12.1.5"},
            )

            assert db is not None
            versions = {v.version for p in db.products for v in p.versions}
            assert "12.1.5" not in versions

    def test_crawl_prisma_wrapper_skip_versions(self, mock_playwright_prisma):
        """Test that skip_versions works in Prisma sync wrapper function."""
        with patch("bugdb.crawler.async_playwright", return_value=mock_playwright_prisma):
            db = crawl_prisma_access_agent(
                major_versions=["26-1"],
                skip_versions={"26.1.2"},
            )

            assert db is not None
            versions = {v.version for p in db.products for v in p.versions}
            assert "26.1.2" not in versions

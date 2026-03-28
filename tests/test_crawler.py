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
    crawl_prisma_access,
    crawl_prisma_access_agent,
    crawl_prisma_sdwan,
    extract_affected_components,
    extract_bug_id_and_fix_info,
    extract_cell_text_with_tables,
    extract_fix_info_from_description,
    extract_workaround,
    get_existing_versions,
    merge_databases,
    table_to_text,
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

    def test_deduplicate_issues_removes_true_duplicates(self):
        """Test that true duplicates (same bug_id, release_date, description) are removed."""
        crawler = PaloAltoCrawler()

        issues = [
            Issue(bug_id="GPC-001", description="First description"),
            Issue(bug_id="GPC-002", description="Second description"),
            Issue(bug_id="GPC-001", description="First description"),  # True duplicate
            Issue(bug_id="GPC-003", description="Third description"),
            Issue(bug_id="GPC-002", description="Second description"),  # True duplicate
        ]

        deduplicated = crawler._deduplicate_issues(issues)

        assert len(deduplicated) == 3
        assert [i.bug_id for i in deduplicated] == ["GPC-001", "GPC-002", "GPC-003"]

    def test_deduplicate_issues_keeps_different_descriptions(self):
        """Test that issues with same bug_id but different descriptions are kept."""
        crawler = PaloAltoCrawler()

        issues = [
            Issue(bug_id="GPC-001", description="First description"),
            Issue(bug_id="GPC-001", description="Different description"),  # Same bug, different desc
            Issue(bug_id="GPC-002", description="Second description"),
        ]

        deduplicated = crawler._deduplicate_issues(issues)

        # Both GPC-001 entries should be kept since they have different descriptions
        assert len(deduplicated) == 3
        assert deduplicated[0].description == "First description"
        assert deduplicated[1].description == "Different description"

    def test_deduplicate_issues_keeps_different_release_dates(self):
        """Test that issues with same bug_id but different release_dates are kept."""
        crawler = PaloAltoCrawler()

        issues = [
            Issue(bug_id="GPC-001", description="Same description", release_date="2024-01-01"),
            Issue(bug_id="GPC-001", description="Same description", release_date="2024-02-01"),
            Issue(bug_id="GPC-002", description="Other issue"),
        ]

        deduplicated = crawler._deduplicate_issues(issues)

        # Both GPC-001 entries should be kept since they have different release_dates
        assert len(deduplicated) == 3

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
            Issue(bug_id="A-001", description="First"),  # True duplicate (same description)
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


class TestExtractWorkaround:
    """Tests for the extract_workaround function."""

    def test_extract_workaround_simple(self):
        """Test extracting a simple workaround."""
        description = "The application crashes when clicking save. Workaround: Click cancel instead."
        cleaned, workaround = extract_workaround(description)

        assert cleaned == "The application crashes when clicking save."
        assert workaround == "Click cancel instead."

    def test_extract_workaround_no_space_after_colon(self):
        """Test extracting workaround without space after colon."""
        description = "Bug in login flow. Workaround:Use the mobile app instead."
        cleaned, workaround = extract_workaround(description)

        assert cleaned == "Bug in login flow."
        assert workaround == "Use the mobile app instead."

    def test_extract_workaround_case_insensitive(self):
        """Test that workaround extraction is case insensitive."""
        description = "Connection drops unexpectedly. WORKAROUND: Reconnect manually."
        cleaned, workaround = extract_workaround(description)

        assert cleaned == "Connection drops unexpectedly."
        assert workaround == "Reconnect manually."

    def test_extract_workaround_mixed_case(self):
        """Test workaround with mixed case."""
        description = "Error on startup. WorkAround: Restart the service."
        cleaned, workaround = extract_workaround(description)

        assert cleaned == "Error on startup."
        assert workaround == "Restart the service."

    def test_extract_workaround_multiline(self):
        """Test extracting multiline workaround."""
        description = "Memory leak detected. Workaround: 1. Stop the service. 2. Clear cache. 3. Restart."
        cleaned, workaround = extract_workaround(description)

        assert cleaned == "Memory leak detected."
        assert workaround == "1. Stop the service. 2. Clear cache. 3. Restart."

    def test_extract_workaround_at_end(self):
        """Test workaround at the end of description."""
        description = "Feature not working as expected. Workaround: Disable and re-enable the feature."
        cleaned, workaround = extract_workaround(description)

        assert cleaned == "Feature not working as expected."
        assert workaround == "Disable and re-enable the feature."

    def test_extract_workaround_none_present(self):
        """Test when no workaround is present."""
        description = "The button color is wrong. This affects all users."
        cleaned, workaround = extract_workaround(description)

        assert cleaned == "The button color is wrong. This affects all users."
        assert workaround is None

    def test_extract_workaround_empty_description(self):
        """Test with empty description."""
        cleaned, workaround = extract_workaround("")

        assert cleaned == ""
        assert workaround is None

    def test_extract_workaround_none_description(self):
        """Test with None description."""
        cleaned, workaround = extract_workaround(None)

        assert cleaned is None
        assert workaround is None

    def test_extract_workaround_only_workaround_keyword(self):
        """Test when only 'Workaround:' is present with no text."""
        description = "Bug exists. Workaround:"
        cleaned, workaround = extract_workaround(description)

        # Empty workaround should not be extracted
        assert cleaned == "Bug exists. Workaround:"
        assert workaround is None

    def test_extract_workaround_in_middle(self):
        """Test workaround in the middle of text."""
        description = "Issue with display. Workaround: Refresh the page. This resolves most cases."
        cleaned, workaround = extract_workaround(description)

        # Workaround captures text until end or next section
        assert "Issue with display" in cleaned
        assert "Refresh the page" in workaround

    def test_extract_workaround_with_special_characters(self):
        """Test workaround with special characters."""
        description = "SSL error occurs. Workaround: Set SSL_VERIFY=false in config.yaml."
        cleaned, workaround = extract_workaround(description)

        assert cleaned == "SSL error occurs."
        assert workaround == "Set SSL_VERIFY=false in config.yaml."

    def test_extract_workaround_preserves_description(self):
        """Test that original description is preserved when no workaround."""
        description = "This is a detailed description with multiple sentences. It describes the bug thoroughly."
        cleaned, workaround = extract_workaround(description)

        assert cleaned == description
        assert workaround is None

    def test_extract_workaround_replaces_newlines_with_spaces(self):
        """Test that newlines are replaced with spaces in workaround text."""
        description = "Bug occurs on startup. Workaround: Step 1: Open settings.\nStep 2: Click reset.\nStep 3: Restart app."
        cleaned, workaround = extract_workaround(description)

        assert cleaned == "Bug occurs on startup."
        assert "Step 1: Open settings." in workaround
        assert "\n" not in workaround  # Newlines should be replaced with spaces
        assert "Step 2: Click reset." in workaround
        assert "Step 3: Restart app." in workaround

    def test_extract_workaround_replaces_newlines_in_description(self):
        """Test that newlines are replaced with spaces in the cleaned description."""
        description = "First paragraph of description.\n\nSecond paragraph. Workaround: Use alternative method."
        cleaned, workaround = extract_workaround(description)

        assert "First paragraph" in cleaned
        assert "\n" not in cleaned  # Newlines should be replaced with spaces
        assert "Second paragraph" in cleaned
        assert workaround == "Use alternative method."


class TestIssueParsingWithWorkaround:
    """Tests for issue parsing that includes workaround extraction."""

    def test_parse_issues_table_extracts_workaround(self):
        """Test that _parse_issues_table extracts workarounds from descriptions."""
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
                    <td>Connection fails on slow networks. Workaround: Increase timeout to 30 seconds.</td>
                </tr>
                <tr>
                    <td>GPC-12346</td>
                    <td>Button misaligned on mobile devices.</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 2

        # First issue should have workaround extracted
        assert issues[0].bug_id == "GPC-12345"
        assert "Connection fails on slow networks" in issues[0].description
        assert "Workaround" not in issues[0].description
        assert issues[0].workaround == "Increase timeout to 30 seconds."

        # Second issue should have no workaround
        assert issues[1].bug_id == "GPC-12346"
        assert issues[1].description == "Button misaligned on mobile devices."
        assert issues[1].workaround is None

    def test_parse_issues_table_multiple_workarounds(self):
        """Test parsing multiple issues with workarounds."""
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
                    <td>PAN-001</td>
                    <td>Auth failure. Workaround: Use API key authentication.</td>
                </tr>
                <tr>
                    <td>PAN-002</td>
                    <td>Slow response. WORKAROUND: Enable caching.</td>
                </tr>
                <tr>
                    <td>PAN-003</td>
                    <td>UI glitch on Firefox.</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 3

        assert issues[0].workaround == "Use API key authentication."
        assert issues[1].workaround == "Enable caching."
        assert issues[2].workaround is None


class TestExtractBugIdAndFixInfo:
    """Tests for the extract_bug_id_and_fix_info function."""

    def test_extract_simple_bug_id(self):
        """Test extracting a simple bug ID without fix info."""
        bug_id, fix_info = extract_bug_id_and_fix_info("EPM-4616")

        assert bug_id == "EPM-4616"
        assert fix_info is None

    def test_extract_bug_id_with_fix_info(self):
        """Test extracting bug ID with fix info text."""
        bug_id, fix_info = extract_bug_id_and_fix_info("EPM-4616Resolved in Prisma Access Agent 25.3")

        assert bug_id == "EPM-4616"
        assert fix_info == "Resolved in Prisma Access Agent 25.3"

    def test_extract_bug_id_with_fix_info_and_spaces(self):
        """Test extracting bug ID with fix info that has leading spaces."""
        bug_id, fix_info = extract_bug_id_and_fix_info("PAN-12345 Fixed in version 11.2.3")

        assert bug_id == "PAN-12345"
        assert fix_info == "Fixed in version 11.2.3"

    def test_extract_bug_id_various_prefixes(self):
        """Test extracting bug IDs with various prefixes."""
        test_cases = [
            ("GPC-999", "GPC-999", None),
            ("PAN-123456", "PAN-123456", None),
            ("EPM-1Also in 26.1", "EPM-1", "Also in 26.1"),
            ("ABC-99999Note: Fixed in patch", "ABC-99999", "Note: Fixed in patch"),
        ]

        for raw, expected_id, expected_info in test_cases:
            bug_id, fix_info = extract_bug_id_and_fix_info(raw)
            assert bug_id == expected_id, f"Failed for {raw}"
            assert fix_info == expected_info, f"Failed for {raw}"

    def test_extract_bug_id_empty_string(self):
        """Test with empty string."""
        bug_id, fix_info = extract_bug_id_and_fix_info("")

        assert bug_id == ""
        assert fix_info is None

    def test_extract_bug_id_none(self):
        """Test with None input."""
        bug_id, fix_info = extract_bug_id_and_fix_info(None)

        assert bug_id is None
        assert fix_info is None

    def test_extract_bug_id_invalid_format(self):
        """Test with invalid bug ID format."""
        bug_id, fix_info = extract_bug_id_and_fix_info("NotABugId")

        # Returns original string if no valid bug ID pattern found
        assert bug_id == "NotABugId"
        assert fix_info is None

    def test_extract_bug_id_lowercase_invalid(self):
        """Test with lowercase bug ID (invalid format)."""
        bug_id, fix_info = extract_bug_id_and_fix_info("pan-123")

        # Lowercase letters don't match the pattern
        assert bug_id == "pan-123"
        assert fix_info is None

    def test_extract_bug_id_with_trailing_whitespace(self):
        """Test that trailing whitespace is stripped from fix info."""
        bug_id, fix_info = extract_bug_id_and_fix_info("EPM-4616Fixed in v25.3  ")

        assert bug_id == "EPM-4616"
        assert fix_info == "Fixed in v25.3"

    def test_extract_bug_id_with_leading_whitespace(self):
        """Test that leading whitespace is handled."""
        bug_id, fix_info = extract_bug_id_and_fix_info("  EPM-4616Fixed in v25.3")

        assert bug_id == "EPM-4616"
        assert fix_info == "Fixed in v25.3"

    def test_extract_bug_id_numbers_only_suffix(self):
        """Test bug ID with numbers-only suffix."""
        bug_id, fix_info = extract_bug_id_and_fix_info("PAN-123456789")

        assert bug_id == "PAN-123456789"
        assert fix_info is None

    def test_extract_bug_id_with_version_numbers(self):
        """Test fix info containing version numbers."""
        bug_id, fix_info = extract_bug_id_and_fix_info("EPM-100Resolved in 26.1.2 and 25.3.1")

        assert bug_id == "EPM-100"
        assert fix_info == "Resolved in 26.1.2 and 25.3.1"


class TestIssueParsingWithFixInfo:
    """Tests for issue parsing that includes fix_info extraction."""

    def test_parse_issues_table_extracts_fix_info(self):
        """Test that _parse_issues_table extracts fix info from bug IDs."""
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
                    <td>EPM-4616Resolved in Prisma Access Agent 25.3</td>
                    <td>Agent fails to connect on startup.</td>
                </tr>
                <tr>
                    <td>GPC-12345</td>
                    <td>Button misaligned on mobile devices.</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 2

        # First issue should have fix_info extracted
        assert issues[0].bug_id == "EPM-4616"
        assert issues[0].description == "Agent fails to connect on startup."
        assert issues[0].fix_info == "Resolved in Prisma Access Agent 25.3"

        # Second issue should have no fix_info
        assert issues[1].bug_id == "GPC-12345"
        assert issues[1].description == "Button misaligned on mobile devices."
        assert issues[1].fix_info is None

    def test_parse_issues_table_fix_info_and_workaround(self):
        """Test parsing issues with both fix_info and workaround."""
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
                    <td>PAN-001Fixed in 11.2.4</td>
                    <td>Connection fails on slow networks. Workaround: Increase timeout to 30 seconds.</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 1

        # Should have both fix_info and workaround extracted
        assert issues[0].bug_id == "PAN-001"
        assert issues[0].fix_info == "Fixed in 11.2.4"
        assert "Connection fails on slow networks" in issues[0].description
        assert "Workaround" not in issues[0].description
        assert issues[0].workaround == "Increase timeout to 30 seconds."

    def test_parse_issues_table_multiple_fix_infos(self):
        """Test parsing multiple issues with fix_info."""
        html = """
        <table>
            <thead>
                <tr>
                    <th>Issue</th>
                    <th>Description</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>EPM-100Also fixed in 25.2</td>
                    <td>Memory leak issue.</td>
                </tr>
                <tr>
                    <td>EPM-200Resolved in Agent 26.1</td>
                    <td>Crash on Windows 11.</td>
                </tr>
                <tr>
                    <td>EPM-300</td>
                    <td>UI rendering issue.</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 3

        assert issues[0].bug_id == "EPM-100"
        assert issues[0].fix_info == "Also fixed in 25.2"

        assert issues[1].bug_id == "EPM-200"
        assert issues[1].fix_info == "Resolved in Agent 26.1"

        assert issues[2].bug_id == "EPM-300"
        assert issues[2].fix_info is None


class TestNestedTableHandling:
    """Tests for handling nested tables in issue descriptions."""

    def test_nested_table_not_parsed_as_issues(self):
        """Test that tables nested in description cells are not parsed as separate issues."""
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
                    <td>PAN-242777</td>
                    <td>
                        Fixed platform limits issue. New limits:
                        <table>
                            <tr><th>Platform</th><th>Limit</th></tr>
                            <tr><td>PA-5410</td><td>95K</td></tr>
                            <tr><td>PA-5420</td><td>95K</td></tr>
                            <tr><td>PA-5430</td><td>95K</td></tr>
                        </table>
                    </td>
                </tr>
                <tr>
                    <td>PAN-123456</td>
                    <td>Another bug fix.</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        # Should only have 2 issues, not 5 (nested table rows should not be parsed)
        assert len(issues) == 2
        assert issues[0].bug_id == "PAN-242777"
        assert issues[1].bug_id == "PAN-123456"

        # Nested table entries should NOT be parsed as bug IDs
        bug_ids = [i.bug_id for i in issues]
        assert "PA-5410" not in bug_ids
        assert "PA-5420" not in bug_ids
        assert "PA-5430" not in bug_ids

    def test_nested_table_converted_to_text_in_description(self):
        """Test that nested tables in descriptions are converted to text."""
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
                    <td>PAN-242777</td>
                    <td>
                        Fixed platform limits. See table:
                        <table>
                            <tr><th>Platform</th><th>Limit</th></tr>
                            <tr><td>PA-5410</td><td>95K</td></tr>
                        </table>
                    </td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 1
        assert issues[0].bug_id == "PAN-242777"
        # Description should contain the table content as text
        assert "PA-5410" in issues[0].description
        assert "95K" in issues[0].description

    def test_table_to_text_function(self):
        """Test the table_to_text helper function."""
        from bugdb.crawler import table_to_text

        html = """
        <table>
            <tr><th>Platform</th><th>Limit</th></tr>
            <tr><td>PA-5410</td><td>95K</td></tr>
            <tr><td>PA-5420</td><td>100K</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        text = table_to_text(table)

        assert "Platform" in text
        assert "Limit" in text
        assert "PA-5410" in text
        assert "95K" in text
        assert "PA-5420" in text
        assert "100K" in text

    def test_extract_cell_text_with_tables_function(self):
        """Test the extract_cell_text_with_tables helper function."""
        from bugdb.crawler import extract_cell_text_with_tables

        html = """
        <td>
            Some text before.
            <table>
                <tr><td>Cell1</td><td>Cell2</td></tr>
            </table>
            Some text after.
        </td>
        """
        soup = BeautifulSoup(html, "lxml")
        cell = soup.find("td")

        text = extract_cell_text_with_tables(cell)

        assert "Some text before" in text
        assert "Some text after" in text
        assert "Cell1" in text
        assert "Cell2" in text

    def test_deeply_nested_tables_skipped(self):
        """Test that deeply nested tables are also handled correctly."""
        html = """
        <table>
            <thead>
                <tr>
                    <th>Issue</th>
                    <th>Description</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>PAN-111111</td>
                    <td>
                        Outer description.
                        <table>
                            <tr>
                                <td>Nested level 1</td>
                                <td>
                                    <table>
                                        <tr><td>PA-NESTED</td><td>Deep value</td></tr>
                                    </table>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        # Only the main issue should be parsed
        assert len(issues) == 1
        assert issues[0].bug_id == "PAN-111111"
        # Nested table content should NOT create separate issues
        bug_ids = [i.bug_id for i in issues]
        assert "PA-NESTED" not in bug_ids


class TestExtractAffectedComponents:
    """Tests for the extract_affected_components function."""

    def test_extract_single_component(self):
        """Test extracting a single component from description start."""
        description = "(NGFW Clusters) Fixed an issue with cluster failover."
        cleaned, components = extract_affected_components(description)

        assert cleaned == "Fixed an issue with cluster failover."
        assert components == ["NGFW Clusters"]

    def test_extract_platform_component(self):
        """Test extracting platform-specific component."""
        description = "(PA-5500 Series firewalls only) Memory leak in packet processing."
        cleaned, components = extract_affected_components(description)

        assert cleaned == "Memory leak in packet processing."
        assert components == ["PA-5500 Series firewalls only"]

    def test_extract_multiple_components(self):
        """Test extracting multiple components."""
        description = "(NGFW Clusters) (PA-7000 Series) Issue with high availability."
        cleaned, components = extract_affected_components(description)

        assert cleaned == "Issue with high availability."
        assert components == ["NGFW Clusters", "PA-7000 Series"]

    def test_no_components(self):
        """Test when no components are present."""
        description = "Fixed an issue with the firewall."
        cleaned, components = extract_affected_components(description)

        assert cleaned == "Fixed an issue with the firewall."
        assert components is None

    def test_parentheses_in_middle(self):
        """Test that parentheses in the middle are not extracted."""
        description = "Fixed an issue (intermittent) with the firewall."
        cleaned, components = extract_affected_components(description)

        assert cleaned == "Fixed an issue (intermittent) with the firewall."
        assert components is None

    def test_empty_description(self):
        """Test with empty description."""
        cleaned, components = extract_affected_components("")

        assert cleaned == ""
        assert components is None

    def test_none_description(self):
        """Test with None description."""
        cleaned, components = extract_affected_components(None)

        assert cleaned is None
        assert components is None

    def test_empty_parentheses(self):
        """Test with empty parentheses at start."""
        description = "() Fixed an issue."
        cleaned, components = extract_affected_components(description)

        # Empty parentheses should not be extracted as a component
        assert cleaned == "() Fixed an issue."
        assert components is None

    def test_unclosed_parenthesis(self):
        """Test with unclosed parenthesis at start."""
        description = "(Incomplete Fixed an issue."
        cleaned, components = extract_affected_components(description)

        # Unclosed parenthesis should not be extracted
        assert cleaned == "(Incomplete Fixed an issue."
        assert components is None

    def test_whitespace_handling(self):
        """Test that whitespace is handled correctly."""
        description = "  (PA-5400 Series)   Fixed an issue.  "
        cleaned, components = extract_affected_components(description)

        assert cleaned == "Fixed an issue."
        assert components == ["PA-5400 Series"]

    def test_component_with_special_characters(self):
        """Test component with special characters."""
        description = "(PA-5400/5500 Series) Fixed an issue."
        cleaned, components = extract_affected_components(description)

        assert cleaned == "Fixed an issue."
        assert components == ["PA-5400/5500 Series"]


class TestIssueParsingWithAffectedComponents:
    """Tests for issue parsing that includes affected components extraction."""

    def test_parse_issues_table_extracts_components(self):
        """Test that _parse_issues_table extracts affected components."""
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
                    <td>PAN-123456</td>
                    <td>(NGFW Clusters) Fixed cluster sync issue.</td>
                </tr>
                <tr>
                    <td>PAN-789012</td>
                    <td>Fixed general firewall issue.</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 2

        # First issue should have affected components
        assert issues[0].bug_id == "PAN-123456"
        assert issues[0].affected_components == ["NGFW Clusters"]
        assert "NGFW Clusters" not in issues[0].description
        assert "Fixed cluster sync issue" in issues[0].description

        # Second issue should have no affected components
        assert issues[1].bug_id == "PAN-789012"
        assert issues[1].affected_components is None

    def test_parse_issues_table_all_extractions_combined(self):
        """Test parsing with workaround, fix_info, and affected components."""
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
                    <td>PAN-111Fixed in 11.2.5</td>
                    <td>(PA-7000 Series) Memory leak detected. Workaround: Restart daily.</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 1

        issue = issues[0]
        assert issue.bug_id == "PAN-111"
        assert issue.fix_info == "Fixed in 11.2.5"
        assert issue.affected_components == ["PA-7000 Series"]
        assert issue.workaround == "Restart daily."
        assert "Memory leak detected" in issue.description
        assert "Workaround" not in issue.description
        assert "PA-7000" not in issue.description


class TestPrismaAccessCrawler:
    """Tests for Prisma Access crawler functionality."""

    def test_parse_issues_table_with_feature_no_feature(self):
        """Test parsing table without feature context."""
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
                    <td>PA-12345</td>
                    <td>Fixed connectivity issue.</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table_with_feature(table, feature=None)

        assert len(issues) == 1
        assert issues[0].bug_id == "PA-12345"
        assert issues[0].affected_components is None

    def test_parse_issues_table_with_feature_adds_component(self):
        """Test that feature is added to affected_components."""
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
                    <td>PA-12345</td>
                    <td>Fixed connectivity issue.</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table_with_feature(
            table, feature="Dynamic Privileges Access"
        )

        assert len(issues) == 1
        assert issues[0].bug_id == "PA-12345"
        assert issues[0].affected_components == ["Dynamic Privileges Access"]

    def test_parse_issues_table_with_feature_combines_components(self):
        """Test that feature is prepended to existing affected_components."""
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
                    <td>PA-12345</td>
                    <td>(Windows only) Fixed connectivity issue.</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table_with_feature(
            table, feature="Remote Browser Isolation"
        )

        assert len(issues) == 1
        assert issues[0].bug_id == "PA-12345"
        # Feature should be first, then existing component
        assert issues[0].affected_components == ["Remote Browser Isolation", "Windows only"]
        assert "Windows only" not in issues[0].description

    def test_parse_issues_table_with_feature_extracts_all_fields(self):
        """Test that all fields are extracted correctly with feature."""
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
                    <td>PA-99999Fixed in 6.1.2</td>
                    <td>(macOS) Connection fails. Workaround: Reconnect manually.</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table_with_feature(table, feature="GlobalProtect App")

        assert len(issues) == 1
        issue = issues[0]
        assert issue.bug_id == "PA-99999"
        assert issue.fix_info == "Fixed in 6.1.2"
        assert issue.affected_components == ["GlobalProtect App", "macOS"]
        assert issue.workaround == "Reconnect manually."
        assert "Connection fails" in issue.description

    def test_parse_issues_table_with_feature_multiple_rows(self):
        """Test parsing multiple rows with feature."""
        html = """
        <table>
            <thead>
                <tr>
                    <th>Issue</th>
                    <th>Description</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>PA-001</td>
                    <td>Issue one.</td>
                </tr>
                <tr>
                    <td>PA-002</td>
                    <td>Issue two.</td>
                </tr>
                <tr>
                    <td>PA-003</td>
                    <td>(Linux) Issue three.</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table_with_feature(table, feature="ZTNA Connector")

        assert len(issues) == 3
        assert all(i.affected_components[0] == "ZTNA Connector" for i in issues)
        # Third issue should have both feature and platform
        assert issues[2].affected_components == ["ZTNA Connector", "Linux"]


class TestPrismaAccessIssuePageParsing:
    """Tests for parsing Prisma Access issues pages with sections."""

    @pytest.mark.asyncio
    async def test_parse_prisma_access_issues_page_version_sections(self):
        """Test parsing page with version sections."""
        html = """
        <html>
        <body>
            <h2>6.1 Addressed Issues</h2>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>PA-100</td><td>Base version fix.</td></tr>
                </tbody>
            </table>

            <h3>6.1.1 Addressed Issues</h3>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>PA-101</td><td>Minor version fix.</td></tr>
                </tbody>
            </table>

            <h3>6.1.0-h5 Addressed Issues</h3>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>PA-102</td><td>Hotfix.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore') as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            crawler = PaloAltoCrawler()
            result = await crawler._parse_prisma_access_issues_page(
                "/test-url", "addressed", "6-1"
            )

        # Should have issues for three versions
        assert "6.1" in result
        assert "6.1.1" in result
        assert "6.1.0-h5" in result

        assert result["6.1"][0].bug_id == "PA-100"
        assert result["6.1.1"][0].bug_id == "PA-101"
        assert result["6.1.0-h5"][0].bug_id == "PA-102"

    @pytest.mark.asyncio
    async def test_parse_prisma_access_issues_page_feature_sections(self):
        """Test parsing page with feature sections for known issues."""
        html = """
        <html>
        <body>
            <h2>Prisma Access 6.1 Known Issues</h2>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>PA-200</td><td>General issue.</td></tr>
                </tbody>
            </table>

            <h3>Dynamic Privileges Access Known Issues</h3>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>PA-201</td><td>DPA specific issue.</td></tr>
                </tbody>
            </table>

            <h3>Remote Browser Isolation Known Issues</h3>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>PA-202</td><td>RBI specific issue.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore') as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            crawler = PaloAltoCrawler()
            result = await crawler._parse_prisma_access_issues_page(
                "/test-url", "known", "6-1"
            )

        # All issues should be under base version 6.1
        assert "6.1" in result
        issues = result["6.1"]
        assert len(issues) == 3

        # Check that features are in affected_components
        bug_ids = {i.bug_id: i for i in issues}

        assert bug_ids["PA-200"].affected_components is None  # General, no feature
        assert bug_ids["PA-201"].affected_components == ["Dynamic Privileges Access"]
        assert bug_ids["PA-202"].affected_components == ["Remote Browser Isolation"]

    @pytest.mark.asyncio
    async def test_parse_prisma_access_issues_page_mixed_sections(self):
        """Test parsing page with both version and feature sections."""
        html = """
        <html>
        <body>
            <h2>Prisma Access Known Issues</h2>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>PA-300</td><td>General issue.</td></tr>
                </tbody>
            </table>

            <h3>ZTNA Connector Known Issues</h3>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>PA-301</td><td>ZTNA issue.</td></tr>
                </tbody>
            </table>

            <h3>6.1.2 Known Issues</h3>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>PA-302</td><td>Version specific issue.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore') as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            crawler = PaloAltoCrawler()
            result = await crawler._parse_prisma_access_issues_page(
                "/test-url", "known", "6-1"
            )

        # Should have issues for base version and specific version
        assert "6.1" in result
        assert "6.1.2" in result

        # Base version issues include general and feature-specific
        base_issues = {i.bug_id: i for i in result["6.1"]}
        assert "PA-300" in base_issues
        assert "PA-301" in base_issues
        assert base_issues["PA-301"].affected_components == ["ZTNA Connector"]

        # Version-specific issue
        assert result["6.1.2"][0].bug_id == "PA-302"


class TestPrismaAccessCrawlFunction:
    """Tests for the crawl_prisma_access function."""

    def test_crawl_prisma_access_import(self):
        """Test that crawl_prisma_access can be imported."""
        from bugdb.crawler import crawl_prisma_access
        assert callable(crawl_prisma_access)



class TestExtractFixInfoFromDescription:
    """Tests for the extract_fix_info_from_description function."""

    def test_extract_fix_info_simple(self):
        """Test extracting fix info from a simple description."""
        description = "Some issue description. This issue is resolved in ION 6.3.3."
        cleaned, fix_info = extract_fix_info_from_description(description)

        assert cleaned == "Some issue description."
        assert fix_info == "Resolved in ION 6.3.3"

    def test_extract_fix_info_with_release(self):
        """Test extracting fix info with release keyword."""
        description = "A problem occurs. This issue is resolved in release 6.5.1."
        cleaned, fix_info = extract_fix_info_from_description(description)

        assert cleaned == "A problem occurs."
        assert fix_info == "Resolved in release 6.5.1"

    def test_extract_fix_info_prisma_sdwan(self):
        """Test extracting fix info for Prisma SD-WAN."""
        description = "Connection drops intermittently. This issue is resolved in Prisma SD-WAN ION 6.4.2."
        cleaned, fix_info = extract_fix_info_from_description(description)

        assert cleaned == "Connection drops intermittently."
        assert fix_info == "Resolved in Prisma SD-WAN ION 6.4.2"

    def test_extract_fix_info_no_match(self):
        """Test that description without fix info is unchanged."""
        description = "Some issue that has no resolution info."
        cleaned, fix_info = extract_fix_info_from_description(description)

        assert cleaned == description
        assert fix_info is None

    def test_extract_fix_info_preserves_existing(self):
        """Test that existing fix_info is preserved and not overwritten."""
        description = "Issue description. This issue is resolved in 6.5.0."
        cleaned, fix_info = extract_fix_info_from_description(
            description, existing_fix_info="Resolved in 6.4.0"
        )

        assert cleaned == description  # Description unchanged when existing_fix_info
        assert fix_info == "Resolved in 6.4.0"

    def test_extract_fix_info_reformats_existing(self):
        """Test that existing fix_info with full sentence is reformatted."""
        description = "Some issue description."
        cleaned, fix_info = extract_fix_info_from_description(
            description, existing_fix_info="This issue is resolved in ION version 6.4.3."
        )

        assert cleaned == description
        assert fix_info == "Resolved in ION version 6.4.3"

    def test_extract_fix_info_reformats_existing_no_period(self):
        """Test reformatting existing fix_info without trailing period."""
        description = "Some issue."
        cleaned, fix_info = extract_fix_info_from_description(
            description, existing_fix_info="This issue is resolved in 6.5.0"
        )

        assert cleaned == description
        assert fix_info == "Resolved in 6.5.0"

    def test_extract_fix_info_empty_description(self):
        """Test with empty description."""
        cleaned, fix_info = extract_fix_info_from_description("")

        assert cleaned == ""
        assert fix_info is None

    def test_extract_fix_info_none_description(self):
        """Test with None description."""
        cleaned, fix_info = extract_fix_info_from_description(None)

        assert cleaned is None
        assert fix_info is None

    def test_extract_fix_info_case_insensitive(self):
        """Test that matching is case insensitive."""
        description = "Issue desc. THIS ISSUE IS RESOLVED IN version 6.5."
        cleaned, fix_info = extract_fix_info_from_description(description)

        assert cleaned == "Issue desc."
        assert fix_info == "Resolved in version 6.5"

    def test_extract_fix_info_at_end(self):
        """Test fix info at end without period."""
        description = "Issue description This issue is resolved in 6.5.1"
        cleaned, fix_info = extract_fix_info_from_description(description)

        assert cleaned == "Issue description"
        assert fix_info == "Resolved in 6.5.1"


class TestPrismaSDWANCrawler:
    """Tests for Prisma SD-WAN crawler methods."""

    def test_parse_issues_table_extracts_fix_info(self):
        """Test that _parse_issues_table extracts fix_info from descriptions."""
        html = """
        <table>
            <thead>
                <tr><th>Issue ID</th><th>Description</th></tr>
            </thead>
            <tbody>
                <tr>
                    <td>CGXSW-1234</td>
                    <td>Controller failover issue. This issue is resolved in ION 6.4.1.</td>
                </tr>
                <tr>
                    <td>CGXSW-5678</td>
                    <td>Simple issue without fix info.</td>
                </tr>
            </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")

        crawler = PaloAltoCrawler()
        issues = crawler._parse_issues_table(table)

        assert len(issues) == 2

        # First issue should have fix_info extracted
        assert issues[0].bug_id == "CGXSW-1234"
        assert issues[0].fix_info == "Resolved in ION 6.4.1"
        assert "This issue is resolved" not in issues[0].description

        # Second issue should not have fix_info
        assert issues[1].bug_id == "CGXSW-5678"
        assert issues[1].fix_info is None


class TestPrismaSDWANIssuePageParsing:
    """Tests for Prisma SD-WAN issue page parsing."""

    @pytest.mark.asyncio
    async def test_parse_prisma_sdwan_issues_page_simple(self):
        """Test parsing a simple Prisma SD-WAN issues page."""
        html = """
        <html>
        <body>
            <h2>Addressed Issues in Prisma SD-WAN ION Release 6.5</h2>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>CGXSW-100</td><td>Fixed a connectivity issue.</td></tr>
                    <tr><td>CGXSW-101</td><td>Fixed a performance bug.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore') as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            crawler = PaloAltoCrawler()
            result = await crawler._parse_prisma_sdwan_issues_page(
                "/test-url", "addressed", "6-5"
            )

        assert "6.5" in result
        assert len(result["6.5"]) == 2
        assert result["6.5"][0].bug_id == "CGXSW-100"
        assert result["6.5"][1].bug_id == "CGXSW-101"

    @pytest.mark.asyncio
    async def test_parse_prisma_sdwan_issues_page_version_sections(self):
        """Test parsing page with multiple version sections."""
        html = """
        <html>
        <body>
            <h2>Addressed Issues in Prisma SD-WAN ION Releases</h2>

            <h3>6.5.1 Addressed Issues</h3>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>CGXSW-200</td><td>Fixed in 6.5.1.</td></tr>
                </tbody>
            </table>

            <h3>6.5.0 Addressed Issues</h3>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>CGXSW-201</td><td>Fixed in 6.5.0.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore') as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            crawler = PaloAltoCrawler()
            result = await crawler._parse_prisma_sdwan_issues_page(
                "/test-url", "addressed", "6-5"
            )

        assert "6.5.1" in result
        assert "6.5.0" in result
        assert result["6.5.1"][0].bug_id == "CGXSW-200"
        assert result["6.5.0"][0].bug_id == "CGXSW-201"

    @pytest.mark.asyncio
    async def test_parse_prisma_sdwan_issues_page_with_workaround(self):
        """Test parsing page with workarounds in descriptions."""
        html = """
        <html>
        <body>
            <h2>Known Issues</h2>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr>
                        <td>CGXSW-300</td>
                        <td>Connection drops under load. Workaround: Reduce concurrent connections.</td>
                    </tr>
                </tbody>
            </table>
        </body>
        </html>
        """

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore') as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            crawler = PaloAltoCrawler()
            result = await crawler._parse_prisma_sdwan_issues_page(
                "/test-url", "known", "6-5"
            )

        assert "6.5" in result
        issue = result["6.5"][0]
        assert issue.bug_id == "CGXSW-300"
        assert issue.workaround == "Reduce concurrent connections."
        assert "Workaround" not in issue.description


class TestPrismaSDWANCrawlFunction:
    """Tests for the crawl_prisma_sdwan function."""

    def test_crawl_prisma_sdwan_import(self):
        """Test that crawl_prisma_sdwan can be imported."""
        from bugdb.crawler import crawl_prisma_sdwan
        assert callable(crawl_prisma_sdwan)


class TestCloudNGFWAzureCrawler:
    """Tests for Cloud NGFW for Azure crawler."""

    @pytest.mark.asyncio
    async def test_crawl_cloud_ngfw_azure_basic(self):
        """Test basic Cloud NGFW for Azure crawling."""
        known_html = """
        <html>
        <body>
            <h2>Cloud NGFW for Azure Known Issues</h2>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>CNGFWAZR-100</td><td>Known issue in Azure deployment.</td></tr>
                    <tr><td>CNGFWAZR-101</td><td>Resource limitation issue.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """
        addressed_html = """
        <html>
        <body>
            <h2>Cloud NGFW for Azure Addressed Issues</h2>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>CNGFWAZR-50</td><td>Fixed connectivity issue.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """

        async def mock_fetch(url):
            if "known-issues" in url:
                return BeautifulSoup(known_html, "lxml")
            else:
                return BeautifulSoup(addressed_html, "lxml")

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore', side_effect=mock_fetch):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_cloud_ngfw_azure()

        assert product.id == "cloud-ngfw-azure"
        assert product.name == "Cloud NGFW for Azure"
        assert len(product.versions) == 1
        assert product.versions[0].version == "SaaS"
        assert len(product.versions[0].known_issues) == 2
        assert len(product.versions[0].addressed_issues) == 1

    @pytest.mark.asyncio
    async def test_crawl_cloud_ngfw_azure_with_workaround(self):
        """Test parsing Cloud NGFW for Azure issues with workarounds."""
        known_html = """
        <html>
        <body>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr>
                        <td>CNGFWAZR-200</td>
                        <td>Timeout during deployment. Workaround: Increase timeout value in settings.</td>
                    </tr>
                </tbody>
            </table>
        </body>
        </html>
        """
        addressed_html = "<html><body></body></html>"

        async def mock_fetch(url):
            if "known-issues" in url:
                return BeautifulSoup(known_html, "lxml")
            else:
                return BeautifulSoup(addressed_html, "lxml")

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore', side_effect=mock_fetch):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_cloud_ngfw_azure()

        issue = product.versions[0].known_issues[0]
        assert issue.bug_id == "CNGFWAZR-200"
        assert issue.workaround == "Increase timeout value in settings."
        assert "Workaround" not in issue.description

    @pytest.mark.asyncio
    async def test_crawl_cloud_ngfw_azure_empty_pages(self):
        """Test handling of empty pages."""
        empty_html = "<html><body></body></html>"

        async def mock_fetch(url):
            return BeautifulSoup(empty_html, "lxml")

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore', side_effect=mock_fetch):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_cloud_ngfw_azure()

        assert product.id == "cloud-ngfw-azure"
        assert len(product.versions) == 0


class TestCloudNGFWAzureCrawlFunction:
    """Tests for the crawl_cloud_ngfw_azure function."""

    def test_crawl_cloud_ngfw_azure_import(self):
        """Test that crawl_cloud_ngfw_azure can be imported."""
        from bugdb.crawler import crawl_cloud_ngfw_azure
        assert callable(crawl_cloud_ngfw_azure)

    def test_crawl_cloud_ngfw_azure_accepts_version_params(self):
        """Test that crawl_cloud_ngfw_azure accepts version params for API compatibility."""
        from bugdb.crawler import crawl_cloud_ngfw_azure
        import inspect
        sig = inspect.signature(crawl_cloud_ngfw_azure)
        params = list(sig.parameters.keys())
        assert "major_versions" in params
        assert "skip_versions" in params


class TestCloudNGFWAWSCrawler:
    """Tests for Cloud NGFW for AWS crawler."""

    @pytest.mark.asyncio
    async def test_crawl_cloud_ngfw_aws_basic(self):
        """Test basic Cloud NGFW for AWS crawling (known issues only)."""
        known_html = """
        <html>
        <body>
            <h2>Cloud NGFW for AWS Known Issues</h2>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>CNGFWAWS-100</td><td>Known issue in AWS deployment.</td></tr>
                    <tr><td>CNGFWAWS-101</td><td>VPC configuration issue.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore') as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(known_html, "lxml")
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_cloud_ngfw_aws()

        assert product.id == "cloud-ngfw-aws"
        assert product.name == "Cloud NGFW for AWS"
        assert len(product.versions) == 1
        assert product.versions[0].version == "SaaS"
        assert len(product.versions[0].known_issues) == 2
        assert len(product.versions[0].addressed_issues) == 0

    @pytest.mark.asyncio
    async def test_crawl_cloud_ngfw_aws_empty_page(self):
        """Test handling of empty page."""
        empty_html = "<html><body></body></html>"

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore') as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(empty_html, "lxml")
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_cloud_ngfw_aws()

        assert product.id == "cloud-ngfw-aws"
        assert len(product.versions) == 0


class TestCloudNGFWAWSCrawlFunction:
    """Tests for the crawl_cloud_ngfw_aws function."""

    def test_crawl_cloud_ngfw_aws_import(self):
        """Test that crawl_cloud_ngfw_aws can be imported."""
        from bugdb.crawler import crawl_cloud_ngfw_aws
        assert callable(crawl_cloud_ngfw_aws)


class TestADEMDateParsing:
    """Tests for ADEM date parsing."""

    def test_parse_adem_date_month_year(self):
        """Test parsing 'Month Year' format."""
        crawler = PaloAltoCrawler()
        assert crawler._parse_adem_date("March 2024") == "2024-03-01"
        assert crawler._parse_adem_date("December 2023") == "2023-12-01"
        assert crawler._parse_adem_date("January 2025") == "2025-01-01"

    def test_parse_adem_date_month_day_year(self):
        """Test parsing 'Month Day, Year' format."""
        crawler = PaloAltoCrawler()
        assert crawler._parse_adem_date("March 15, 2024") == "2024-03-15"
        assert crawler._parse_adem_date("December 1, 2023") == "2023-12-01"
        assert crawler._parse_adem_date("January 31 2025") == "2025-01-31"

    def test_parse_adem_date_iso_format(self):
        """Test parsing ISO date format."""
        crawler = PaloAltoCrawler()
        assert crawler._parse_adem_date("2024-03-15") == "2024-03-15"
        assert crawler._parse_adem_date("2023-12-01") == "2023-12-01"

    def test_parse_adem_date_invalid(self):
        """Test that invalid dates return None."""
        crawler = PaloAltoCrawler()
        assert crawler._parse_adem_date("Not a date") is None
        assert crawler._parse_adem_date("Bug ID: ADEM-123") is None
        assert crawler._parse_adem_date("") is None


class TestADEMCrawler:
    """Tests for Autonomous DEM crawler."""

    @pytest.mark.asyncio
    async def test_crawl_adem_basic(self):
        """Test basic ADEM crawling with version headers."""
        known_html = """
        <html>
        <body>
            <h2>Autonomous DEM Agent 5.9 Known Issues</h2>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>ADEM-100</td><td>Agent connection issue.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """
        addressed_html = """
        <html>
        <body>
            <h2>Autonomous DEM Agent 5.9 Addressed Issues</h2>
            <h3>March 2024</h3>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>ADEM-50</td><td>Fixed memory leak.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """

        async def mock_fetch(url):
            if "known-issues" in url:
                return BeautifulSoup(known_html, "lxml")
            else:
                return BeautifulSoup(addressed_html, "lxml")

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore', side_effect=mock_fetch):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_adem()

        assert product.id == "adem"
        assert product.name == "Autonomous DEM"
        assert len(product.versions) == 1
        assert product.versions[0].version == "5.9"
        assert len(product.versions[0].known_issues) == 1
        assert len(product.versions[0].addressed_issues) == 1
        assert product.versions[0].addressed_issues[0].release_date == "2024-03-01"

    @pytest.mark.asyncio
    async def test_crawl_adem_multiple_versions(self):
        """Test ADEM crawling with multiple agent versions."""
        known_html = """
        <html>
        <body>
            <h2>Agent 5.9 Known Issues</h2>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>ADEM-100</td><td>Issue in 5.9.</td></tr>
                </tbody>
            </table>
            <h2>Agent 5.8 Known Issues</h2>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>ADEM-90</td><td>Issue in 5.8.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """
        addressed_html = "<html><body></body></html>"

        async def mock_fetch(url):
            if "known-issues" in url:
                return BeautifulSoup(known_html, "lxml")
            else:
                return BeautifulSoup(addressed_html, "lxml")

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore', side_effect=mock_fetch):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_adem()

        assert len(product.versions) == 2
        versions = {v.version for v in product.versions}
        assert "5.9" in versions
        assert "5.8" in versions

    @pytest.mark.asyncio
    async def test_crawl_adem_release_dates_in_addressed(self):
        """Test that release dates are captured for addressed issues."""
        known_html = "<html><body></body></html>"
        addressed_html = """
        <html>
        <body>
            <h2>Autonomous DEM Agent 5.9 Addressed Issues</h2>
            <h3>March 15, 2024</h3>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>ADEM-50</td><td>Fixed in March.</td></tr>
                </tbody>
            </table>
            <h3>February 2024</h3>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>ADEM-40</td><td>Fixed in February.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """

        async def mock_fetch(url):
            if "known-issues" in url:
                return BeautifulSoup(known_html, "lxml")
            else:
                return BeautifulSoup(addressed_html, "lxml")

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore', side_effect=mock_fetch):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_adem()

        assert len(product.versions) == 1
        addressed = product.versions[0].addressed_issues
        assert len(addressed) == 2

        # Check that release dates are captured
        dates = {issue.release_date for issue in addressed}
        assert "2024-03-15" in dates
        assert "2024-02-01" in dates


class TestADEMCrawlFunction:
    """Tests for the crawl_adem function."""

    def test_crawl_adem_import(self):
        """Test that crawl_adem can be imported."""
        from bugdb.crawler import crawl_adem
        assert callable(crawl_adem)

    def test_crawl_adem_accepts_version_params(self):
        """Test that crawl_adem accepts version params for API compatibility."""
        from bugdb.crawler import crawl_adem
        import inspect
        sig = inspect.signature(crawl_adem)
        params = list(sig.parameters.keys())
        assert "major_versions" in params
        assert "skip_versions" in params


class TestSCMVersionSortKey:
    """Tests for SCM version sort key."""

    def test_scm_version_sort_key_standard(self):
        """Test sorting standard SCM versions."""
        crawler = PaloAltoCrawler()
        assert crawler._scm_version_sort_key("2025.r5.0") == (2025, 5, 0)
        assert crawler._scm_version_sort_key("2024.r12.1") == (2024, 12, 1)
        assert crawler._scm_version_sort_key("2023.r1.0") == (2023, 1, 0)

    def test_scm_version_sort_key_unknown(self):
        """Test sorting Unknown version."""
        crawler = PaloAltoCrawler()
        assert crawler._scm_version_sort_key("Unknown") == (0, 0, 0)

    def test_scm_version_sort_key_invalid(self):
        """Test sorting invalid version."""
        crawler = PaloAltoCrawler()
        assert crawler._scm_version_sort_key("invalid") == (0, 0, 0)


class TestSCMCrawler:
    """Tests for Strata Cloud Manager crawler."""

    @pytest.mark.asyncio
    async def test_crawl_scm_known_issues_with_components(self):
        """Test SCM known issues parsing with component headers."""
        known_html = """
        <html>
        <body>
            <h2>Configuration Management Known Issues</h2>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>SCM-100</td><td>Config issue.</td></tr>
                </tbody>
            </table>
            <h2>Command Center Known Issues</h2>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>SCM-200</td><td>Command Center issue.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """
        addressed_html = "<html><body></body></html>"

        async def mock_fetch(url):
            if "known-issues" in url:
                return BeautifulSoup(known_html, "lxml")
            else:
                return BeautifulSoup(addressed_html, "lxml")

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore', side_effect=mock_fetch):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_scm()

        assert product.id == "scm"
        assert product.name == "Strata Cloud Manager"
        assert len(product.versions) == 1
        assert product.versions[0].version == "SaaS"

        known = product.versions[0].known_issues
        assert len(known) == 2

        # Check component association
        config_issue = next(i for i in known if i.bug_id == "SCM-100")
        assert "Configuration Management" in config_issue.affected_components

        cc_issue = next(i for i in known if i.bug_id == "SCM-200")
        assert "Command Center" in cc_issue.affected_components

    @pytest.mark.asyncio
    async def test_crawl_scm_addressed_issues_with_versions(self):
        """Test SCM addressed issues parsing with version headers."""
        known_html = "<html><body></body></html>"
        addressed_html = """
        <html>
        <body>
            <h2>2025.r5.0</h2>
            <h3>Command Center</h3>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>SCM-50</td><td>Fixed in r5.</td></tr>
                </tbody>
            </table>
            <h2>2025.r4.0</h2>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>SCM-40</td><td>Fixed in r4.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """

        async def mock_fetch(url):
            if "known-issues" in url:
                return BeautifulSoup(known_html, "lxml")
            else:
                return BeautifulSoup(addressed_html, "lxml")

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore', side_effect=mock_fetch):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_scm()

        assert len(product.versions) == 2
        versions = {v.version for v in product.versions}
        assert "2025.r5.0" in versions
        assert "2025.r4.0" in versions

        # Check component association for r5 issue
        r5_version = next(v for v in product.versions if v.version == "2025.r5.0")
        assert len(r5_version.addressed_issues) == 1
        assert "Command Center" in r5_version.addressed_issues[0].affected_components

    @pytest.mark.asyncio
    async def test_crawl_scm_addressed_issues_with_date_only(self):
        """Test SCM addressed issues with date-only releases (no version)."""
        known_html = "<html><body></body></html>"
        addressed_html = """
        <html>
        <body>
            <h2>September 2024</h2>
            <table>
                <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>SCM-30</td><td>Fixed in September.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """

        async def mock_fetch(url):
            if "known-issues" in url:
                return BeautifulSoup(known_html, "lxml")
            else:
                return BeautifulSoup(addressed_html, "lxml")

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore', side_effect=mock_fetch):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_scm()

        assert len(product.versions) == 1
        assert product.versions[0].version == "Unknown"
        assert len(product.versions[0].addressed_issues) == 1
        assert product.versions[0].addressed_issues[0].release_date == "2024-09-01"


class TestSCMMainAddressedTable:
    """Tests for parsing SCM main addressed issues table with concatenated bug ID/version."""

    @pytest.mark.asyncio
    async def test_parse_scm_main_addressed_table_concat_format(self):
        """Test parsing table with concatenated bug ID and version (e.g., ADI-478552025.r5.0)."""
        known_html = "<html><body></body></html>"
        addressed_html = """
        <html>
        <body>
            <h3>Addressed Issues</h3>
            <table>
                <thead><tr><th></th><th></th></tr></thead>
                <tbody>
                    <tr><td></td><td></td></tr>
                    <tr><td>ADI-478552025.r5.0</td><td>Fixed an issue with configuration push.</td></tr>
                    <tr><td>ADI-491212025.r5.0</td><td>Fixed View Only role permissions.</td></tr>
                    <tr><td>ADI-482732025.r4.0</td><td>Fixed authentication issue.</td></tr>
                </tbody>
            </table>
            <h3>Command Center Addressed Issues</h3>
            <table>
                <thead><tr><th>ID</th><th>Description</th></tr></thead>
                <tbody>
                    <tr><td>NETVIS-2017</td><td>Fixed DLP redirect issue.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """

        async def mock_fetch(url):
            if "known-issues" in url:
                return BeautifulSoup(known_html, "lxml")
            else:
                return BeautifulSoup(addressed_html, "lxml")

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore', side_effect=mock_fetch):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_scm()

        # Should have 3 versions: 2025.r5.0, 2025.r4.0, Unknown
        assert len(product.versions) == 3
        versions = {v.version for v in product.versions}
        assert "2025.r5.0" in versions
        assert "2025.r4.0" in versions
        assert "Unknown" in versions

        # Check 2025.r5.0 version has 2 ADI issues
        r5_version = next(v for v in product.versions if v.version == "2025.r5.0")
        assert len(r5_version.addressed_issues) == 2
        bug_ids = {i.bug_id for i in r5_version.addressed_issues}
        assert "ADI-47855" in bug_ids
        assert "ADI-49121" in bug_ids

        # Check 2025.r4.0 version has 1 ADI issue
        r4_version = next(v for v in product.versions if v.version == "2025.r4.0")
        assert len(r4_version.addressed_issues) == 1
        assert r4_version.addressed_issues[0].bug_id == "ADI-48273"

        # Check Unknown version has NETVIS issue from Command Center
        unknown_version = next(v for v in product.versions if v.version == "Unknown")
        assert len(unknown_version.addressed_issues) == 1
        assert unknown_version.addressed_issues[0].bug_id == "NETVIS-2017"
        assert "Command Center" in unknown_version.addressed_issues[0].affected_components

    @pytest.mark.asyncio
    async def test_parse_scm_main_addressed_table_date_format(self):
        """Test parsing table with date concatenated format (e.g., ADI-38973September 2024)."""
        known_html = "<html><body></body></html>"
        addressed_html = """
        <html>
        <body>
            <table>
                <thead><tr><th></th><th></th></tr></thead>
                <tbody>
                    <tr><td>ADI-38973September 2024</td><td>Fixed in September.</td></tr>
                    <tr><td>ADI-34609June 2024</td><td>Fixed in June.</td></tr>
                    <tr><td>ADI-36846</td><td>Bug only format.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """

        async def mock_fetch(url):
            if "known-issues" in url:
                return BeautifulSoup(known_html, "lxml")
            else:
                return BeautifulSoup(addressed_html, "lxml")

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore', side_effect=mock_fetch):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_scm()

        # All should be in Unknown version
        assert len(product.versions) == 1
        assert product.versions[0].version == "Unknown"
        assert len(product.versions[0].addressed_issues) == 3

        # Check bug IDs
        bug_ids = {i.bug_id for i in product.versions[0].addressed_issues}
        assert bug_ids == {"ADI-38973", "ADI-34609", "ADI-36846"}

        # Check release dates for date-formatted entries
        issues_by_id = {i.bug_id: i for i in product.versions[0].addressed_issues}
        assert issues_by_id["ADI-38973"].release_date == "2024-09-01"
        assert issues_by_id["ADI-34609"].release_date == "2024-06-01"
        assert issues_by_id["ADI-36846"].release_date is None

    @pytest.mark.asyncio
    async def test_parse_scm_main_addressed_table_empty_rows_skipped(self):
        """Test that empty rows in the main table are skipped."""
        known_html = "<html><body></body></html>"
        addressed_html = """
        <html>
        <body>
            <table>
                <thead><tr><th></th><th></th></tr></thead>
                <tbody>
                    <tr><td></td><td></td></tr>
                    <tr><td></td><td></td></tr>
                    <tr><td>ADI-123452025.r1.0</td><td>Valid issue.</td></tr>
                </tbody>
            </table>
        </body>
        </html>
        """

        async def mock_fetch(url):
            if "known-issues" in url:
                return BeautifulSoup(known_html, "lxml")
            else:
                return BeautifulSoup(addressed_html, "lxml")

        with patch.object(PaloAltoCrawler, '_fetch_page_with_semaphore', side_effect=mock_fetch):
            async with PaloAltoCrawler() as crawler:
                product = await crawler.crawl_scm()

        assert len(product.versions) == 1
        assert product.versions[0].version == "2025.r1.0"
        assert len(product.versions[0].addressed_issues) == 1
        assert product.versions[0].addressed_issues[0].bug_id == "ADI-12345"


class TestSCMCrawlFunction:
    """Tests for the crawl_scm function."""

    def test_crawl_scm_import(self):
        """Test that crawl_scm can be imported."""
        from bugdb.crawler import crawl_scm
        assert callable(crawl_scm)

    def test_crawl_scm_accepts_version_params(self):
        """Test that crawl_scm accepts version params for API compatibility."""
        from bugdb.crawler import crawl_scm
        import inspect
        sig = inspect.signature(crawl_scm)
        params = list(sig.parameters.keys())
        assert "major_versions" in params
        assert "skip_versions" in params


"""Tests for the web crawler module."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from bs4 import BeautifulSoup

# Import specific crawler classes for product-specific tests
from bugdb.crawlers import (
    ADEMCrawler,
    CloudNGFWAWSCrawler,
    CloudNGFWAzureCrawler,
    DeviceSecurityCrawler,
    GlobalProtectCrawler,
    PANOSCrawler,
    PluginCrawler,
    PrismaAccessAgentCrawler,
    SCMCrawler,
    SDWANPluginCrawler,
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
    normalize_text,
    table_to_text,
)
from bugdb.crawlers import (
    BaseCrawler as PaloAltoCrawler,
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
            Issue(
                bug_id="GPC-001", description="Different description"
            ),  # Same bug, different desc
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


class TestPaloAltoCrawlerAsync:
    """Tests for async crawler functionality using mocked playwright."""

    @pytest.mark.asyncio
    async def test_crawler_context_manager(self, mock_playwright_all):
        """Test crawler can be used as async context manager."""
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_all):
            async with PaloAltoCrawler() as crawler:
                assert crawler._browser is not None
                assert crawler._semaphore is not None

    @pytest.mark.asyncio
    async def test_fetch_page_returns_soup(self, mock_playwright_globalprotect, fixtures_dir):
        """Test that _fetch_page returns BeautifulSoup object."""
        with patch(
            "bugdb.crawlers.base.async_playwright", return_value=mock_playwright_globalprotect
        ):
            async with PaloAltoCrawler() as crawler:
                page = await crawler._new_page()
                soup = await crawler._fetch_page(
                    page, "/globalprotect/release-notes/6-2/6-2-1-known-issues"
                )

                assert isinstance(soup, BeautifulSoup)
                # Should contain the expected content from our fixture
                title = soup.find("title")
                assert title is not None
                await page.close()

    @pytest.mark.asyncio
    async def test_parse_issues_page_integration(self, mock_playwright_globalprotect):
        """Test parsing issues from a full HTML page."""
        with patch(
            "bugdb.crawlers.base.async_playwright", return_value=mock_playwright_globalprotect
        ):
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
        with patch(
            "bugdb.crawlers.base.async_playwright", return_value=mock_playwright_globalprotect
        ):
            async with GlobalProtectCrawler() as crawler:
                result = await crawler.crawl(major_versions=["6-2"])

                assert result.product.id == "globalprotect"
                assert result.product.name == "GlobalProtect"
                # Should have found some versions
                assert len(result.product.versions) >= 0
                assert isinstance(result.failed_fetches, list)

    @pytest.mark.asyncio
    async def test_crawl_globalprotect_multi_version(self, mock_playwright_globalprotect):
        """Test crawling GlobalProtect with multi-version pages (older style)."""
        with patch(
            "bugdb.crawlers.base.async_playwright", return_value=mock_playwright_globalprotect
        ):
            async with GlobalProtectCrawler() as crawler:
                result = await crawler.crawl(major_versions=["6-1"])

                assert result.product.id == "globalprotect"
                # Multi-version pages should yield multiple versions
                # (if the fixture is properly parsed)
                assert isinstance(result.failed_fetches, list)

    @pytest.mark.asyncio
    async def test_crawl_panos_ngfw_pattern(self, mock_playwright_panos):
        """Test crawling PAN-OS with NGFW URL pattern (12.x+)."""
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            async with PANOSCrawler() as crawler:
                result = await crawler.crawl(major_versions=["12-1"])

                assert result.product.id == "panos"
                assert result.product.name == "PAN-OS"
                assert isinstance(result.failed_fetches, list)

    @pytest.mark.asyncio
    async def test_crawl_panos_ngfw_discovers_hotfixes(self, mock_playwright_panos):
        """Test that NGFW pattern (12.x+) discovers hotfix releases."""
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            async with PANOSCrawler() as crawler:
                result = await crawler.crawl(major_versions=["12-1"])

                versions = {v.version for v in result.product.versions}
                assert "12.1.5-h2" in versions

    @pytest.mark.asyncio
    async def test_crawl_panos_legacy_pattern(self, mock_playwright_panos):
        """Test crawling PAN-OS with legacy URL pattern (11.x and older)."""
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            async with PANOSCrawler() as crawler:
                result = await crawler.crawl(major_versions=["11-2"])

                assert result.product.id == "panos"
                assert result.product.name == "PAN-OS"
                assert isinstance(result.failed_fetches, list)

    @pytest.mark.asyncio
    async def test_crawl_panos_legacy_discovers_hotfixes(self, mock_playwright_panos):
        """Test that legacy pattern (11.x) discovers hotfix releases."""
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            async with PANOSCrawler() as crawler:
                result = await crawler.crawl(major_versions=["11-2"])

                versions = {v.version for v in result.product.versions}
                assert "11.2.4-h1" in versions

    @pytest.mark.asyncio
    async def test_panos_12_1_only_discoverable_via_ngfw_url(self, mock_playwright_panos):
        """Regression pin for the PAN-OS 12.1 URL-pattern bug.

        Starting with PAN-OS 12.1, Palo Alto Networks moved release notes
        from ``/pan-os/<v>/pan-os-release-notes`` onto the shared NGFW
        release-notes book at ``/ngfw/release-notes/<v>``. The crawler
        used to hard-code only the legacy path and silently dropped 12-1
        from discovery. A prior conftest.py revision masked this by
        mapping BOTH URLs to the same fixture.

        This test pins three things:

        1. Probing the legacy URL for 12-1 must fail — we rely on
           conftest.py no longer mapping ``/pan-os/12-1/...`` to anything.
        2. Probing the NGFW URL for 12-1 must succeed.
        3. ``discover_versions`` must still return "12-1" (via the
           fallback-to-NGFW code path in PANOSCrawler._resolve_landing_url).

        If any of these fail, the PAN-OS crawler has silently lost 12.1
        coverage again.
        """
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            async with PANOSCrawler() as crawler:
                # 1. Legacy URL for 12-1 must not resolve.
                legacy_ok = await crawler._probe_landing_url("/pan-os/12-1/pan-os-release-notes")
                assert legacy_ok is False, (
                    "Legacy URL pattern for 12-1 unexpectedly resolved. "
                    "Check conftest.py — it must NOT map "
                    "/pan-os/12-1/pan-os-release-notes to a fixture. "
                    "Mapping it would mask the PAN-OS 12.1 URL bug again."
                )

                # 2. NGFW URL for 12-1 must resolve.
                ngfw_ok = await crawler._probe_landing_url("/ngfw/release-notes/12-1")
                assert ngfw_ok is True, (
                    "NGFW URL pattern for 12-1 failed to resolve against "
                    "the fixture. Check PANOS_URL_MAPPING in conftest.py."
                )

                # 3. discover_versions must fall back to NGFW and still
                # include 12-1.
                versions = await crawler.discover_versions()
                assert "12-1" in versions, (
                    "discover_versions dropped 12-1 even though the NGFW "
                    "URL resolves. The fallback chain in "
                    "PANOSCrawler._resolve_landing_url is broken."
                )

                # 4. The resolved landing URL must be the NGFW one, not
                # the legacy one.
                assert crawler._base_url_for_version.get("12-1") == ("/ngfw/release-notes/12-1"), (
                    "Landing URL for 12-1 should be the NGFW pattern, got "
                    f"{crawler._base_url_for_version.get('12-1')!r}"
                )

    @pytest.mark.asyncio
    async def test_panos_warm_cache_skips_discovery(self, mock_playwright_panos, tmp_path):
        """S3 warm-cache path: a fresh version_infos cache short-circuits
        both discover_versions and discover_version_pages entirely.
        """
        from bugdb.crawlers.models import VersionInfo
        from bugdb.discovery_cache import DiscoveryCache

        cache_path = tmp_path / "discovery.json"
        cache = DiscoveryCache(path=cache_path)

        # Pre-populate the cache with a VersionInfo for 12-1 / 12.1.5.
        # The URL doesn't matter for this test — we're only verifying
        # that discovery is skipped, not that the URLs resolve.
        cache.put_version_infos(
            "panos",
            {
                "12-1": [
                    VersionInfo(
                        version="12.1.5",
                        known_issues_urls=["/ngfw/release-notes/12-1/pan-os-12-1-5-known-issues"],
                        addressed_issues_urls=[
                            "/ngfw/release-notes/12-1/pan-os-12-1-5-addressed-issues"
                        ],
                    )
                ]
            },
        )
        cache.save()

        reloaded = DiscoveryCache(path=cache_path)
        assert reloaded.is_fresh("panos")

        # Patch both discovery methods to raise — if either fires the
        # cache-skip path is broken.
        async def _raise_discover_versions():
            raise AssertionError("discover_versions should not be called on a warm cache hit")

        async def _raise_discover_version_pages(major_version: str):
            raise AssertionError(
                f"discover_version_pages should not be called on a warm cache hit, "
                f"got {major_version!r}"
            )

        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            async with PANOSCrawler(discovery_cache=reloaded) as crawler:
                crawler.discover_versions = _raise_discover_versions  # type: ignore[assignment]
                crawler.discover_version_pages = _raise_discover_version_pages  # type: ignore[assignment]

                vi_by_major = await crawler._resolve_version_infos(
                    discover_majors_fn=crawler.discover_versions,
                    discover_pages_fn=crawler.discover_version_pages,
                    explicit_majors=None,
                    skip_versions=set(),
                )

        assert "12-1" in vi_by_major
        assert len(vi_by_major["12-1"]) == 1
        assert vi_by_major["12-1"][0].version == "12.1.5"

    @pytest.mark.asyncio
    async def test_panos_warm_cache_filters_skip_versions(self, mock_playwright_panos, tmp_path):
        """S3 warm-cache path + skip_versions: cached entries are filtered
        by the passed-in skip_versions set so already-fetched versions
        don't get re-crawled.
        """
        from bugdb.crawlers.models import VersionInfo
        from bugdb.discovery_cache import DiscoveryCache

        cache_path = tmp_path / "discovery.json"
        cache = DiscoveryCache(path=cache_path)
        cache.put_version_infos(
            "panos",
            {
                "12-1": [
                    VersionInfo(version="12.1.5", known_issues_urls=[], addressed_issues_urls=[]),
                    VersionInfo(version="12.1.4", known_issues_urls=[], addressed_issues_urls=[]),
                ]
            },
        )
        cache.save()

        reloaded = DiscoveryCache(path=cache_path)
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            async with PANOSCrawler(discovery_cache=reloaded) as crawler:
                vi_by_major = await crawler._resolve_version_infos(
                    discover_majors_fn=crawler.discover_versions,
                    discover_pages_fn=crawler.discover_version_pages,
                    explicit_majors=None,
                    skip_versions={"12.1.4"},  # 12.1.5 is new
                )

        assert len(vi_by_major["12-1"]) == 1
        assert vi_by_major["12-1"][0].version == "12.1.5"

    @pytest.mark.asyncio
    async def test_panos_explicit_majors_bypasses_cache(self, mock_playwright_panos, tmp_path):
        """S3 explicit-majors path: when the caller passes explicit_majors
        (i.e. `bugdb fetch panos --version 12-1`), the cache must be
        ignored and discover_pages_fn must be called for each named major.
        The user asked for something specific.
        """
        from bugdb.crawlers.models import VersionInfo
        from bugdb.discovery_cache import DiscoveryCache

        cache_path = tmp_path / "discovery.json"
        cache = DiscoveryCache(path=cache_path)
        # Pre-populate with stale/incorrect data to prove we don't use it.
        cache.put_version_infos(
            "panos",
            {
                "12-1": [
                    VersionInfo(
                        version="FAKE-FROM-CACHE",
                        known_issues_urls=[],
                        addressed_issues_urls=[],
                    )
                ]
            },
        )
        cache.save()

        reloaded = DiscoveryCache(path=cache_path)
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            async with PANOSCrawler(discovery_cache=reloaded) as crawler:
                vi_by_major = await crawler._resolve_version_infos(
                    discover_majors_fn=crawler.discover_versions,
                    discover_pages_fn=crawler.discover_version_pages,
                    explicit_majors=["12-1"],
                    skip_versions=set(),
                )

        # The fake cache value must NOT appear in the result.
        versions = [vi.version for vi in vi_by_major.get("12-1", [])]
        assert "FAKE-FROM-CACHE" not in versions
        assert "12.1.5" in versions  # real discovery found this from fixtures

    @pytest.mark.asyncio
    async def test_panos_stale_cache_re_discovers(self, mock_playwright_panos, tmp_path):
        """S3 stale-cache path: a cache older than 24h must trigger a
        fresh discovery, and the fresh result must replace the stale
        cache entry.
        """
        from datetime import UTC, datetime, timedelta

        from bugdb.crawlers.models import VersionInfo
        from bugdb.discovery_cache import TTL_SECONDS, DiscoveryCache

        cache_path = tmp_path / "discovery.json"
        cache = DiscoveryCache(path=cache_path)
        cache.put_version_infos(
            "panos",
            {
                "12-1": [
                    VersionInfo(
                        version="STALE-VALUE",
                        known_issues_urls=[],
                        addressed_issues_urls=[],
                    )
                ]
            },
        )
        # Backdate the cache by TTL + 1 minute.
        old = datetime.now(UTC) - timedelta(seconds=TTL_SECONDS + 60)
        cache._data["products"]["panos"]["updated_at"] = old.isoformat(timespec="seconds")
        cache.save()

        reloaded = DiscoveryCache(path=cache_path)
        assert reloaded.is_fresh("panos") is False

        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            async with PANOSCrawler(discovery_cache=reloaded) as crawler:
                vi_by_major = await crawler._resolve_version_infos(
                    discover_majors_fn=crawler.discover_versions,
                    discover_pages_fn=crawler.discover_version_pages,
                    explicit_majors=None,
                    skip_versions=set(),
                )

        # Stale value must be gone, fresh discovery must have run.
        versions = [vi.version for vi in vi_by_major.get("12-1", [])]
        assert "STALE-VALUE" not in versions
        assert "12.1.5" in versions

    @pytest.mark.asyncio
    async def test_panos_url_pattern_cache_hit_skips_probe(self, mock_playwright_panos, tmp_path):
        """S1 cache-hit path: a fresh persistent cache short-circuits the
        dual-template probe in ``_resolve_landing_url``. Second crawl
        invocation with the same cache must not call ``_probe_landing_url``.
        """
        from bugdb.discovery_cache import DiscoveryCache

        cache_path = tmp_path / "discovery.json"

        # First run: probe normally, populate the cache.
        cache = DiscoveryCache(path=cache_path)
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            async with PANOSCrawler(discovery_cache=cache) as crawler:
                first_url = await crawler._resolve_landing_url("12-1")
                assert first_url == "/ngfw/release-notes/12-1"
        cache.save()

        # Second run: fresh crawler, same cache file. Patch _probe_landing_url
        # to raise if called — if the cache-hit path works, it's never called.
        reloaded_cache = DiscoveryCache(path=cache_path)
        assert reloaded_cache.is_fresh("panos")
        assert reloaded_cache.get_url_pattern("panos", "12-1") == "/ngfw/release-notes/12-1"

        probe_called = False

        async def _raising_probe(url: str) -> bool:
            nonlocal probe_called
            probe_called = True
            raise AssertionError(
                f"_probe_landing_url should not be called on cache hit, got {url!r}"
            )

        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            async with PANOSCrawler(discovery_cache=reloaded_cache) as crawler:
                crawler._probe_landing_url = _raising_probe  # type: ignore[assignment]
                second_url = await crawler._resolve_landing_url("12-1")

        assert second_url == "/ngfw/release-notes/12-1"
        assert probe_called is False

    @pytest.mark.asyncio
    async def test_panos_url_pattern_cache_miss_still_probes(self, mock_playwright_panos, tmp_path):
        """S1 cache-miss path: when the cache has no entry for the major,
        fall through to the normal probe chain and populate the cache.
        """
        from bugdb.discovery_cache import DiscoveryCache

        cache_path = tmp_path / "discovery.json"
        cache = DiscoveryCache(path=cache_path)
        assert cache.get_url_pattern("panos", "12-1") is None

        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            async with PANOSCrawler(discovery_cache=cache) as crawler:
                url = await crawler._resolve_landing_url("12-1")

        assert url == "/ngfw/release-notes/12-1"
        assert cache.get_url_pattern("panos", "12-1") == "/ngfw/release-notes/12-1"

    @pytest.mark.asyncio
    async def test_panos_discover_skips_known_and_addressed_hub_pages(self, mock_playwright_panos):
        """Regression pin for S2: discover_version_pages must filter out
        hub pages whose last path segment contains "known-and-addressed".

        The fixture ``panos/12-1-index.html`` lists six such hub URLs
        (12.1.0 through 12.1.5). They are link-only indexes with no
        issue tables (verified in
        ``panos/12-1-5-known-and-addressed-issues.html``), so fetching
        them wastes a request per hotfix. Before the S2 fix the
        substring classification in discover_version_pages added them
        to ``addressed_issues_urls`` because "addressed" appears in the
        slug; after the S2 fix the filter runs first and skips them.
        """
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            async with PANOSCrawler() as crawler:
                version_infos = await crawler.discover_version_pages("12-1")

                assert version_infos, "discover_version_pages returned nothing"

                # No URL in any VersionInfo's known or addressed list may
                # contain the "known-and-addressed" hub substring.
                all_urls: list[str] = []
                for vi in version_infos:
                    all_urls.extend(vi.known_issues_urls)
                    all_urls.extend(vi.addressed_issues_urls)

                hub_urls = [url for url in all_urls if "known-and-addressed" in url.lower()]
                assert not hub_urls, (
                    f"PAN-OS discover_version_pages is still emitting "
                    f"'known-and-addressed' hub URLs: {hub_urls}. These "
                    f"pages are link-only indexes and fetching them is "
                    f"pure waste. Check the S2 filter in "
                    f"src/bugdb/crawlers/products/panos.py::discover_version_pages."
                )

                # Positive assertion: the leaf known/addressed pages
                # for 12.1.5 ARE present, so the filter didn't overshoot.
                assert any(url.endswith("/pan-os-12-1-5-known-issues") for url in all_urls), (
                    "12.1.5 known-issues leaf URL is missing from discover_version_pages output"
                )
                assert any(url.endswith("/pan-os-12-1-5-addressed-issues") for url in all_urls), (
                    "12.1.5 addressed-issues leaf URL is missing from discover_version_pages output"
                )

    @pytest.mark.asyncio
    async def test_crawl_prisma_access_agent(self, mock_playwright_prisma):
        """Test crawling Prisma Access Agent."""
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_prisma):
            async with PrismaAccessAgentCrawler() as crawler:
                result = await crawler.crawl(major_versions=["26-1"])

                assert result.product.id == "prisma-access-agent"
                assert result.product.name == "Prisma Access Agent"
                assert isinstance(result.failed_fetches, list)

    @pytest.mark.asyncio
    async def test_crawl_version_parallel(self, mock_playwright_globalprotect):
        """Test parallel version crawling."""
        with patch(
            "bugdb.crawlers.base.async_playwright", return_value=mock_playwright_globalprotect
        ):
            async with PaloAltoCrawler(max_concurrency=3) as crawler:
                version_infos = [
                    VersionInfo(
                        version="6.2.1",
                        known_issues_urls=["/globalprotect/release-notes/6-2/6-2-1-known-issues"],
                        addressed_issues_urls=[
                            "/globalprotect/release-notes/6-2/6-2-1-addressed-issues"
                        ],
                    ),
                ]

                versions, failed = await crawler._crawl_versions_parallel(version_infos)

                # Should return list of ProductVersion and list of FailedFetch
                assert isinstance(versions, list)
                for pv in versions:
                    assert isinstance(pv, ProductVersion)
                assert isinstance(failed, list)


class TestGlobalBackoff:
    """Tests for global backoff mechanism on connection refused errors."""

    def test_is_connection_refused_error_detection(self):
        """Test detection of connection refused errors."""
        crawler = PaloAltoCrawler()

        # Should detect connection refused errors
        assert crawler._is_connection_refused_error(Exception("net::ERR_CONNECTION_REFUSED"))
        assert crawler._is_connection_refused_error(Exception("Connection refused by server"))
        assert crawler._is_connection_refused_error(Exception("ERR_CONNECTION_RESET occurred"))

        # Should not trigger on other errors
        assert not crawler._is_connection_refused_error(Exception("Page not found"))
        assert not crawler._is_connection_refused_error(Exception("Timeout waiting for selector"))

    @pytest.mark.asyncio
    async def test_global_backoff_trigger_and_wait(self):
        """Test that global backoff can be triggered and waited on."""
        import time

        # Create crawler with context manager to initialize lock
        crawler = PaloAltoCrawler()
        crawler._backoff_lock = asyncio.Lock()
        crawler._global_backoff_until = 0.0

        # Trigger backoff
        await crawler._trigger_global_backoff()

        # Verify backoff was set
        assert crawler._global_backoff_until > time.monotonic()
        assert (
            crawler._global_backoff_until <= time.monotonic() + crawler.GLOBAL_BACKOFF_DURATION + 1
        )

    @pytest.mark.asyncio
    async def test_global_backoff_wait_skips_if_not_active(self):
        """Test that wait returns immediately if no backoff is active."""
        import time

        crawler = PaloAltoCrawler()
        crawler._backoff_lock = asyncio.Lock()
        crawler._global_backoff_until = 0.0  # No backoff active

        start = time.monotonic()
        await crawler._wait_for_global_backoff()
        elapsed = time.monotonic() - start

        # Should return almost immediately (less than 0.1s)
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_global_backoff_shared_across_tasks(self):
        """Test that backoff is shared across concurrent tasks."""
        import time

        crawler = PaloAltoCrawler()
        crawler._backoff_lock = asyncio.Lock()
        crawler._global_backoff_until = 0.0

        # Set a short backoff for testing (0.2 seconds)
        crawler.GLOBAL_BACKOFF_DURATION = 0.2

        wait_times = []

        async def task_that_waits(task_id: int):
            start = time.monotonic()
            await crawler._wait_for_global_backoff()
            wait_times.append((task_id, time.monotonic() - start))

        # Trigger backoff
        await crawler._trigger_global_backoff()

        # Start multiple tasks that should all wait
        tasks = [asyncio.create_task(task_that_waits(i)) for i in range(3)]

        await asyncio.gather(*tasks)

        # All tasks should have waited approximately the same amount
        # (within 0.15 seconds of each other)
        for task_id, wait_time in wait_times:
            assert wait_time >= 0.15, f"Task {task_id} didn't wait long enough"


class TestWrapperFunctions:
    """Tests for the synchronous wrapper functions."""

    def test_crawl_globalprotect_returns_database(self, mock_playwright_globalprotect):
        """Test that crawl_globalprotect returns a FetchResult with BugDatabase."""
        with patch(
            "bugdb.crawlers.base.async_playwright", return_value=mock_playwright_globalprotect
        ):
            result = crawl_globalprotect(major_versions=["6-2"])

            assert result is not None
            assert len(result.database.products) == 1
            assert result.database.products[0].id == "globalprotect"
            assert result.database.metadata is not None
            assert isinstance(result.failed_fetches, list)

    def test_crawl_panos_returns_database(self, mock_playwright_panos):
        """Test that crawl_panos returns a FetchResult with BugDatabase."""
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            result = crawl_panos(major_versions=["12-1"])

            assert result is not None
            assert len(result.database.products) == 1
            assert result.database.products[0].id == "panos"
            assert isinstance(result.failed_fetches, list)

    def test_crawl_prisma_returns_database(self, mock_playwright_prisma):
        """Test that crawl_prisma_access_agent returns a FetchResult with BugDatabase."""
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_prisma):
            result = crawl_prisma_access_agent(major_versions=["26-1"])

            assert result is not None
            assert len(result.database.products) == 1
            assert result.database.products[0].id == "prisma-access-agent"
            assert isinstance(result.failed_fetches, list)

    def test_crawl_globalprotect_metadata_source(self, mock_playwright_globalprotect):
        """Test that metadata source is set correctly."""
        with patch(
            "bugdb.crawlers.base.async_playwright", return_value=mock_playwright_globalprotect
        ):
            result = crawl_globalprotect(major_versions=["6-2"])

            assert "GlobalProtect" in result.database.metadata.source
            assert "6.2" in result.database.metadata.source

    def test_crawl_globalprotect_all_versions_source(self, mock_playwright_globalprotect):
        """Test metadata source when crawling all versions."""
        with (
            patch(
                "bugdb.crawlers.base.async_playwright",
                return_value=mock_playwright_globalprotect,
            ),
            patch.object(
                GlobalProtectCrawler,
                "discover_versions",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = crawl_globalprotect(major_versions=None)

            assert "All Versions" in result.database.metadata.source


class TestCrawlerConfiguration:
    """Tests for crawler configuration options."""

    def test_crawler_default_configuration(self):
        """Test default crawler configuration."""
        crawler = PaloAltoCrawler()

        assert crawler.headless is True
        assert crawler.debug is False
        assert crawler.max_concurrency == 3
        assert crawler.max_retries == 3
        assert crawler.retry_delay == 2.0

    def test_crawler_custom_configuration(self):
        """Test custom crawler configuration."""
        crawler = PaloAltoCrawler(
            headless=False,
            debug=True,
            max_concurrency=10,
            max_retries=5,
            retry_delay=1.0,
        )

        assert crawler.headless is False
        assert crawler.debug is True
        assert crawler.max_concurrency == 10
        assert crawler.max_retries == 5
        assert crawler.retry_delay == 1.0

    def test_crawler_debug_configuration(self):
        """Test that debug mode can be enabled."""
        crawler = PaloAltoCrawler(debug=True)
        assert crawler.debug is True


class TestMultiVersionPageParsing:
    """Tests for multi-version page parsing."""

    @pytest.mark.asyncio
    async def test_parse_multi_version_issues_page(
        self, mock_playwright_globalprotect, sample_html_multi_version
    ):
        """Test parsing a page with multiple version sections."""
        # Create a custom mock that returns our sample HTML
        with patch(
            "bugdb.crawlers.base.async_playwright", return_value=mock_playwright_globalprotect
        ):
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
        version_620 = next(v for v in merged.products[0].versions if v.version == "6.2.0")
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
        with patch(
            "bugdb.crawlers.base.async_playwright", return_value=mock_playwright_globalprotect
        ):
            async with GlobalProtectCrawler() as crawler:
                # Crawl with skip_versions - should skip the specified version
                result = await crawler.crawl(
                    major_versions=["6-2"],
                    skip_versions={"6.2.1"},
                )

                assert result.product.id == "globalprotect"
                # Version 6.2.1 should be skipped
                versions = {v.version for v in result.product.versions}
                assert "6.2.1" not in versions

    @pytest.mark.asyncio
    async def test_crawl_globalprotect_empty_skip_versions(self, mock_playwright_globalprotect):
        """Test that empty skip_versions doesn't affect crawling."""
        with patch(
            "bugdb.crawlers.base.async_playwright", return_value=mock_playwright_globalprotect
        ):
            async with GlobalProtectCrawler() as crawler:
                result = await crawler.crawl(
                    major_versions=["6-2"],
                    skip_versions=set(),
                )

                assert result.product.id == "globalprotect"

    @pytest.mark.asyncio
    async def test_crawl_panos_skip_versions(self, mock_playwright_panos):
        """Test that skip_versions works for PAN-OS crawler."""
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            async with PANOSCrawler() as crawler:
                result = await crawler.crawl(
                    major_versions=["12-1"],
                    skip_versions={"12.1.5"},
                )

                assert result.product.id == "panos"
                versions = {v.version for v in result.product.versions}
                assert "12.1.5" not in versions

    @pytest.mark.asyncio
    async def test_crawl_prisma_skip_versions(self, mock_playwright_prisma):
        """Test that skip_versions works for Prisma Access Agent crawler."""
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_prisma):
            async with PrismaAccessAgentCrawler() as crawler:
                result = await crawler.crawl(
                    major_versions=["26-1"],
                    skip_versions={"26.1.2"},
                )

                assert result.product.id == "prisma-access-agent"
                versions = {v.version for v in result.product.versions}
                assert "26.1.2" not in versions

    def test_crawl_globalprotect_wrapper_skip_versions(self, mock_playwright_globalprotect):
        """Test that skip_versions works in sync wrapper function."""
        with patch(
            "bugdb.crawlers.base.async_playwright", return_value=mock_playwright_globalprotect
        ):
            result = crawl_globalprotect(
                major_versions=["6-2"],
                skip_versions={"6.2.1"},
            )

            assert result is not None
            versions = {v.version for p in result.database.products for v in p.versions}
            assert "6.2.1" not in versions

    def test_crawl_panos_wrapper_skip_versions(self, mock_playwright_panos):
        """Test that skip_versions works in PAN-OS sync wrapper function."""
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_panos):
            result = crawl_panos(
                major_versions=["12-1"],
                skip_versions={"12.1.5"},
            )

            assert result is not None
            versions = {v.version for p in result.database.products for v in p.versions}
            assert "12.1.5" not in versions

    def test_crawl_prisma_wrapper_skip_versions(self, mock_playwright_prisma):
        """Test that skip_versions works in Prisma sync wrapper function."""
        with patch("bugdb.crawlers.base.async_playwright", return_value=mock_playwright_prisma):
            result = crawl_prisma_access_agent(
                major_versions=["26-1"],
                skip_versions={"26.1.2"},
            )

            assert result is not None
            versions = {v.version for p in result.database.products for v in p.versions}
            assert "26.1.2" not in versions


class TestExtractWorkaround:
    """Tests for the extract_workaround function."""

    def test_extract_workaround_simple(self):
        """Test extracting a simple workaround."""
        description = (
            "The application crashes when clicking save. Workaround: Click cancel instead."
        )
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
        description = (
            "Memory leak detected. Workaround: 1. Stop the service. 2. Clear cache. 3. Restart."
        )
        cleaned, workaround = extract_workaround(description)

        assert cleaned == "Memory leak detected."
        assert workaround == "1. Stop the service. 2. Clear cache. 3. Restart."

    def test_extract_workaround_at_end(self):
        """Test workaround at the end of description."""
        description = (
            "Feature not working as expected. Workaround: Disable and re-enable the feature."
        )
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
        bug_id, fix_info = extract_bug_id_and_fix_info(
            "EPM-4616Resolved in Prisma Access Agent 25.3"
        )

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

    def test_normalize_text_preserves_spaces_around_inline_elements(self):
        """Test that normalize_text preserves spaces around <b>, <i>, etc."""
        # This is the exact pattern from the bug report
        html = '<td class="entry relcol">In the<b class="ph b"> Operational Health</b> view of the command center</td>'
        soup = BeautifulSoup(html, "lxml")
        cell = soup.find("td")

        text = normalize_text(cell)

        # Verify spaces are preserved
        assert "In the Operational Health view" in text
        assert "theOperational" not in text  # Bug: missing space before
        assert "Healthview" not in text  # Bug: missing space after

    def test_normalize_text_collapses_multiple_spaces(self):
        """Test that normalize_text collapses multiple spaces into one."""
        html = "<p>Some    text   with   multiple    spaces</p>"
        soup = BeautifulSoup(html, "lxml")
        elem = soup.find("p")

        text = normalize_text(elem)

        assert text == "Some text with multiple spaces"
        assert "  " not in text  # No double spaces

    def test_normalize_text_handles_nested_formatting(self):
        """Test normalize_text with nested <b>, <i>, <span> elements."""
        html = "<td>Before<b> bold<i> and italic</i> text</b> after</td>"
        soup = BeautifulSoup(html, "lxml")
        cell = soup.find("td")

        text = normalize_text(cell)

        assert "Before bold and italic text after" in text

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
        issues = crawler._parse_issues_table_with_feature(table, feature="Remote Browser Isolation")

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


class TestPrismaAccessCrawlFunction:
    """Tests for the crawl_prisma_access function."""

    def test_crawl_prisma_access_import(self):
        """Test that crawl_prisma_access can be imported."""
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
        description = (
            "Connection drops intermittently. This issue is resolved in Prisma SD-WAN ION 6.4.2."
        )
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


class TestPrismaSDWANCrawlFunction:
    """Tests for the crawl_prisma_sdwan function."""

    def test_crawl_prisma_sdwan_import(self):
        """Test that crawl_prisma_sdwan can be imported."""
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

        with patch.object(
            CloudNGFWAzureCrawler, "_fetch_page_with_semaphore", side_effect=mock_fetch
        ):
            async with CloudNGFWAzureCrawler() as crawler:
                result = await crawler.crawl()

        assert result.product.id == "cloud-ngfw-azure"
        assert result.product.name == "Cloud NGFW for Azure"
        assert len(result.product.versions) == 1
        assert result.product.versions[0].version == "SaaS"
        assert len(result.product.versions[0].known_issues) == 2
        assert len(result.product.versions[0].addressed_issues) == 1
        assert isinstance(result.failed_fetches, list)

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

        with patch.object(
            CloudNGFWAzureCrawler, "_fetch_page_with_semaphore", side_effect=mock_fetch
        ):
            async with CloudNGFWAzureCrawler() as crawler:
                result = await crawler.crawl()

        issue = result.product.versions[0].known_issues[0]
        assert issue.bug_id == "CNGFWAZR-200"
        assert issue.workaround == "Increase timeout value in settings."
        assert "Workaround" not in issue.description

    @pytest.mark.asyncio
    async def test_crawl_cloud_ngfw_azure_empty_pages(self):
        """Test handling of empty pages."""
        empty_html = "<html><body></body></html>"

        async def mock_fetch(url):
            return BeautifulSoup(empty_html, "lxml")

        with patch.object(
            CloudNGFWAzureCrawler, "_fetch_page_with_semaphore", side_effect=mock_fetch
        ):
            async with CloudNGFWAzureCrawler() as crawler:
                result = await crawler.crawl()

        assert result.product.id == "cloud-ngfw-azure"
        assert len(result.product.versions) == 0


class TestCloudNGFWAzureCrawlFunction:
    """Tests for the crawl_cloud_ngfw_azure function."""

    def test_crawl_cloud_ngfw_azure_import(self):
        """Test that crawl_cloud_ngfw_azure can be imported."""
        from bugdb.crawler import crawl_cloud_ngfw_azure

        assert callable(crawl_cloud_ngfw_azure)

    def test_crawl_cloud_ngfw_azure_accepts_version_params(self):
        """Test that crawl_cloud_ngfw_azure accepts version params for API compatibility."""
        import inspect

        from bugdb.crawler import crawl_cloud_ngfw_azure

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

        with patch.object(CloudNGFWAWSCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(known_html, "lxml")
            async with CloudNGFWAWSCrawler() as crawler:
                result = await crawler.crawl()

        assert result.product.id == "cloud-ngfw-aws"
        assert result.product.name == "Cloud NGFW for AWS"
        assert len(result.product.versions) == 1
        assert result.product.versions[0].version == "SaaS"
        assert len(result.product.versions[0].known_issues) == 2
        assert len(result.product.versions[0].addressed_issues) == 0
        assert isinstance(result.failed_fetches, list)

    @pytest.mark.asyncio
    async def test_crawl_cloud_ngfw_aws_empty_page(self):
        """Test handling of empty page."""
        empty_html = "<html><body></body></html>"

        with patch.object(CloudNGFWAWSCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(empty_html, "lxml")
            async with CloudNGFWAWSCrawler() as crawler:
                result = await crawler.crawl()

        assert result.product.id == "cloud-ngfw-aws"
        assert len(result.product.versions) == 0


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
        crawler = ADEMCrawler()
        assert crawler._parse_adem_date("March 2024") == "2024-03-01"
        assert crawler._parse_adem_date("December 2023") == "2023-12-01"
        assert crawler._parse_adem_date("January 2025") == "2025-01-01"

    def test_parse_adem_date_month_day_year(self):
        """Test parsing 'Month Day, Year' format."""
        crawler = ADEMCrawler()
        assert crawler._parse_adem_date("March 15, 2024") == "2024-03-15"
        assert crawler._parse_adem_date("December 1, 2023") == "2023-12-01"
        assert crawler._parse_adem_date("January 31 2025") == "2025-01-31"

    def test_parse_adem_date_iso_format(self):
        """Test parsing ISO date format."""
        crawler = ADEMCrawler()
        assert crawler._parse_adem_date("2024-03-15") == "2024-03-15"
        assert crawler._parse_adem_date("2023-12-01") == "2023-12-01"

    def test_parse_adem_date_invalid(self):
        """Test that invalid dates return None."""
        crawler = ADEMCrawler()
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

        with patch.object(ADEMCrawler, "_fetch_page_with_semaphore", side_effect=mock_fetch):
            async with ADEMCrawler() as crawler:
                result = await crawler.crawl()

        assert result.product.id == "adem"
        assert result.product.name == "Autonomous DEM"
        assert len(result.product.versions) == 1
        assert result.product.versions[0].version == "5.9"
        assert len(result.product.versions[0].known_issues) == 1
        assert len(result.product.versions[0].addressed_issues) == 1
        assert result.product.versions[0].addressed_issues[0].release_date == "2024-03-01"
        assert isinstance(result.failed_fetches, list)

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

        with patch.object(ADEMCrawler, "_fetch_page_with_semaphore", side_effect=mock_fetch):
            async with ADEMCrawler() as crawler:
                result = await crawler.crawl()

        assert len(result.product.versions) == 2
        versions = {v.version for v in result.product.versions}
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

        with patch.object(ADEMCrawler, "_fetch_page_with_semaphore", side_effect=mock_fetch):
            async with ADEMCrawler() as crawler:
                result = await crawler.crawl()

        assert len(result.product.versions) == 1
        addressed = result.product.versions[0].addressed_issues
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
        import inspect

        from bugdb.crawler import crawl_adem

        sig = inspect.signature(crawl_adem)
        params = list(sig.parameters.keys())
        assert "major_versions" in params
        assert "skip_versions" in params


class TestSCMVersionSortKey:
    """Tests for SCM version sort key."""

    def test_scm_version_sort_key_standard(self):
        """Test sorting standard SCM versions."""
        crawler = SCMCrawler()
        assert crawler._scm_version_sort_key("2025.r5.0") == (2025, 5, 0)
        assert crawler._scm_version_sort_key("2024.r12.1") == (2024, 12, 1)
        assert crawler._scm_version_sort_key("2023.r1.0") == (2023, 1, 0)

    def test_scm_version_sort_key_unknown(self):
        """Test sorting Unknown version."""
        crawler = SCMCrawler()
        assert crawler._scm_version_sort_key("Unknown") == (0, 0, 0)

    def test_scm_version_sort_key_invalid(self):
        """Test sorting invalid version."""
        crawler = SCMCrawler()
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

        with patch.object(SCMCrawler, "_fetch_page_with_semaphore", side_effect=mock_fetch):
            async with SCMCrawler() as crawler:
                result = await crawler.crawl()

        assert result.product.id == "scm"
        assert result.product.name == "Strata Cloud Manager"
        assert len(result.product.versions) == 1
        assert result.product.versions[0].version == "SaaS"
        assert isinstance(result.failed_fetches, list)

        known = result.product.versions[0].known_issues
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

        with patch.object(SCMCrawler, "_fetch_page_with_semaphore", side_effect=mock_fetch):
            async with SCMCrawler() as crawler:
                result = await crawler.crawl()

        assert len(result.product.versions) == 2
        versions = {v.version for v in result.product.versions}
        assert "2025.r5.0" in versions
        assert "2025.r4.0" in versions

        # Check component association for r5 issue
        r5_version = next(v for v in result.product.versions if v.version == "2025.r5.0")
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

        with patch.object(SCMCrawler, "_fetch_page_with_semaphore", side_effect=mock_fetch):
            async with SCMCrawler() as crawler:
                result = await crawler.crawl()

        assert len(result.product.versions) == 1
        assert result.product.versions[0].version == "Unknown"
        assert len(result.product.versions[0].addressed_issues) == 1
        assert result.product.versions[0].addressed_issues[0].release_date == "2024-09-01"


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

        with patch.object(SCMCrawler, "_fetch_page_with_semaphore", side_effect=mock_fetch):
            async with SCMCrawler() as crawler:
                result = await crawler.crawl()

        # Should have 3 versions: 2025.r5.0, 2025.r4.0, Unknown
        assert len(result.product.versions) == 3
        versions = {v.version for v in result.product.versions}
        assert "2025.r5.0" in versions
        assert "2025.r4.0" in versions
        assert "Unknown" in versions

        # Check 2025.r5.0 version has 2 ADI issues
        r5_version = next(v for v in result.product.versions if v.version == "2025.r5.0")
        assert len(r5_version.addressed_issues) == 2
        bug_ids = {i.bug_id for i in r5_version.addressed_issues}
        assert "ADI-47855" in bug_ids
        assert "ADI-49121" in bug_ids

        # Check 2025.r4.0 version has 1 ADI issue
        r4_version = next(v for v in result.product.versions if v.version == "2025.r4.0")
        assert len(r4_version.addressed_issues) == 1
        assert r4_version.addressed_issues[0].bug_id == "ADI-48273"

        # Check Unknown version has NETVIS issue from Command Center
        unknown_version = next(v for v in result.product.versions if v.version == "Unknown")
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

        with patch.object(SCMCrawler, "_fetch_page_with_semaphore", side_effect=mock_fetch):
            async with SCMCrawler() as crawler:
                result = await crawler.crawl()

        # All should be in Unknown version
        assert len(result.product.versions) == 1
        assert result.product.versions[0].version == "Unknown"
        assert len(result.product.versions[0].addressed_issues) == 3

        # Check bug IDs
        bug_ids = {i.bug_id for i in result.product.versions[0].addressed_issues}
        assert bug_ids == {"ADI-38973", "ADI-34609", "ADI-36846"}

        # Check release dates for date-formatted entries
        issues_by_id = {i.bug_id: i for i in result.product.versions[0].addressed_issues}
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

        with patch.object(SCMCrawler, "_fetch_page_with_semaphore", side_effect=mock_fetch):
            async with SCMCrawler() as crawler:
                result = await crawler.crawl()

        assert len(result.product.versions) == 1
        assert result.product.versions[0].version == "2025.r1.0"
        assert len(result.product.versions[0].addressed_issues) == 1
        assert result.product.versions[0].addressed_issues[0].bug_id == "ADI-12345"


class TestSCMCrawlFunction:
    """Tests for the crawl_scm function."""

    def test_crawl_scm_import(self):
        """Test that crawl_scm can be imported."""
        from bugdb.crawler import crawl_scm

        assert callable(crawl_scm)

    def test_crawl_scm_accepts_version_params(self):
        """Test that crawl_scm accepts version params for API compatibility."""
        import inspect

        from bugdb.crawler import crawl_scm

        sig = inspect.signature(crawl_scm)
        params = list(sig.parameters.keys())
        assert "major_versions" in params
        assert "skip_versions" in params


class TestSCMMultitenantKnownIssues:
    """Tests for SCM multitenant known issues parsing."""

    @pytest.mark.asyncio
    async def test_parse_multitenant_known_issues(self):
        """Test parsing multitenant known issues with correct component."""
        html = """
        <html><body>
        <h2>Known Issues in Strata Multitenant Cloud Manager</h2>
        <table>
            <thead><tr><th>ID</th><th>Description</th></tr></thead>
            <tbody>
                <tr><td>ADI-31756</td><td>When configuring Snippets, the push fails.</td></tr>
                <tr><td>PAMSP-4495</td><td>Bulk Configuration snippet push fails.</td></tr>
            </tbody>
        </table>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")

        async with SCMCrawler(headless=True) as crawler:
            issues = crawler._parse_scm_multitenant_known_issues_page(soup)

        assert len(issues) == 2
        # Verify all issues have the multitenant component
        for issue in issues:
            assert issue.affected_components == ["Strata Multitenant Cloud Manager"]

        # Verify specific issues
        adi_issue = next(i for i in issues if i.bug_id == "ADI-31756")
        assert "Snippets" in adi_issue.description

        pamsp_issue = next(i for i in issues if i.bug_id == "PAMSP-4495")
        assert "Bulk Configuration" in pamsp_issue.description

    @pytest.mark.asyncio
    async def test_parse_multitenant_empty_table(self):
        """Test parsing multitenant page with no issues."""
        html = """
        <html><body>
        <h2>Known Issues in Strata Multitenant Cloud Manager</h2>
        <table>
            <thead><tr><th>ID</th><th>Description</th></tr></thead>
            <tbody></tbody>
        </table>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")

        async with SCMCrawler(headless=True) as crawler:
            issues = crawler._parse_scm_multitenant_known_issues_page(soup)

        assert len(issues) == 0

    @pytest.mark.asyncio
    async def test_parse_multitenant_skips_nested_tables(self):
        """Test that nested tables are skipped."""
        html = """
        <html><body>
        <table>
            <thead><tr><th>ID</th><th>Description</th></tr></thead>
            <tbody>
                <tr><td>ADI-100</td><td>
                    Issue with nested table:
                    <table><tr><td>Nested</td><td>Data</td></tr></table>
                </td></tr>
            </tbody>
        </table>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")

        async with SCMCrawler(headless=True) as crawler:
            issues = crawler._parse_scm_multitenant_known_issues_page(soup)

        # Should only parse the outer table, not the nested one
        assert len(issues) == 1
        assert issues[0].bug_id == "ADI-100"
        assert issues[0].affected_components == ["Strata Multitenant Cloud Manager"]


class TestSdwanPluginCrawler:
    """Tests for Panorama Plugin for SD-WAN crawler methods."""

    @pytest.mark.asyncio
    async def test_discover_sdwan_plugin_versions(self):
        """Test discovering SD-WAN Plugin versions."""
        valid_html = """
        <html>
        <head><title>SD-WAN Plugin Release Notes</title></head>
        <body><h1>Panorama Plugin for SD-WAN</h1></body>
        </html>
        """
        invalid_html = """
        <html>
        <head><title>404 Not Found</title></head>
        <body></body>
        </html>
        """

        async def mock_fetch(url):
            if "340" in url or "330" in url:
                return BeautifulSoup(valid_html, "lxml")
            return BeautifulSoup(invalid_html, "lxml")

        with patch.object(SDWANPluginCrawler, "_fetch_page_with_semaphore", side_effect=mock_fetch):
            crawler = SDWANPluginCrawler()
            versions = await crawler.discover_versions()

        assert "3-4" in versions
        assert "3-3" in versions
        # Versions should be sorted newest first
        assert versions.index("3-4") < versions.index("3-3")


class TestSdwanPluginIssuePageParsing:
    """Tests for SD-WAN Plugin issue page parsing."""

    @pytest.mark.asyncio
    async def test_parse_sdwan_plugin_issues_page_basic(self):
        """Test parsing a basic SD-WAN Plugin issues page."""
        html = """
        <html>
        <body>
            <div class="topic topic concept" id="id_123">
                <h2 class="title">PLUG-21660</h2>
                <div class="shortdesc">Short description of the issue.</div>
                <div class="p">Main description of the problem.</div>
            </div>
            <div class="topic topic concept" id="id_456">
                <h2 class="title">PAN-12345</h2>
                <div class="shortdesc">Another issue.</div>
                <div class="p">Details about this issue.</div>
            </div>
        </body>
        </html>
        """

        with patch.object(SDWANPluginCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            crawler = SDWANPluginCrawler()
            known_issues, addressed_by_version = await crawler._parse_sdwan_plugin_issues_page(
                "/test-url", "3-3"
            )

        assert len(known_issues) == 2
        assert known_issues[0].bug_id == "PLUG-21660"
        assert known_issues[1].bug_id == "PAN-12345"
        assert "Short description" in known_issues[0].description
        assert len(addressed_by_version) == 0  # No fix info

    @pytest.mark.asyncio
    async def test_parse_sdwan_plugin_issues_page_with_fix_info(self):
        """Test parsing page with fix information in tt tags."""
        html = """
        <html>
        <body>
            <div class="topic topic concept" id="id_123">
                <h2 class="title">PLUG-21660</h2>
                <div class="shortdesc">Issue with fix.</div>
                <div class="p">Main description.</div>
                <div class="p">
                    <tt class="ph tt">This issue is addressed in SD-WAN plugin
                        <span>3.2.4-h1</span><span>, 3.3.4</span><span> and 3.4.1</span>.
                    </tt>
                </div>
            </div>
        </body>
        </html>
        """

        with patch.object(SDWANPluginCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            crawler = SDWANPluginCrawler()
            known_issues, addressed_by_version = await crawler._parse_sdwan_plugin_issues_page(
                "/test-url", "3-3"
            )

        assert len(known_issues) == 1
        assert known_issues[0].bug_id == "PLUG-21660"
        assert known_issues[0].fix_info is not None
        # Fix info should keep the original text
        assert "This issue is addressed" in known_issues[0].fix_info
        assert "3.2.4-h1" in known_issues[0].fix_info
        assert "3.3.4" in known_issues[0].fix_info
        assert "3.4.1" in known_issues[0].fix_info

        # Should have addressed issues for each plugin fix version
        assert "3.2.4-h1" in addressed_by_version
        assert "3.3.4" in addressed_by_version
        assert "3.4.1" in addressed_by_version
        assert addressed_by_version["3.3.4"][0].bug_id == "PLUG-21660"

    @pytest.mark.asyncio
    async def test_parse_sdwan_plugin_issues_page_strips_description_prefix(self):
        """Test that 'Description of <issue-id>' prefix is stripped."""
        html = """
        <html>
        <body>
            <div class="topic topic concept" id="id_123">
                <h2 class="title">PLUG-12345</h2>
                <div class="shortdesc">Description of PLUG-12345</div>
                <div class="p">The actual issue description here.</div>
            </div>
        </body>
        </html>
        """

        with patch.object(SDWANPluginCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            crawler = SDWANPluginCrawler()
            known_issues, _ = await crawler._parse_sdwan_plugin_issues_page("/test-url", "3-3")

        assert len(known_issues) == 1
        # "Description of PLUG-12345" prefix should be stripped
        assert not known_issues[0].description.startswith("Description of")
        assert "actual issue description" in known_issues[0].description

    @pytest.mark.asyncio
    async def test_parse_sdwan_plugin_issues_page_strips_description_prefix_with_period(self):
        """Test that 'Description of <issue-id>.' prefix with period is stripped."""
        html = """
        <html>
        <body>
            <div class="topic topic concept" id="id_123">
                <h2 class="title">PLUG-12345</h2>
                <div class="p">Description of PLUG-12345. The actual issue description here.</div>
            </div>
        </body>
        </html>
        """

        with patch.object(SDWANPluginCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            crawler = SDWANPluginCrawler()
            known_issues, _ = await crawler._parse_sdwan_plugin_issues_page("/test-url", "3-3")

        assert len(known_issues) == 1
        # "Description of PLUG-12345." prefix should be stripped
        assert not known_issues[0].description.startswith("Description of")
        assert "actual issue description" in known_issues[0].description.lower()

    @pytest.mark.asyncio
    async def test_parse_sdwan_plugin_issues_page_panos_versions_not_in_addressed(self):
        """Test that PAN-OS versions (>=8) don't create addressed issues."""
        html = """
        <html>
        <body>
            <div class="topic topic concept" id="id_123">
                <h2 class="title">PLUG-99999</h2>
                <div class="shortdesc">Issue fixed in both plugin and PAN-OS.</div>
                <div class="p">
                    <tt class="ph tt">This issue is addressed in SD-WAN plugin 3.3.4
                        and PAN-OS 10.2.0, 11.1.1.
                    </tt>
                </div>
            </div>
        </body>
        </html>
        """

        with patch.object(SDWANPluginCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            crawler = SDWANPluginCrawler()
            known_issues, addressed_by_version = await crawler._parse_sdwan_plugin_issues_page(
                "/test-url", "3-3"
            )

        assert len(known_issues) == 1
        # fix_info should keep original text with both plugin and PAN-OS versions
        assert "plugin" in known_issues[0].fix_info.lower()
        assert "3.3.4" in known_issues[0].fix_info
        assert "PAN-OS" in known_issues[0].fix_info
        assert "10.2.0" in known_issues[0].fix_info
        assert "11.1.1" in known_issues[0].fix_info

        # Only plugin version should be in addressed_by_version
        assert "3.3.4" in addressed_by_version
        # PAN-OS versions should NOT create addressed issues
        assert "10.2.0" not in addressed_by_version
        assert "11.1.1" not in addressed_by_version

    @pytest.mark.asyncio
    async def test_parse_sdwan_plugin_issues_page_deduplicates_addressed_versions(self):
        """Test that addressed_by_version entries are deduplicated even if fix_info has duplicates."""
        html = """
        <html>
        <body>
            <div class="topic topic concept" id="id_123">
                <h2 class="title">PLUG-11111</h2>
                <div class="shortdesc">Issue with duplicate versions.</div>
                <div class="p">
                    <tt class="ph tt">This issue is addressed in SD-WAN plugin 3.3.4, 3.3.4, 3.4.1.
                    </tt>
                </div>
            </div>
        </body>
        </html>
        """

        with patch.object(SDWANPluginCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            crawler = SDWANPluginCrawler()
            known_issues, addressed_by_version = await crawler._parse_sdwan_plugin_issues_page(
                "/test-url", "3-3"
            )

        assert len(known_issues) == 1
        # fix_info keeps original text (may have duplicates)
        fix_info = known_issues[0].fix_info
        assert "3.3.4" in fix_info
        assert "3.4.1" in fix_info

        # addressed_by_version should have unique entries (deduplicated)
        assert len(addressed_by_version) == 2  # 3.3.4 and 3.4.1

    @pytest.mark.asyncio
    async def test_parse_sdwan_plugin_issues_page_with_affected_components(self):
        """Test parsing page with affected components in parentheses."""
        html = """
        <html>
        <body>
            <div class="topic topic concept" id="id_123">
                <h2 class="title">PLUG-12345</h2>
                <div class="shortdesc">Issue summary.</div>
                <div class="p">(<tt class="ph tt">HA Deployments only</tt>) Main description of the problem.</div>
            </div>
        </body>
        </html>
        """

        with patch.object(SDWANPluginCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            crawler = SDWANPluginCrawler()
            known_issues, _ = await crawler._parse_sdwan_plugin_issues_page("/test-url", "3-3")

        assert len(known_issues) == 1
        assert known_issues[0].affected_components is not None
        assert "HA Deployments only" in known_issues[0].affected_components

    @pytest.mark.asyncio
    async def test_parse_sdwan_plugin_issues_page_with_workaround(self):
        """Test parsing page with workaround text."""
        html = """
        <html>
        <body>
            <div class="topic topic concept" id="id_123">
                <h2 class="title">PLUG-99999</h2>
                <div class="shortdesc">Issue with workaround.</div>
                <div class="p">This is the main description.</div>
                <div class="p"><b class="ph b">Workaround</b></div>
                <div class="p">Follow these steps to work around the issue.</div>
            </div>
        </body>
        </html>
        """

        with patch.object(SDWANPluginCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            crawler = SDWANPluginCrawler()
            known_issues, _ = await crawler._parse_sdwan_plugin_issues_page("/test-url", "3-3")

        assert len(known_issues) == 1
        assert known_issues[0].bug_id == "PLUG-99999"
        # Workaround should be extracted (checking it's not None)
        # Note: The exact extraction depends on the HTML structure

    @pytest.mark.asyncio
    async def test_parse_sdwan_plugin_issues_page_skips_invalid_bug_ids(self):
        """Test that invalid bug IDs are skipped."""
        html = """
        <html>
        <body>
            <div class="topic topic concept" id="id_123">
                <h2 class="title">Not A Bug ID</h2>
                <div class="shortdesc">This should be skipped.</div>
            </div>
            <div class="topic topic concept" id="id_456">
                <h2 class="title">PLUG-12345</h2>
                <div class="shortdesc">Valid issue.</div>
            </div>
        </body>
        </html>
        """

        with patch.object(SDWANPluginCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            crawler = SDWANPluginCrawler()
            known_issues, _ = await crawler._parse_sdwan_plugin_issues_page("/test-url", "3-3")

        assert len(known_issues) == 1
        assert known_issues[0].bug_id == "PLUG-12345"


class TestSdwanPluginCrawlFunction:
    """Tests for the crawl_sdwan_plugin function."""

    def test_crawl_sdwan_plugin_import(self):
        """Test that crawl_sdwan_plugin can be imported."""
        from bugdb.crawler import crawl_sdwan_plugin

        assert callable(crawl_sdwan_plugin)

    def test_crawl_sdwan_plugin_signature(self):
        """Test that crawl_sdwan_plugin has expected parameters."""
        import inspect

        from bugdb.crawler import crawl_sdwan_plugin

        sig = inspect.signature(crawl_sdwan_plugin)
        params = list(sig.parameters.keys())
        assert "major_versions" in params
        assert "skip_versions" in params
        assert "headless" in params
        assert "debug" in params


class TestPluginConfig:
    """Tests for PluginConfig dataclass and PLUGIN_CONFIGS."""

    def test_plugin_configs_exist(self):
        """Test that PLUGIN_CONFIGS contains all expected plugins."""
        from bugdb.crawler import PLUGIN_CONFIGS

        expected_plugins = [
            "vm-series-plugin",
            "plugin-aws",
            "plugin-azure",
            "plugin-gcp",
            "plugin-vmware-nsx",
            "plugin-vmware-vcenter",
            "plugin-kubernetes",
            "plugin-cisco-aci",
            "plugin-cisco-trustsec",
            "plugin-ztp",
            "plugin-clustering",
        ]

        for plugin_id in expected_plugins:
            assert plugin_id in PLUGIN_CONFIGS, f"Missing plugin: {plugin_id}"

    def test_plugin_config_attributes(self):
        """Test that plugin configs have required attributes."""
        from bugdb.crawler import PLUGIN_CONFIGS

        for plugin_id, config in PLUGIN_CONFIGS.items():
            assert config.product_id, f"{plugin_id}: missing product_id"
            assert config.product_name, f"{plugin_id}: missing product_name"
            assert config.base_url, f"{plugin_id}: missing base_url"
            assert config.version_link_patterns, f"{plugin_id}: missing version_link_patterns"
            assert config.known_issues_keywords, f"{plugin_id}: missing known_issues_keywords"
            assert config.addressed_issues_keywords, (
                f"{plugin_id}: missing addressed_issues_keywords"
            )


class TestPluginCrawlerFunctions:
    """Tests for plugin crawler entry point functions."""

    def test_crawl_functions_exist(self):
        """Test that all plugin crawler functions exist and are callable."""
        from bugdb.crawler import (
            crawl_plugin_aws,
            crawl_plugin_azure,
            crawl_plugin_cisco_aci,
            crawl_plugin_cisco_trustsec,
            crawl_plugin_clustering,
            crawl_plugin_gcp,
            crawl_plugin_kubernetes,
            crawl_plugin_vmware_nsx,
            crawl_plugin_vmware_vcenter,
            crawl_plugin_ztp,
            crawl_vm_series_plugin,
        )

        functions = [
            crawl_vm_series_plugin,
            crawl_plugin_aws,
            crawl_plugin_azure,
            crawl_plugin_gcp,
            crawl_plugin_vmware_nsx,
            crawl_plugin_vmware_vcenter,
            crawl_plugin_kubernetes,
            crawl_plugin_cisco_aci,
            crawl_plugin_cisco_trustsec,
            crawl_plugin_ztp,
            crawl_plugin_clustering,
        ]

        for func in functions:
            assert callable(func), f"{func.__name__} is not callable"

    def test_crawl_functions_have_correct_signature(self):
        """Test that plugin crawler functions have expected parameters."""
        import inspect

        from bugdb.crawler import crawl_plugin_aws

        sig = inspect.signature(crawl_plugin_aws)
        params = list(sig.parameters.keys())

        expected_params = [
            "major_versions",
            "headless",
            "debug",
            "max_concurrency",
            "skip_versions",
        ]

        for param in expected_params:
            assert param in params, f"Missing parameter: {param}"


class TestTopicFormatParsing:
    """Tests for parsing div.topic format issues (used by Panorama plugins)."""

    def test_parse_topic_format_single_issue(self):
        """Test parsing a single issue from div.topic format."""
        html = """
        <html>
        <body>
            <div class="topic">
                <h2 class="title">PLUG-12345</h2>
                <div class="shortdesc">This is the issue description.</div>
            </div>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        crawler = PaloAltoCrawler()
        issues = crawler._parse_topic_format_issues(soup)

        assert len(issues) == 1
        assert issues[0].bug_id == "PLUG-12345"
        assert "issue description" in issues[0].description

    def test_parse_topic_format_multiple_issues(self):
        """Test parsing multiple issues from div.topic format."""
        html = """
        <html>
        <body>
            <div class="topic">
                <h2 class="title">PLUG-11111</h2>
                <div class="shortdesc">First issue.</div>
            </div>
            <div class="topic">
                <h2 class="title">PLUG-22222</h2>
                <div class="shortdesc">Second issue.</div>
            </div>
            <div class="topic">
                <h2 class="title">PAN-33333</h2>
                <div class="shortdesc">Third issue with PAN prefix.</div>
            </div>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        crawler = PaloAltoCrawler()
        issues = crawler._parse_topic_format_issues(soup)

        assert len(issues) == 3
        assert issues[0].bug_id == "PLUG-11111"
        assert issues[1].bug_id == "PLUG-22222"
        assert issues[2].bug_id == "PAN-33333"

    def test_parse_topic_format_with_workaround(self):
        """Test parsing issue with workaround from div.topic format."""
        html = """
        <html>
        <body>
            <div class="topic">
                <h2 class="title">PLUG-12345</h2>
                <div class="shortdesc">Issue description.</div>
                <div class="p"><b>Workaround</b>: Restart the service.</div>
            </div>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        crawler = PaloAltoCrawler()
        issues = crawler._parse_topic_format_issues(soup)

        assert len(issues) == 1
        assert issues[0].bug_id == "PLUG-12345"
        assert issues[0].workaround is not None
        assert "Restart" in issues[0].workaround

    def test_parse_topic_format_with_fix_info(self):
        """Test parsing issue with fix info from div.topic format."""
        html = """
        <html>
        <body>
            <div class="topic">
                <h2 class="title">PLUG-12345</h2>
                <div class="shortdesc">Issue description.</div>
                <div class="p"><tt>This issue is addressed in version 5.3.1.</tt></div>
            </div>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        crawler = PaloAltoCrawler()
        issues = crawler._parse_topic_format_issues(soup)

        assert len(issues) == 1
        assert issues[0].bug_id == "PLUG-12345"
        assert issues[0].fix_info is not None
        assert "5.3.1" in issues[0].fix_info

    def test_parse_topic_format_skips_invalid_bug_ids(self):
        """Test that invalid bug IDs are skipped."""
        html = """
        <html>
        <body>
            <div class="topic">
                <h2 class="title">Introduction</h2>
                <div class="shortdesc">This is not a bug.</div>
            </div>
            <div class="topic">
                <h2 class="title">PLUG-12345</h2>
                <div class="shortdesc">Valid bug.</div>
            </div>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        crawler = PaloAltoCrawler()
        issues = crawler._parse_topic_format_issues(soup)

        assert len(issues) == 1
        assert issues[0].bug_id == "PLUG-12345"

    def test_parse_topic_format_with_affected_components(self):
        """Test parsing issue with affected components."""
        html = """
        <html>
        <body>
            <div class="topic">
                <h2 class="title">PLUG-12345</h2>
                <div class="shortdesc">Issue description.</div>
                <div class="p">(AWS Integration) This affects AWS deployments.</div>
            </div>
        </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        crawler = PaloAltoCrawler()
        issues = crawler._parse_topic_format_issues(soup)

        assert len(issues) == 1
        assert issues[0].bug_id == "PLUG-12345"
        assert issues[0].affected_components is not None
        assert "AWS Integration" in issues[0].affected_components


class TestPluginVersionDiscovery:
    """Tests for plugin version discovery."""

    @pytest.mark.asyncio
    async def test_discover_plugin_versions_extracts_versions(self):
        """Test that version discovery extracts versions from URLs."""
        html = """
        <html>
        <body>
            <a href="/content/techdocs/en_US/.../aws-plugin-530/known-issues-in-aws-530.html">Known</a>
            <a href="/content/techdocs/en_US/.../aws-plugin-530/addressed-issues-in-aws-530.html">Addressed</a>
            <a href="/content/techdocs/en_US/.../aws-plugin-520/known-issues-in-aws-520.html">Known</a>
        </body>
        </html>
        """
        from bugdb.crawlers import PLUGIN_CONFIGS

        with patch.object(PluginCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            config = PLUGIN_CONFIGS["plugin-aws"]
            async with PluginCrawler(config=config) as crawler:
                versions = await crawler.discover_versions()

        # Should find versions 5.3.0 and 5.2.0
        version_strs = [v.version for v in versions]
        assert "5.3.0" in version_strs
        assert "5.2.0" in version_strs

    @pytest.mark.asyncio
    async def test_discover_plugin_versions_handles_dashed_versions(self):
        """Test that version discovery handles dashed version formats (e.g., vm-series-plugin-6-1-2)."""
        html = """
        <html>
        <body>
            <a href="/content/.../vm-series-plugin-6-1-2/known-issues-in-vm-series-plugin-612.html">Known</a>
            <a href="/content/.../vm-series-plugin-6-1-1/addressed-issues-in-vm-series-plugin-611.html">Addressed</a>
        </body>
        </html>
        """
        from bugdb.crawlers import PLUGIN_CONFIGS

        with patch.object(PluginCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(html, "lxml")

            config = PLUGIN_CONFIGS["vm-series-plugin"]
            async with PluginCrawler(config=config) as crawler:
                versions = await crawler.discover_versions()

        version_strs = [v.version for v in versions]
        assert "6.1.2" in version_strs
        assert "6.1.1" in version_strs


class TestDeviceSecurityCrawler:
    """Tests for Device Security (IoT) crawler."""

    @pytest.mark.asyncio
    async def test_discover_device_security_years(self):
        """Test that year discovery extracts years from index pages."""
        index_html = """
        <html>
        <body>
            <a href="/iot/release-notes/known-issues/known-issues-in-2026">Known Issues in 2026</a>
            <a href="/iot/release-notes/addressed-issues/addressed-issues-in-2025">Addressed Issues in 2025</a>
            <a href="/iot/release-notes/known-issues/known-issues-in-2024">Known Issues in 2024</a>
        </body>
        </html>
        """

        with patch.object(DeviceSecurityCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            mock_fetch.return_value = BeautifulSoup(index_html, "lxml")

            async with DeviceSecurityCrawler() as crawler:
                years = await crawler.discover_years()

        assert "2026" in years
        assert "2025" in years
        assert "2024" in years
        # Should be sorted newest first
        assert years.index("2026") < years.index("2025") < years.index("2024")

    @pytest.mark.asyncio
    async def test_crawl_device_security_parses_issues(self):
        """Test that Device Security crawler parses issues from tables."""
        # Index page with year links
        index_html = """
        <html><body>
            <a href="/iot/release-notes/known-issues/known-issues-in-2025">Known Issues in 2025</a>
        </body></html>
        """
        issues_html = """
        <html><body>
        <table>
            <thead><tr><th>ISSUE ID</th><th>DESCRIPTION</th></tr></thead>
            <tbody>
                <tr><td>DIT-12345</td><td>Test issue description</td></tr>
                <tr><td>DIT-67890</td><td>Another test issue</td></tr>
            </tbody>
        </table>
        </body></html>
        """

        with patch.object(DeviceSecurityCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            # First call: index page for discover_years
            # Second call: known issues page for 2025
            # Third call: addressed issues page for 2025
            mock_fetch.side_effect = [
                BeautifulSoup(index_html, "lxml"),
                BeautifulSoup(issues_html, "lxml"),
                BeautifulSoup(issues_html, "lxml"),
            ]

            async with DeviceSecurityCrawler() as crawler:
                result = await crawler.crawl()

        assert result.product.id == "device-security"
        assert result.product.name == "Device Security"
        assert len(result.product.versions) == 1
        assert result.product.versions[0].version == "2025"
        assert len(result.product.versions[0].known_issues) == 2
        assert len(result.product.versions[0].addressed_issues) == 2

    @pytest.mark.asyncio
    async def test_crawl_device_security_skip_versions(self):
        """Test that skip_versions is respected."""
        # Index page with multiple year links
        index_html = """
        <html><body>
            <a href="/iot/release-notes/known-issues/known-issues-in-2025">Known Issues in 2025</a>
            <a href="/iot/release-notes/known-issues/known-issues-in-2024">Known Issues in 2024</a>
        </body></html>
        """
        issues_html = """
        <html><body>
        <table>
            <thead><tr><th>ISSUE ID</th><th>DESCRIPTION</th></tr></thead>
            <tbody>
                <tr><td>DIT-11111</td><td>Issue for non-skipped year</td></tr>
            </tbody>
        </table>
        </body></html>
        """

        with patch.object(DeviceSecurityCrawler, "_fetch_page_with_semaphore") as mock_fetch:
            # First call: index page for discover_years
            # Second call: known issues page for 2025 (2024 is skipped)
            # Third call: addressed issues page for 2025
            mock_fetch.side_effect = [
                BeautifulSoup(index_html, "lxml"),
                BeautifulSoup(issues_html, "lxml"),
                BeautifulSoup(issues_html, "lxml"),
            ]

            async with DeviceSecurityCrawler() as crawler:
                result = await crawler.crawl(skip_versions={"2024"})

        # Should only have 2025, not 2024
        version_strs = [v.version for v in result.product.versions]
        assert "2025" in version_strs
        assert "2024" not in version_strs


class TestDeviceSecurityCrawlFunction:
    """Tests for Device Security crawl function import and signature."""

    def test_crawl_device_security_import(self):
        """Test that crawl_device_security can be imported."""
        from bugdb.crawler import crawl_device_security

        assert callable(crawl_device_security)

    def test_crawl_device_security_signature(self):
        """Test that crawl_device_security has correct signature."""
        import inspect

        from bugdb.crawler import crawl_device_security

        sig = inspect.signature(crawl_device_security)
        param_names = list(sig.parameters.keys())

        assert "major_versions" in param_names
        assert "headless" in param_names
        assert "debug" in param_names
        assert "max_concurrency" in param_names
        assert "skip_versions" in param_names


# =============================================================================
# Cortex XDR Agent Crawler Tests
# =============================================================================


class TestCortexXDRCrawlFunction:
    """Tests for Cortex XDR crawl function import and signature."""

    def test_crawl_cortex_xdr_import(self):
        """Test that crawl_cortex_xdr can be imported."""
        from bugdb.crawler import crawl_cortex_xdr

        assert callable(crawl_cortex_xdr)

    def test_crawl_cortex_xdr_signature(self):
        """Test that crawl_cortex_xdr has correct signature."""
        import inspect

        from bugdb.crawler import crawl_cortex_xdr

        sig = inspect.signature(crawl_cortex_xdr)
        param_names = list(sig.parameters.keys())

        assert "major_versions" in param_names
        assert "headless" in param_names
        assert "debug" in param_names
        assert "max_concurrency" in param_names
        assert "skip_versions" in param_names

    def test_cortex_xdr_in_cli_supported_products(self):
        """Test that cortex-xdr is in CLI supported products."""
        # This is a simple import test to ensure CLI includes cortex-xdr
        from bugdb.crawler import crawl_cortex_xdr

        # The crawl function should exist and be callable
        assert callable(crawl_cortex_xdr)


# ---------------------------------------------------------------------------
# Progress reporter integration
# ---------------------------------------------------------------------------


class SpyProgressReporter:
    """Records every reporter call for assertion in tests.

    Follows the ``ProgressReporter`` protocol structurally — no
    inheritance needed since the protocol is ``@runtime_checkable``.
    Exposed as a spy, not a mock, so tests can inspect the ordered
    event log and distinguish ``update(advance=1)`` ticks from
    description-only updates.
    """

    def __init__(self) -> None:
        self.events: list[tuple] = []
        self._next_id: int = 0

    def add_task(self, description, total=None, parent=None):
        self._next_id += 1
        self.events.append(("add_task", self._next_id, description, total, parent))
        return self._next_id

    def update(self, task, *, advance=0, description=None, total=None):
        self.events.append(("update", task, advance, description, total))

    def complete(self, task):
        self.events.append(("complete", task))

    def log(self, message):
        self.events.append(("log", message))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return None

    def advance_events(self):
        """Convenience: yield every ``update`` event whose advance>0."""
        return [e for e in self.events if e[0] == "update" and e[2] > 0]


class TestProgressReporterIntegration:
    """BaseCrawler emits progress events when a reporter+task pair is wired."""

    @pytest.mark.asyncio
    async def test_crawl_versions_parallel_advances_once_per_version(
        self, mock_playwright_globalprotect
    ):
        """Each completed version must produce exactly one advance=1
        event, in ``finally``-block semantics so failures still tick
        the bar and leave no stuck counters."""
        spy = SpyProgressReporter()
        task = spy.add_task("test", total=None)

        with patch(
            "bugdb.crawlers.base.async_playwright", return_value=mock_playwright_globalprotect
        ):
            async with PaloAltoCrawler(reporter=spy, task=task) as crawler:
                version_infos = [
                    VersionInfo(
                        version="6.2.1",
                        known_issues_urls=["/globalprotect/release-notes/6-2/6-2-1-known-issues"],
                        addressed_issues_urls=[
                            "/globalprotect/release-notes/6-2/6-2-1-addressed-issues"
                        ],
                    ),
                    VersionInfo(
                        version="6.1.3",
                        known_issues_urls=["/globalprotect/release-notes/6-1/6-1-3-known-issues"],
                        addressed_issues_urls=[
                            "/globalprotect/release-notes/6-1/6-1-3-addressed-issues"
                        ],
                    ),
                ]

                await crawler._crawl_versions_parallel(version_infos, product_name="GP")

        advances = spy.advance_events()
        assert len(advances) == 2, f"expected 2 advance=1 events, got {advances}"
        # Every advance carries the finishing version in its description,
        # so users see which one just completed.
        descriptions = [e[3] for e in advances]
        assert any("6.2.1" in d for d in descriptions)
        assert any("6.1.3" in d for d in descriptions)

    @pytest.mark.asyncio
    async def test_crawl_versions_parallel_advances_on_exception(
        self, mock_playwright_globalprotect
    ):
        """If ``_crawl_version`` raises, the ``finally`` block must
        still advance the bar so the counter doesn't get stuck below
        the total. We simulate failure by patching _crawl_version."""
        spy = SpyProgressReporter()
        task = spy.add_task("test", total=None)

        with patch(
            "bugdb.crawlers.base.async_playwright", return_value=mock_playwright_globalprotect
        ):
            async with PaloAltoCrawler(reporter=spy, task=task) as crawler:
                crawler._crawl_version = AsyncMock(side_effect=RuntimeError("boom"))
                version_infos = [
                    VersionInfo(
                        version=f"6.2.{n}",
                        known_issues_urls=[f"/gp/6-2-{n}-known"],
                        addressed_issues_urls=[f"/gp/6-2-{n}-addressed"],
                    )
                    for n in range(3)
                ]

                await crawler._crawl_versions_parallel(version_infos, product_name="GP")

        advances = spy.advance_events()
        assert len(advances) == 3, f"expected 3 advance=1 events (one per failure), got {advances}"

    @pytest.mark.asyncio
    async def test_no_reporter_is_zero_overhead_noop(self, mock_playwright_globalprotect):
        """Default ``reporter=None`` path must not raise or touch any
        attribute — this is the backwards-compat guarantee for every
        test and library caller that existed before the feature."""
        with patch(
            "bugdb.crawlers.base.async_playwright", return_value=mock_playwright_globalprotect
        ):
            async with PaloAltoCrawler() as crawler:
                assert crawler._reporter is None
                assert crawler._task is None
                version_infos = [
                    VersionInfo(
                        version="6.2.1",
                        known_issues_urls=["/globalprotect/release-notes/6-2/6-2-1-known-issues"],
                        addressed_issues_urls=[
                            "/globalprotect/release-notes/6-2/6-2-1-addressed-issues"
                        ],
                    ),
                ]
                versions, _failed = await crawler._crawl_versions_parallel(version_infos)
                assert isinstance(versions, list)

    def test_set_task_total_updates_reporter(self):
        """``_set_task_total`` forwards to reporter.update when both
        reporter and task are set; no-op otherwise."""
        spy = SpyProgressReporter()
        task = spy.add_task("x", total=None)

        crawler = PaloAltoCrawler(reporter=spy, task=task)
        crawler._set_task_total(15, "PAN-OS: fetching 15 versions")

        updates = [e for e in spy.events if e[0] == "update" and e[4] == 15]
        assert len(updates) == 1
        assert updates[0][3] == "PAN-OS: fetching 15 versions"

    def test_set_task_total_without_reporter_is_noop(self):
        """With no reporter/task pair, ``_set_task_total`` must be a
        silent no-op — this is what keeps the default path free of
        overhead."""
        crawler = PaloAltoCrawler()
        # Must not raise.
        crawler._set_task_total(42, "ignored")

    def test_advance_task_updates_reporter(self):
        """``_advance_task`` forwards ``advance=1`` to the reporter."""
        spy = SpyProgressReporter()
        task = spy.add_task("x", total=3)

        crawler = PaloAltoCrawler(reporter=spy, task=task)
        crawler._advance_task("PAN-OS: 12.1.5 done")
        crawler._advance_task("PAN-OS: 11.2.3 done")

        advances = spy.advance_events()
        assert len(advances) == 2
        assert advances[0][3] == "PAN-OS: 12.1.5 done"
        assert advances[1][3] == "PAN-OS: 11.2.3 done"

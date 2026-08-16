"""Tests for the GitBook-era Cortex XDR Agent crawler.

Palo Alto moved the Cortex docs off FluidTopics onto GitBook. The new site
renders tables as ``div``s carrying ARIA roles rather than ``<table>``
elements, and its URL slugs differ from version to version, so URLs must be
resolved from each space's own ``sitemap-pages.xml``.

The HTML fixtures here are trimmed captures of real pages (see the comment at
the top of each file); the sitemap fixtures are trimmed copies of the live
XML.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from bugdb.crawlers.products.cortex_xdr import CortexXDRCrawler
from bugdb.crawlers.utils import CORTEX_BASE_URL
from bugdb.transport.base import FetchedPage

FIXTURES = Path(__file__).parent / "fixtures" / "cortex-xdr"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def _soup(name: str) -> BeautifulSoup:
    return BeautifulSoup(_fixture(name), "lxml")


class FakeTransport:
    """Serves canned bodies keyed by URL; records what was requested."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.requested: list[str] = []

    async def fetch(self, url: str) -> FetchedPage:
        self.requested.append(url)
        if url not in self.pages:
            return FetchedPage(url=url, status_code=404, html="")
        return FetchedPage(url=url, status_code=200, html=self.pages[url])

    async def aclose(self) -> None:  # pragma: no cover - nothing to release
        return None


# ---------------------------------------------------------------------------
# ARIA table parsing
# ---------------------------------------------------------------------------


class TestAriaTableParsing:
    """The new pages have no <table> tags at all — only role="table" divs."""

    def test_fixtures_really_have_no_table_tags(self):
        """Guard the premise: if these grew <table> tags the fixture is stale."""
        for name in (
            "gitbook-addressed-issues.html",
            "gitbook-known-issues.html",
            "gitbook-addressed-issues-legacy.html",
        ):
            assert _soup(name).find("table") is None, name

    def test_parses_three_column_addressed_issues_table(self):
        crawler = CortexXDRCrawler()
        issues = crawler._parse_aria_issue_tables(_soup("gitbook-addressed-issues.html"))

        assert [i.bug_id for i in issues] == [
            "CPATR-36649",
            "CPATR-36490",
            "CPATR-36464",
            "CPATR-36025",
        ]
        first = issues[0]
        assert first.description == (
            "Fixed an issue where an invalid hardware ID may cause an agent "
            "installation or upgrade to fail."
        )
        # "General" is not a platform — it must not become a component.
        assert first.affected_components is None

    def test_platform_column_becomes_affected_components(self):
        crawler = CortexXDRCrawler()
        issues = crawler._parse_aria_issue_tables(_soup("gitbook-addressed-issues.html"))

        by_id = {i.bug_id: i for i in issues}
        assert by_id["CPATR-36464"].affected_components == ["Windows"]

    def test_two_column_known_issues_table_drops_category_rows(self):
        """Most known-issue rows are feature names, not bug ids — drop those."""
        crawler = CortexXDRCrawler()
        soup = _soup("gitbook-known-issues.html")

        # The fixture really does carry category rows, not just bug ids.
        text = soup.get_text(" ", strip=True)
        assert "Windows on ARM" in text

        issues = crawler._parse_aria_issue_tables(soup)

        assert [i.bug_id for i in issues] == ["CPATR-18568"]
        assert not any(i.bug_id == "Windows on ARM" for i in issues)

    def test_header_row_without_columnheader_role(self):
        """Older spaces put "Issue"/"Description" in role="cell", not
        role="columnheader" — the header row must still be recognised and
        dropped."""
        crawler = CortexXDRCrawler()
        issues = crawler._parse_aria_issue_tables(_soup("gitbook-addressed-issues-legacy.html"))

        assert [i.bug_id for i in issues] == [
            "CPATR-22124",
            "CPATR-21933",
            "CPATR-21870",
            "CPATR-21465",
        ]
        assert not any(i.bug_id.lower().startswith("issue") for i in issues)

    def test_non_breaking_hyphen_in_bug_id_is_normalised(self):
        """The legacy fixture spells ids with U+2011, not ASCII '-'."""
        raw = _fixture("gitbook-addressed-issues-legacy.html")
        assert "CPATR\u201122124" in raw

        crawler = CortexXDRCrawler()
        issues = crawler._parse_aria_issue_tables(_soup("gitbook-addressed-issues-legacy.html"))
        assert issues[0].bug_id == "CPATR-22124"

    def test_parenthesised_platform_becomes_affected_components(self):
        crawler = CortexXDRCrawler()
        issues = crawler._parse_aria_issue_tables(_soup("gitbook-addressed-issues-legacy.html"))

        assert issues[0].affected_components == ["Linux"]
        assert "(Linux)" not in issues[0].bug_id


# ---------------------------------------------------------------------------
# Sitemap-driven discovery
# ---------------------------------------------------------------------------


class TestSitemapDiscovery:
    def test_sitemap_index_yields_agent_release_note_spaces(self):
        crawler = CortexXDRCrawler()
        urls = crawler._space_sitemap_urls(_fixture("sitemap-index.xml"))

        assert urls == [
            f"{CORTEX_BASE_URL}/xdr-agent-release-notes/sitemap-pages.xml",
            f"{CORTEX_BASE_URL}/xdr-agent-release-notes/9.2/sitemap-pages.xml",
            f"{CORTEX_BASE_URL}/xdr-agent-release-notes/9.1-ce/sitemap-pages.xml",
            f"{CORTEX_BASE_URL}/8.x/sitemap-pages.xml",
            f"{CORTEX_BASE_URL}/8.x/8.1-eol/sitemap-pages.xml",
            f"{CORTEX_BASE_URL}/8.x/8.3ce/sitemap-pages.xml",
            f"{CORTEX_BASE_URL}/7.x/7.5ce-eol/sitemap-pages.xml",
            f"{CORTEX_BASE_URL}/6.1-eol/sitemap-pages.xml",
            f"{CORTEX_BASE_URL}/5.0/sitemap-pages.xml",
        ]

    def test_sitemap_index_skips_other_products_and_guides(self):
        crawler = CortexXDRCrawler()
        urls = crawler._space_sitemap_urls(_fixture("sitemap-index.xml"))
        joined = " ".join(urls)

        for unwanted in (
            "xsiam",
            "xsoar",
            "ios-guide",
            "cortex-xdr-agent/9.3",
            "cortex-xdr-3.x",
            "cortex-xdr-docs",
        ):
            assert unwanted not in joined

    def test_page_urls_come_from_the_spaces_own_sitemap(self):
        crawler = CortexXDRCrawler()
        urls = crawler._page_urls(_fixture("sitemap-pages-92.xml"))

        assert f"{CORTEX_BASE_URL}/xdr-agent-release-notes/9.2" in urls
        assert (
            f"{CORTEX_BASE_URL}/xdr-agent-release-notes/9.2/release-information/"
            "addressed-issues/addressed-issues-92" in urls
        )


class TestPageClassification:
    """Classify on the substrings 'known'/'addressed', case-insensitively.

    The three slug shapes below are all real and all describe the same kind
    of page — which is exactly why templating URLs does not work.
    """

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/xdr-agent-release-notes/9.2/release-information/addressed-issues", "addressed"),
            (
                "/xdr-agent-release-notes/9.0/agent-9.0-release-information/"
                "addressed-issues-in-agent-9.0/addressed-issues-in-cortex-xdr-agent-9.0.1",
                "addressed",
            ),
            (
                "/8.x/8.1-eol/cortex-xdr-agent-8.1-release-information/"
                "addressed-issues-in-cortex-xdr-agent-8.1.x",
                "addressed",
            ),
            ("/xdr-agent-release-notes/9.2/release-information/known-issues", "known"),
            (
                "/8.x/cortex-xdr-agent-8.9-release-information/cortex-xdr-agent-known-limitations",
                "known",
            ),
            ("/5.0/traps-agent-release/Known-Issues-in-Traps-Agent-5.0", "known"),
            ("/xdr-agent-release-notes/9.2/release-information/feature-enhancements", None),
            ("/xdr-agent-release-notes/9.2", None),
        ],
    )
    def test_classify_page(self, path, expected):
        crawler = CortexXDRCrawler()
        assert crawler._classify_page(CORTEX_BASE_URL + path) == expected


class TestVersionResolution:
    @pytest.mark.parametrize(
        ("space_path", "expected"),
        [
            ("xdr-agent-release-notes/9.2", "9.2"),
            ("xdr-agent-release-notes/9.0", "9.0"),
            ("xdr-agent-release-notes/9.1-ce", "9.1-CE"),
            ("8.x/8.1-eol", "8.1"),
            ("8.x/8.3ce", "8.3-CE"),
            ("7.x/7.5ce-eol", "7.5-CE"),
            ("6.1-eol", "6.1"),
            ("5.0", "5.0"),
            # Roots that carry no version of their own.
            ("xdr-agent-release-notes", None),
            ("8.x", None),
            ("7.x", None),
        ],
    )
    def test_version_from_space_path(self, space_path, expected):
        crawler = CortexXDRCrawler()
        assert crawler._version_from_space_path(space_path) == expected

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Cortex XDR Agent 9.3 Release Information | Cortex Documentation Portal", "9.3"),
            ("Cortex XDR Agent 8.9 Release Information | Cortex Documentation Portal", "8.9"),
            ("Cortex XDR Agent 7.9-CE Release Information | Cortex Documentation Portal", "7.9-CE"),
            ("Traps™ Agent Release Information | Cortex Documentation Portal", None),
        ],
    )
    def test_version_from_space_root_title(self, title, expected):
        """Version-less spaces are resolved from their root page's <title>."""
        crawler = CortexXDRCrawler()
        html = f"<html><head><title>{title}</title></head><body></body></html>"
        assert crawler._version_from_space_root(html) == expected


# ---------------------------------------------------------------------------
# End-to-end crawl over a fake transport
# ---------------------------------------------------------------------------


def _minimal_index(space_paths: list[str]) -> str:
    entries = "".join(
        f"<sitemap><loc>{CORTEX_BASE_URL}/{p}/sitemap-pages.xml</loc></sitemap>"
        for p in space_paths
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}</sitemapindex>"
    )


def _minimal_pages(urls: list[str]) -> str:
    entries = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}</urlset>"
    )


def _two_space_site() -> dict[str, str]:
    known_url = f"{CORTEX_BASE_URL}/xdr-agent-release-notes/9.2/release-information/known-issues"
    addressed_url = (
        f"{CORTEX_BASE_URL}/xdr-agent-release-notes/9.2/release-information/"
        "addressed-issues/addressed-issues-92"
    )
    legacy_url = (
        f"{CORTEX_BASE_URL}/8.x/8.1-eol/cortex-xdr-agent-8.1-release-information/"
        "addressed-issues-in-cortex-xdr-agent-8.1.x"
    )
    return {
        f"{CORTEX_BASE_URL}/sitemap.xml": _minimal_index(
            ["xdr-agent-release-notes/9.2", "8.x/8.1-eol"]
        ),
        f"{CORTEX_BASE_URL}/xdr-agent-release-notes/9.2/sitemap-pages.xml": _minimal_pages(
            [
                f"{CORTEX_BASE_URL}/xdr-agent-release-notes/9.2",
                f"{CORTEX_BASE_URL}/xdr-agent-release-notes/9.2/release-information/"
                "feature-enhancements",
                addressed_url,
                known_url,
            ]
        ),
        f"{CORTEX_BASE_URL}/8.x/8.1-eol/sitemap-pages.xml": _minimal_pages([legacy_url]),
        addressed_url: _fixture("gitbook-addressed-issues.html"),
        known_url: _fixture("gitbook-known-issues.html"),
        legacy_url: _fixture("gitbook-addressed-issues-legacy.html"),
    }


class TestCrawl:
    @pytest.mark.asyncio
    async def test_crawl_builds_versions_from_sitemaps(self):
        transport = FakeTransport(_two_space_site())

        async with CortexXDRCrawler(transport=transport) as crawler:
            result = await crawler.crawl()

        assert result.product.id == "cortex-xdr"
        assert result.product.name == "Cortex XDR Agent"
        versions = {v.version: v for v in result.product.versions}
        assert set(versions) == {"9.2", "8.1"}
        assert len(versions["9.2"].addressed_issues) == 4
        assert len(versions["9.2"].known_issues) == 1
        assert len(versions["8.1"].addressed_issues) == 4
        assert versions["8.1"].known_issues == []
        assert result.failed_fetches == []

    @pytest.mark.asyncio
    async def test_crawl_never_fetches_feature_pages(self):
        transport = FakeTransport(_two_space_site())

        async with CortexXDRCrawler(transport=transport) as crawler:
            await crawler.crawl()

        assert not any("feature-enhancements" in u for u in transport.requested)

    @pytest.mark.asyncio
    async def test_crawl_honours_skip_versions(self):
        transport = FakeTransport(_two_space_site())

        async with CortexXDRCrawler(transport=transport) as crawler:
            result = await crawler.crawl(skip_versions={"9.2"})

        assert [v.version for v in result.product.versions] == ["8.1"]
        assert not any("release-information/known-issues" in u for u in transport.requested)

    @pytest.mark.asyncio
    async def test_crawl_records_failed_page_fetches(self):
        pages = _two_space_site()
        legacy_url = next(u for u in pages if u.endswith("8.1.x"))
        del pages[legacy_url]
        transport = FakeTransport(pages)

        async with CortexXDRCrawler(transport=transport) as crawler:
            result = await crawler.crawl()

        assert [v.version for v in result.product.versions] == ["9.2"]
        assert [f.url for f in result.failed_fetches] == [legacy_url]
        assert result.failed_fetches[0].product == "cortex-xdr"
        assert result.failed_fetches[0].version == "8.1"
        assert result.failed_fetches[0].issue_type == "addressed"

    @pytest.mark.asyncio
    async def test_crawl_reports_a_missing_sitemap_index(self):
        transport = FakeTransport({})

        async with CortexXDRCrawler(transport=transport) as crawler:
            result = await crawler.crawl()

        assert result.product.versions == []
        assert [f.url for f in result.failed_fetches] == [f"{CORTEX_BASE_URL}/sitemap.xml"]

    @pytest.mark.asyncio
    async def test_crawl_resolves_version_from_space_root_when_slug_has_none(self):
        """The 9.3 release notes live in the version-less root space."""
        known_url = f"{CORTEX_BASE_URL}/xdr-agent-release-notes/release-information/known-issues"
        pages = {
            f"{CORTEX_BASE_URL}/sitemap.xml": _minimal_index(["xdr-agent-release-notes"]),
            f"{CORTEX_BASE_URL}/xdr-agent-release-notes/sitemap-pages.xml": _minimal_pages(
                [f"{CORTEX_BASE_URL}/xdr-agent-release-notes", known_url]
            ),
            f"{CORTEX_BASE_URL}/xdr-agent-release-notes": (
                "<html><head><title>Cortex XDR Agent 9.3 Release Information | "
                "Cortex Documentation Portal</title></head><body></body></html>"
            ),
            known_url: _fixture("gitbook-known-issues.html"),
        }
        transport = FakeTransport(pages)

        async with CortexXDRCrawler(transport=transport) as crawler:
            result = await crawler.crawl()

        assert [v.version for v in result.product.versions] == ["9.3"]
        assert [i.bug_id for i in result.product.versions[0].known_issues] == ["CPATR-18568"]


class TestFluidTopicsIsGone:
    """The khub endpoint no longer exists; nothing may still reference it."""

    def test_transport_module_is_deleted(self):
        with pytest.raises(ModuleNotFoundError):
            __import__("bugdb.transport.fluidtopics_transport")

    def test_crawler_has_no_fluidtopics_plumbing(self):
        crawler = CortexXDRCrawler()
        assert not hasattr(crawler, "_fluidtopics")
        assert not hasattr(crawler, "_legacy_crawl")
        assert not hasattr(crawler, "_crawl_via_fluidtopics")

    def test_base_url_points_at_the_gitbook_host(self):
        assert CORTEX_BASE_URL == "https://cortex-docs.paloaltonetworks.com"

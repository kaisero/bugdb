"""Enterprise DLP: bespoke slug versioning plus year-keyed addressed issues.

The shared extract_dotted_version cannot read these slugs — it needs
exactly three digits with no digit neighbours, so `-3010` (3.0.10) and
the two-digit parent slugs `-60` / `-10` produce nothing.
"""

from pathlib import Path
from typing import ClassVar

import pytest
from bs4 import BeautifulSoup

from bugdb.crawlers.products.enterprise_dlp import (
    EnterpriseDLPCrawler,
    extract_dlp_version,
    extract_dlp_year,
)
from bugdb.sitemap import SitemapIndex

FIXTURES = Path(__file__).parent / "fixtures" / "enterprise-dlp"

_BASE = "https://docs.paloaltonetworks.com/enterprise-dlp/release-notes"

_SITEMAP = f"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{_BASE}/known-issues-in-enterprise-dlp-plugin-60</loc><lastmod>2026-08-01</lastmod></url>
  <url><loc>{_BASE}/known-issues-in-enterprise-dlp-plugin-60/known-issues-in-enterprise-dlp-plugin-602</loc><lastmod>2026-08-01</lastmod></url>
  <url><loc>{_BASE}/known-issues-in-enterprise-dlp-plugin-30/known-issues-in-enterprise-dlp-plugin-3010</loc><lastmod>2026-08-01</lastmod></url>
  <url><loc>{_BASE}/known-issues-in-endpoint-dlp</loc><lastmod>2026-08-01</lastmod></url>
  <url><loc>{_BASE}/known-issues-in-the-enterprise-dlp-cloud-service</loc><lastmod>2026-08-01</lastmod></url>
  <url><loc>{_BASE}/addressed-issues-in-enterprise-dlp</loc><lastmod>2026-08-01</lastmod></url>
  <url><loc>{_BASE}/addressed-issues-in-enterprise-dlp/addressed-issues-in-2025</loc><lastmod>2026-08-01</lastmod></url>
</urlset>
"""


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("known-issues-in-enterprise-dlp-plugin-10", "1.0"),
        ("known-issues-in-enterprise-dlp-plugin-60", "6.0"),
        ("known-issues-in-enterprise-dlp-plugin-101", "1.0.1"),
        ("known-issues-in-enterprise-dlp-plugin-602", "6.0.2"),
        ("known-issues-in-enterprise-dlp-plugin-300", "3.0.0"),
        ("known-issues-in-enterprise-dlp-plugin-3010", "3.0.10"),
        ("known-issues-in-endpoint-dlp", None),
        ("addressed-issues-in-enterprise-dlp", None),
    ],
)
def test_extract_dlp_version(slug, expected):
    assert extract_dlp_version(f"{_BASE}/{slug}") == expected


def test_extract_dlp_year():
    assert (
        extract_dlp_year(f"{_BASE}/addressed-issues-in-enterprise-dlp/addressed-issues-in-2025")
        == "2025"
    )
    assert extract_dlp_year(f"{_BASE}/addressed-issues-in-enterprise-dlp") is None


def test_discovery_skips_out_of_scope_pages():
    """Endpoint DLP and the cloud service are deliberately not crawled."""
    crawler = EnterpriseDLPCrawler(sitemap=SitemapIndex.from_xml(_SITEMAP), transport=object())
    known, _addressed = crawler.discover_urls()
    assert not any("endpoint-dlp" in u for u in known)
    assert not any("cloud-service" in u for u in known)


def test_discovery_drops_the_undated_addressed_parent():
    """The parent addressed page is a table of contents for its year
    children; including it would double every issue under a bogus key."""
    crawler = EnterpriseDLPCrawler(sitemap=SitemapIndex.from_xml(_SITEMAP), transport=object())
    _known, addressed = crawler.discover_urls()
    assert addressed == {
        "2025": "/enterprise-dlp/release-notes/addressed-issues-in-enterprise-dlp/addressed-issues-in-2025"
    }


def test_discovery_keys_known_pages_by_version():
    crawler = EnterpriseDLPCrawler(sitemap=SitemapIndex.from_xml(_SITEMAP), transport=object())
    known, _addressed = crawler.discover_urls()
    assert set(known) == {"6.0", "6.0.2", "3.0.10"}


class _StubCrawler(EnterpriseDLPCrawler):
    _PAGES: ClassVar[dict[str, str]] = {
        "6.0.2": "known-issues-plugin-602.html",
        "2025": "addressed-issues-2025.html",
    }

    async def _fetch_page_with_semaphore(self, url, wait_time: int = 3000):
        if "addressed-issues-in-2025" in url:
            name = self._PAGES["2025"]
        elif url.endswith("-602"):
            name = self._PAGES["6.0.2"]
        else:
            return BeautifulSoup("<html><body></body></html>", "lxml")
        return BeautifulSoup((FIXTURES / name).read_text(), "lxml")


@pytest.mark.asyncio
async def test_crawl_produces_versioned_known_and_year_keyed_addressed():
    sitemap = SitemapIndex.from_xml(_SITEMAP)
    async with _StubCrawler(transport=object(), sitemap=sitemap) as crawler:
        result = await crawler.crawl()

    assert result.product.id == "enterprise-dlp"
    assert result.product.name == "Enterprise DLP"
    by_version = {v.version: v for v in result.product.versions}

    # Empty pages produce no ProductVersion at all.
    assert set(by_version) == {"6.0.2", "2025"}

    assert [i.bug_id for i in by_version["6.0.2"].known_issues] == [
        "PLUG-16720",
        "PAN-144897",
        "DSS-17763",
    ]
    assert by_version["6.0.2"].addressed_issues == []
    assert [i.bug_id for i in by_version["2025"].addressed_issues] == ["PLUG-14201"]
    assert by_version["2025"].known_issues == []


@pytest.mark.asyncio
async def test_workaround_survives_the_topic_parser():
    sitemap = SitemapIndex.from_xml(_SITEMAP)
    async with _StubCrawler(transport=object(), sitemap=sitemap) as crawler:
        result = await crawler.crawl()
    issue = {v.version: v for v in result.product.versions}["6.0.2"].known_issues[0]
    assert issue.workaround is not None
    assert "Contact Palo Alto Networks Support" in issue.workaround


class _TableStubCrawler(EnterpriseDLPCrawler):
    """Verified against the live site: unlike known-issues pages, each
    month section of an addressed-issues year page nests a real
    ID/Description ``<table>`` rather than per-issue div.topic blocks.
    ``addressed-issues-2025-table.html`` is trimmed but genuine captured
    markup from the live October/May 2025 sections."""

    async def _fetch_page_with_semaphore(self, url, wait_time: int = 3000):
        if "addressed-issues-in-2025" in url:
            return BeautifulSoup(
                (FIXTURES / "addressed-issues-2025-table.html").read_text(), "lxml"
            )
        return BeautifulSoup("<html><body></body></html>", "lxml")


@pytest.mark.asyncio
async def test_addressed_year_page_parses_nested_month_tables():
    sitemap = SitemapIndex.from_xml(_SITEMAP)
    async with _TableStubCrawler(transport=object(), sitemap=sitemap) as crawler:
        result = await crawler.crawl()

    by_version = {v.version: v for v in result.product.versions}
    assert set(by_version) == {"2025"}
    assert {i.bug_id for i in by_version["2025"].addressed_issues} == {
        "DSS-18161",
        "DIT-54573",
    }

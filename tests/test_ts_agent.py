"""TS Agent lives inside the /pan-os/ tree and must not disturb it.

Two verified upstream layouts:
  10.x -> separate known/addressed URLs, per-patch <h2> sections
  11.x -> one combined page, per-patch <h2>"...Release Information" wrappers
          each containing an <h3> "Known Issues" or
          "TS Agent 11.0.N Addressed Issues" section.
"""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from bugdb.crawlers.products.ts_agent import TSAgentCrawler
from bugdb.sitemap import SitemapIndex

FIXTURES = Path(__file__).parent / "fixtures" / "ts-agent"

_TS = "https://docs.paloaltonetworks.com/pan-os"
_ADDRESSED_10_2 = (
    f"{_TS}/10-2/terminal-services-agent-release-notes/"
    "terminal-services-ts-agent-10-2-release-information/"
    "terminal-services-ts-agent-10-2-addressed-issues"
)
_KNOWN_10_2 = (
    f"{_TS}/10-2/terminal-services-agent-release-notes/"
    "terminal-services-ts-agent-10-2-release-information/known-issues-in-ts-agent-10-2"
)
_COMBINED_11_0 = (
    f"{_TS}/11-0/terminal-services-agent-release-notes/"
    "terminal-services-ts-agent-release-information/"
    "terminal-services-ts-agent-release-information-11-0"
)
_PANOS_CORE = f"{_TS}/10-2/pan-os-release-notes/pan-os-10-2-4-known-issues"

_SITEMAP = f"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{_ADDRESSED_10_2}</loc><lastmod>2026-08-01</lastmod></url>
  <url><loc>{_KNOWN_10_2}</loc><lastmod>2026-08-01</lastmod></url>
  <url><loc>{_COMBINED_11_0}</loc><lastmod>2026-08-01</lastmod></url>
  <url><loc>{_PANOS_CORE}</loc><lastmod>2026-08-01</lastmod></url>
</urlset>
"""


def test_ts_agent_urls_still_classify_as_panos():
    """The approved scope keeps the WINAGENT bugs under panos too, so
    TS Agent must NOT get a _PRODUCT_PREFIXES entry."""
    sitemap = SitemapIndex.from_xml(_SITEMAP)
    entry = next(e for e in sitemap.all_entries() if e.url == _ADDRESSED_10_2)
    assert entry.product_id == "panos"


def test_discovery_finds_the_11_x_page_that_has_no_issue_marker():
    """`...-release-information-11-0` contains no known/addressed token,
    so is_issue_page is False and for_product() would never yield it."""
    sitemap = SitemapIndex.from_xml(_SITEMAP)
    entry = next(e for e in sitemap.all_entries() if e.url == _COMBINED_11_0)
    assert entry.is_issue_page is False

    crawler = TSAgentCrawler(sitemap=sitemap, transport=object())
    assert any("release-information-11-0" in u for u in crawler.discover_urls())


def test_discovery_excludes_panos_core_pages():
    crawler = TSAgentCrawler(sitemap=SitemapIndex.from_xml(_SITEMAP), transport=object())
    assert not any("pan-os-release-notes" in u for u in crawler.discover_urls())


class _StubCrawler(TSAgentCrawler):
    async def _fetch_page_with_semaphore(self, url, wait_time: int = 3000):
        if "10-2-addressed-issues" in url:
            name = "10-2-addressed-issues.html"
        elif "release-information-11-0" in url:
            name = "11-0-release-information.html"
        else:
            return BeautifulSoup("<html><body></body></html>", "lxml")
        return BeautifulSoup((FIXTURES / name).read_text(), "lxml")


async def _crawl():
    sitemap = SitemapIndex.from_xml(_SITEMAP)
    async with _StubCrawler(transport=object(), sitemap=sitemap) as crawler:
        return await crawler.crawl()


@pytest.mark.asyncio
async def test_product_identity():
    result = await _crawl()
    assert result.product.id == "ts-agent"
    assert result.product.name == "Terminal Server Agent"


@pytest.mark.asyncio
async def test_10_x_issues_are_keyed_to_the_patch_from_the_h2():
    by_version = {v.version: v for v in (await _crawl()).product.versions}
    assert [i.bug_id for i in by_version["10.2.2"].addressed_issues] == ["WINAGENT-890"]


@pytest.mark.asyncio
async def test_patch_sections_with_no_table_produce_no_version():
    """10.2.4 and 10.2.0 say 'no updates or addressed issues'."""
    by_version = {v.version: v for v in (await _crawl()).product.versions}
    assert "10.2.4" not in by_version
    assert "10.2.0" not in by_version


@pytest.mark.asyncio
async def test_11_x_known_issues_fall_back_to_the_major():
    """The <h3>Known Issues</h3> heading carries no patch number."""
    by_version = {v.version: v for v in (await _crawl()).product.versions}
    assert [i.bug_id for i in by_version["11.0"].known_issues] == ["WINAGENT-1200"]
    assert by_version["11.0"].addressed_issues == []


@pytest.mark.asyncio
async def test_11_x_addressed_issues_are_keyed_to_the_patch():
    by_version = {v.version: v for v in (await _crawl()).product.versions}
    assert [i.bug_id for i in by_version["11.0.4"].addressed_issues] == ["WINAGENT-1150"]


@pytest.mark.asyncio
async def test_features_introduced_table_is_not_parsed_as_issues():
    """'New Feature | Description' has no issue column, so it yields
    nothing. Guards against a future header-matching change."""
    all_ids = [
        i.bug_id
        for v in (await _crawl()).product.versions
        for i in v.known_issues + v.addressed_issues
    ]
    assert "11.0.0" not in [v.version for v in (await _crawl()).product.versions]
    assert all(i.startswith("WINAGENT-") for i in all_ids)

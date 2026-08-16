"""AI Access Security: known page is a table, addressed page is div.topic.

Verified upstream 2026-08-16 — the two pages of the same product use
different markup, so the SaaS fetch helper needs both parsers.
"""

from pathlib import Path
from typing import ClassVar

import pytest
from bs4 import BeautifulSoup

from bugdb.crawlers.products.saas import AIAccessSecurityCrawler
from bugdb.crawlers.sitemap_discovery import discover_saas_urls
from bugdb.sitemap import SitemapIndex

FIXTURES = Path(__file__).parent / "fixtures" / "ai-access-security"

_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.paloaltonetworks.com/ai-access-security/release-notes/known-issues</loc><lastmod>2026-08-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/ai-access-security/release-notes/addressed-issues</loc><lastmod>2026-08-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/ai-runtime-security/release-notes/known-issues</loc><lastmod>2026-08-01</lastmod></url>
</urlset>
"""


def test_sitemap_classifies_ai_access_security_separately_from_ai_runtime():
    sitemap = SitemapIndex.from_xml(_SITEMAP)
    known, addressed = discover_saas_urls(sitemap, "ai-access-security")
    assert known == ["/ai-access-security/release-notes/known-issues"]
    assert addressed == ["/ai-access-security/release-notes/addressed-issues"]


class _StubCrawler(AIAccessSecurityCrawler):
    """Serve the fixtures instead of the network."""

    _PAGES: ClassVar[dict[str, str]] = {
        "/ai-access-security/release-notes/known-issues": "known-issues.html",
        "/ai-access-security/release-notes/addressed-issues": "addressed-issues.html",
    }

    async def _fetch_page_with_semaphore(self, url, wait_time: int = 3000):
        return BeautifulSoup((FIXTURES / self._PAGES[url]).read_text(), "lxml")


@pytest.mark.asyncio
async def test_crawl_reads_both_page_shapes():
    sitemap = SitemapIndex.from_xml(_SITEMAP)
    async with _StubCrawler(transport=object(), sitemap=sitemap) as crawler:
        result = await crawler.crawl()

    assert result.failed_fetches == []
    assert result.product.id == "ai-access-security"
    assert result.product.name == "AI Access Security"
    assert len(result.product.versions) == 1

    version = result.product.versions[0]
    assert version.version == "SaaS"
    assert [i.bug_id for i in version.known_issues] == ["NETVIS-2039"]
    assert [i.bug_id for i in version.addressed_issues] == [
        "NETVIS-2045",
        "NETVIS-1973",
        "NETVIS-1825",
    ]

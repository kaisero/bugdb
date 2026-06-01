"""Tests for sitemap-driven Prisma Access Agent discovery.

Prisma Access Agent puts the version inside the URL slug, NOT as a
path segment:
  /prisma-access-agent/release-notes/.../prisma-access-agent-26-2-1-known-issues

Two failure points:

1. `bugdb.sitemap._MAJOR_VERSION_RE` looks for `/X-Y/`. The slug-form
   version means `e.major_version` is None for every URL, so
   `discover_versions_from_sitemap` (which buckets by major) returns
   the empty list and the crawler never iterates.

2. `extract_dotted_version` doesn't match `26-2` in a slug like
   `prisma-access-agent-26-2-known-issues` — none of the existing
   fallbacks anchor on the issue marker.

Both are fixed: a custom `discover_versions_from_sitemap` on
PrismaAccessAgentCrawler that derives majors from the extracted
version, plus a new "before-issue-marker" fallback in
`extract_dotted_version`.
"""

import pytest

from bugdb.crawlers.products.prisma_access_agent import (
    PrismaAccessAgentCrawler,
)
from bugdb.crawlers.sitemap_discovery import extract_dotted_version
from bugdb.sitemap import SitemapIndex

_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.paloaltonetworks.com/prisma-access-agent/release-notes/prisma-access-agent-release-information/prisma-access-agent-known-issues</loc></url>
  <url><loc>https://docs.paloaltonetworks.com/prisma-access-agent/release-notes/prisma-access-agent-release-information/prisma-access-agent-known-issues/prisma-access-agent-26-2-1-known-issues</loc></url>
  <url><loc>https://docs.paloaltonetworks.com/prisma-access-agent/release-notes/prisma-access-agent-release-information/prisma-access-agent-known-issues/prisma-access-agent-26-2-known-issues</loc></url>
  <url><loc>https://docs.paloaltonetworks.com/prisma-access-agent/release-notes/prisma-access-agent-release-information/prisma-access-agent-addressed-issues/prisma-access-agent-26-2-1-addressed-issues</loc></url>
</urlset>
"""


# ============================================================
# extract_dotted_version must handle 2-dashed-before-marker too
# ============================================================


@pytest.mark.parametrize(
    "url,expected",
    [
        # Triple still wins
        (
            "/prisma-access-agent/.../prisma-access-agent-26-2-1-known-issues",
            "26.2.1",
        ),
        # 2-dashed-before-marker is the new case
        (
            "/prisma-access-agent/.../prisma-access-agent-26-2-known-issues",
            "26.2.0",
        ),
        # And for addressed-issues marker
        (
            "/prisma-access-agent/.../prisma-access-agent-26-2-addressed-issues",
            "26.2.0",
        ),
    ],
)
def test_extract_dotted_version(url: str, expected: str):
    assert extract_dotted_version(url) == expected


# ============================================================
# Crawler-level: must discover at least 1 version
# ============================================================


def _crawler() -> PrismaAccessAgentCrawler:
    c = PrismaAccessAgentCrawler.__new__(PrismaAccessAgentCrawler)
    c._sitemap = SitemapIndex.from_xml(_SITEMAP)
    c._manifest = None
    return c


def test_discover_versions_from_sitemap_returns_major_minor():
    """Should produce ['26-2'] from the slug-encoded versions."""
    assert _crawler().discover_versions_from_sitemap() == ["26-2"]


def test_discover_version_pages_from_sitemap_finds_all_minor_pages():
    """For major 26-2, both 26.2.1 and 26.2.0 (the bare 26-2) should appear."""
    vis = _crawler().discover_version_pages_from_sitemap("26-2")
    versions = {vi.version for vi in vis}
    # The 26-2-1 URLs map to 26.2.1; the 26-2 URLs map to 26.2.0
    assert "26.2.1" in versions
    assert "26.2.0" in versions


# ============================================================
# Addressed-issues index page: parse H2-grouped tables
# ============================================================

_INDEX_HTML = """
<html><body>
<h2>Issues Addressed in Prisma Access Agent 26.2</h2>
<table>
  <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
  <tbody>
    <tr><td>PAA-1</td><td>fixed a thing in 26.2</td></tr>
    <tr><td>PAA-2</td><td>another fix in 26.2</td></tr>
  </tbody>
</table>

<h2>Issues Addressed in Prisma Access Agent 26.1.1</h2>
<table>
  <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
  <tbody>
    <tr><td>PAA-3</td><td>fix from 26.1.1</td></tr>
  </tbody>
</table>

<h2>Some unrelated heading</h2>
<p>not a table</p>
</body></html>
"""


def test_parse_addressed_index_groups_tables_by_h2_version():
    """The index page interleaves <h2> headings with <table>s; each
    table belongs to the version named in the preceding heading."""
    from bs4 import BeautifulSoup

    c = _crawler()
    soup = BeautifulSoup(_INDEX_HTML, "lxml")
    by_version = c._parse_addressed_index_by_version(soup)
    assert set(by_version.keys()) == {"26.2", "26.1.1"}
    assert {i.bug_id for i in by_version["26.2"]} == {"PAA-1", "PAA-2"}
    assert {i.bug_id for i in by_version["26.1.1"]} == {"PAA-3"}

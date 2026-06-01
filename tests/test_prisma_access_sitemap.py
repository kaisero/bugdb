"""Tests for sitemap-driven Prisma Access discovery.

Prisma Access sitemap URLs put a 2-digit major-minor version in the
path segment: `/prisma-access/release-notes/4-0/.../...-known-issues`.
The dashed-triple regex doesn't match `4-0`, and the run-together
regex needs 3 digits, so `extract_dotted_version` silently returned
None and group_into_version_infos dropped every URL. Result: 0
versions for Prisma Access. Adding a 2-dashed fallback (X-Y → X.Y.0)
recovers the data.
"""

import pytest

from bugdb.crawlers.sitemap_discovery import (
    discover_version_pages,
    extract_dotted_version,
)
from bugdb.sitemap import SitemapIndex


_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.paloaltonetworks.com/prisma-access/release-notes/4-0/prisma-access-about/prisma-access-known-issues</loc></url>
  <url><loc>https://docs.paloaltonetworks.com/prisma-access/release-notes/4-0/prisma-access-about/prisma-access-addressed-issues</loc></url>
  <url><loc>https://docs.paloaltonetworks.com/prisma-access/release-notes/5-2/prisma-access-about/prisma-access-known-issues</loc></url>
  <url><loc>https://docs.paloaltonetworks.com/prisma-access/release-notes/6-0/prisma-access-about/prisma-access-known-issues</loc></url>
  <url><loc>https://docs.paloaltonetworks.com/prisma/prisma-access/3-2/prisma-access-panorama-release-notes/prisma-access-about/prisma-access-known-issues</loc></url>
</urlset>
"""


@pytest.mark.parametrize(
    "url,expected",
    [
        # The main regression case
        (
            "/prisma-access/release-notes/4-0/prisma-access-about/prisma-access-known-issues",
            "4.0.0",
        ),
        (
            "/prisma-access/release-notes/5-2/prisma-access-about/prisma-access-known-issues",
            "5.2.0",
        ),
        # The Panorama-managed Prisma Access still uses 2-digit segments
        (
            "/prisma/prisma-access/3-2/prisma-access-panorama-release-notes/prisma-access-about/prisma-access-known-issues",
            "3.2.0",
        ),
        # Triple form should still win over the 2-dashed fallback when both appear
        (
            "/foo/5-2/bar/baz-5-2-1-known-issues",
            "5.2.1",
        ),
    ],
)
def test_extract_dotted_version_handles_two_dashed(url: str, expected: str):
    assert extract_dotted_version(url) == expected


def test_extract_dotted_version_still_returns_none_for_no_match():
    assert extract_dotted_version("/no/version/here") is None


def test_discover_version_pages_for_prisma_access():
    sm = SitemapIndex.from_xml(_SITEMAP)
    vis = discover_version_pages(sm, "prisma-access")
    versions = {vi.version for vi in vis}
    # Every dashed-pair URL must contribute a version
    assert "4.0.0" in versions
    assert "5.2.0" in versions
    assert "6.0.0" in versions

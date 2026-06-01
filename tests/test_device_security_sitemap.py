"""Tests for sitemap-driven device-security discovery.

The legacy `DeviceSecurityCrawler.discover_years` probes the index URL
`/iot/iot-security-release-notes`, which now 404s. The new docs layout
is `/iot/release-notes/known-issues/known-issues-in-YYYY` and
`/iot/release-notes/addressed-issues/addressed-issues-in-YYYY`. Those
URLs are in the sitemap. The crawler now discovers years from sitemap.
"""

from bugdb.crawlers.products.device_security import DeviceSecurityCrawler
from bugdb.sitemap import SitemapIndex

_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.paloaltonetworks.com/iot/release-notes/known-issues</loc></url>
  <url><loc>https://docs.paloaltonetworks.com/iot/release-notes/known-issues/known-issues-in-2025</loc><lastmod>2025-03-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/iot/release-notes/addressed-issues</loc></url>
  <url><loc>https://docs.paloaltonetworks.com/iot/release-notes/addressed-issues/addressed-issues-in-2025</loc><lastmod>2025-03-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/iot/release-notes/addressed-issues/addressed-issues-in-2026</loc><lastmod>2026-04-01</lastmod></url>
  <!-- Network discovery plugin URLs must NOT be treated as device-security years -->
  <url><loc>https://docs.paloaltonetworks.com/iot/release-notes/network-discovery-plugin-for-panorama/network-discovery-plugin-3-1-0/known-issues-in-network-discovery-plugin-3-1-0</loc></url>
</urlset>
"""


def _crawler() -> DeviceSecurityCrawler:
    c = DeviceSecurityCrawler.__new__(DeviceSecurityCrawler)
    c._sitemap = SitemapIndex.from_xml(_SITEMAP)
    c._manifest = None
    return c


def test_discover_years_from_sitemap_returns_newest_first():
    assert _crawler().discover_years_from_sitemap() == ["2026", "2025"]


def test_discover_years_from_sitemap_ignores_network_discovery_plugin():
    """The Network Discovery plugin lives under the same /iot/ path but
    uses semantic versions (3.1.0), not years."""
    years = _crawler().discover_years_from_sitemap()
    assert "3" not in years and "1" not in years and "0" not in years


def test_discover_year_pages_from_sitemap_pairs_known_and_addressed():
    known, addressed = _crawler().discover_year_pages_from_sitemap("2025")
    assert known is not None and "known-issues-in-2025" in known
    assert addressed is not None and "addressed-issues-in-2025" in addressed


def test_discover_year_pages_from_sitemap_year_with_only_addressed():
    """2026 has only an addressed-issues page in the sample sitemap."""
    known, addressed = _crawler().discover_year_pages_from_sitemap("2026")
    assert known is None
    assert addressed is not None and "addressed-issues-in-2026" in addressed


def test_discover_years_from_sitemap_returns_empty_without_sitemap():
    c = DeviceSecurityCrawler.__new__(DeviceSecurityCrawler)
    c._sitemap = None
    c._manifest = None
    assert c.discover_years_from_sitemap() == []

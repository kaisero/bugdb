"""Tests for sitemap-driven PAN-OS discovery."""

from bugdb.crawlers.products.panos import PANOSCrawler
from bugdb.fetch_manifest import FetchManifest, ManifestEntry
from bugdb.sitemap import SitemapIndex


_XML = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues</loc><lastmod>2026-03-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-addressed-issues</loc><lastmod>2026-03-02</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-4-known-and-addressed-issues/pan-os-11-2-4-known-issues</loc><lastmod>2026-04-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/pan-os/12-1/pan-os-release-notes/pan-os-12-1-1-known-and-addressed-issues/pan-os-12-1-1-known-issues</loc><lastmod>2026-05-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/features-introduced-in-pan-os</loc><lastmod>2026-02-01</lastmod></url>
</urlset>
"""


def _crawler(sitemap=None, manifest=None) -> PANOSCrawler:
    c = PANOSCrawler.__new__(PANOSCrawler)
    c._sitemap = sitemap
    c._manifest = manifest
    return c


def test_discover_versions_from_sitemap_returns_newest_first():
    c = _crawler(sitemap=SitemapIndex.from_xml(_XML))
    assert c.discover_versions_from_sitemap() == ["12-1", "11-2"]


def test_discover_versions_from_sitemap_empty_when_no_sitemap():
    c = _crawler(sitemap=None)
    assert c.discover_versions_from_sitemap() == []


def test_discover_version_pages_groups_by_version():
    c = _crawler(sitemap=SitemapIndex.from_xml(_XML))
    vis = c.discover_version_pages_from_sitemap("11-2")
    versions = {vi.version for vi in vis}
    assert versions == {"11.2.3", "11.2.4"}


def test_discover_version_pages_separates_known_and_addressed():
    c = _crawler(sitemap=SitemapIndex.from_xml(_XML))
    vis = c.discover_version_pages_from_sitemap("11-2")
    by_ver = {vi.version: vi for vi in vis}
    assert any(
        "pan-os-11-2-3-known-issues" in u for u in by_ver["11.2.3"].known_issues_urls
    )
    assert any(
        "pan-os-11-2-3-addressed-issues" in u
        for u in by_ver["11.2.3"].addressed_issues_urls
    )
    # 11.2.4 only has a known-issues URL in this fixture
    assert any(
        "pan-os-11-2-4-known-issues" in u for u in by_ver["11.2.4"].known_issues_urls
    )


def test_discover_version_pages_skips_urls_when_manifest_matches_lastmod():
    manifest = FetchManifest(
        entries={
            "https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues": ManifestEntry(
                lastmod="2026-03-01"
            ),
        }
    )
    c = _crawler(sitemap=SitemapIndex.from_xml(_XML), manifest=manifest)
    vis = c.discover_version_pages_from_sitemap("11-2")
    flat = [u for v in vis for u in v.known_issues_urls + v.addressed_issues_urls]
    assert not any("11-2-3-known-issues" in u for u in flat)
    # Addressed page for 11.2.3 still present because its lastmod differs.
    assert any("11-2-3-addressed-issues" in u for u in flat)


def test_discover_version_pages_does_not_skip_when_lastmod_changed():
    manifest = FetchManifest(
        entries={
            "https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues": ManifestEntry(
                lastmod="2025-01-01"
            ),
        }
    )
    c = _crawler(sitemap=SitemapIndex.from_xml(_XML), manifest=manifest)
    vis = c.discover_version_pages_from_sitemap("11-2")
    flat = [u for v in vis for u in v.known_issues_urls + v.addressed_issues_urls]
    assert any("11-2-3-known-issues" in u for u in flat)

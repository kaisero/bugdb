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


# Real upstream layout for PAN-OS 12.1+. Palo Alto moved the release
# notes off `/pan-os/<v>/pan-os-release-notes` onto the shared NGFW book
# at `/ngfw/release-notes/<v>`; the legacy path now 404s for 12.x. The
# fixture above still uses the legacy shape for 12-1, which is why the
# suite stayed green while the real crawl returned zero 12.x versions —
# these URLs are copied verbatim from docs.paloaltonetworks.com/sitemap.xml.
_NGFW_XML = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.paloaltonetworks.com/ngfw/release-notes/12-1/pan-os-12-1-8-known-and-addressed-issues/pan-os-12-1-8-known-issues</loc><lastmod>2026-07-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/ngfw/release-notes/12-1/pan-os-12-1-8-known-and-addressed-issues/pan-os-12-1-8-addressed-issues</loc><lastmod>2026-07-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/ngfw/release-notes/12-2/pan-os-12-2-2-known-and-addressed-issues/pan-os-12-2-2-known-issues</loc><lastmod>2026-07-15</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/ngfw/release-notes/12-2/pan-os-12-2-2-known-and-addressed-issues/pan-os-12-2-2-addressed-issues</loc><lastmod>2026-07-15</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/ngfw/release-notes/known-issues</loc><lastmod>2026-07-20</lastmod></url>
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
    assert any("pan-os-11-2-3-known-issues" in u for u in by_ver["11.2.3"].known_issues_urls)
    assert any(
        "pan-os-11-2-3-addressed-issues" in u for u in by_ver["11.2.3"].addressed_issues_urls
    )
    # 11.2.4 only has a known-issues URL in this fixture
    assert any("pan-os-11-2-4-known-issues" in u for u in by_ver["11.2.4"].known_issues_urls)


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


# --- PAN-OS 12.x on the NGFW book -------------------------------------
# Regression cover for the bug where every 12.x version was silently
# absent from the crawl: `_PRODUCT_PREFIXES["panos"]` only matched
# `/pan-os/`, so the ~36 issue URLs under `/ngfw/release-notes/`
# classified as product_id=None and no PAN-OS crawler ever saw them.


def test_ngfw_hosted_majors_are_discovered():
    """12.1+ live on the NGFW book, not the legacy /pan-os/ path."""
    c = _crawler(sitemap=SitemapIndex.from_xml(_NGFW_XML))
    assert c.discover_versions_from_sitemap() == ["12-2", "12-1"]


def test_ngfw_hosted_version_pages_are_grouped():
    c = _crawler(sitemap=SitemapIndex.from_xml(_NGFW_XML))
    vis = c.discover_version_pages_from_sitemap("12-1")
    by_ver = {vi.version: vi for vi in vis}
    assert set(by_ver) == {"12.1.8"}
    assert any("pan-os-12-1-8-known-issues" in u for u in by_ver["12.1.8"].known_issues_urls)
    assert any(
        "pan-os-12-1-8-addressed-issues" in u for u in by_ver["12.1.8"].addressed_issues_urls
    )


def test_unversioned_ngfw_landing_does_not_become_a_version():
    """`/ngfw/release-notes/known-issues` has no version — must not leak in."""
    c = _crawler(sitemap=SitemapIndex.from_xml(_NGFW_XML))
    assert "known-issues" not in c.discover_versions_from_sitemap()
    for major in c.discover_versions_from_sitemap():
        for vi in c.discover_version_pages_from_sitemap(major):
            assert vi.version[0].isdigit()

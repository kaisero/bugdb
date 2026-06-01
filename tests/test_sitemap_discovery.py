"""Tests for the shared sitemap_discovery helpers."""

from bugdb.crawlers.sitemap_discovery import (
    discover_major_versions,
    discover_version_pages,
    extract_dotted_version,
    filter_unchanged,
    group_into_version_infos,
    to_relative_path,
)
from bugdb.fetch_manifest import FetchManifest, ManifestEntry
from bugdb.sitemap import SitemapIndex


def test_extract_dotted_version_handles_plain_triple():
    assert (
        extract_dotted_version("https://docs.paloaltonetworks.com/.../pan-os-11-2-3-known-issues")
        == "11.2.3"
    )


def test_extract_dotted_version_keeps_hotfix_suffix():
    assert (
        extract_dotted_version(
            "https://docs.paloaltonetworks.com/.../globalprotect-app-6-2-8-h9-known-issues"
        )
        == "6.2.8-h9"
    )


def test_extract_dotted_version_excludes_known_or_addressed_as_suffix():
    # "11-2-3-known-issues" -> "11.2.3", not "11.2.3-known"
    assert extract_dotted_version("/pan-os-11-2-3-known-issues") == "11.2.3"


def test_extract_dotted_version_returns_none_when_no_match():
    assert extract_dotted_version("/no-numbers-here") is None


def test_to_relative_path_strips_docs_base_and_html():
    assert (
        to_relative_path("https://docs.paloaltonetworks.com/pan-os/11-2/x.html") == "/pan-os/11-2/x"
    )


def test_to_relative_path_passes_through_other_hosts():
    assert (
        to_relative_path("https://other/example", "https://docs.paloaltonetworks.com")
        == "https://other/example"
    )


def test_filter_unchanged_keeps_all_when_no_manifest():
    sitemap = SitemapIndex.from_xml(
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/x-known-issues</loc>"
        "<lastmod>2026-01-01</lastmod></url></urlset>"
    )
    entries = list(sitemap.issue_urls())
    assert filter_unchanged(entries, manifest=None) == entries


def test_filter_unchanged_drops_url_whose_lastmod_matches_manifest():
    sitemap = SitemapIndex.from_xml(
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/x-known-issues</loc>"
        "<lastmod>2026-01-01</lastmod></url></urlset>"
    )
    entries = list(sitemap.issue_urls())
    manifest = FetchManifest(
        entries={
            "https://docs.paloaltonetworks.com/pan-os/11-2/x-known-issues": ManifestEntry(
                lastmod="2026-01-01"
            )
        }
    )
    assert filter_unchanged(entries, manifest=manifest) == []


def test_group_into_version_infos_buckets_known_and_addressed():
    sitemap = SitemapIndex.from_xml(
        """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/.../pan-os-11-2-3-known-issues</loc></url>
          <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/.../pan-os-11-2-3-addressed-issues</loc></url>
        </urlset>"""
    )
    vis = group_into_version_infos(list(sitemap.issue_urls()))
    assert len(vis) == 1
    vi = vis[0]
    assert vi.version == "11.2.3"
    assert len(vi.known_issues_urls) == 1
    assert len(vi.addressed_issues_urls) == 1


def test_group_into_version_infos_handles_combined_known_and_addressed_page():
    sitemap = SitemapIndex.from_xml(
        """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://docs.paloaltonetworks.com/globalprotect/6-2/x/globalprotect-app-6-2-8-known-and-addressed-issues</loc></url>
        </urlset>"""
    )
    vis = group_into_version_infos(list(sitemap.issue_urls()))
    assert len(vis) == 1
    assert len(vis[0].known_issues_urls) == 1
    assert len(vis[0].addressed_issues_urls) == 1


def test_discover_major_versions_returns_sorted_newest_first():
    sitemap = SitemapIndex.from_xml(
        """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/.../pan-os-11-2-3-known-issues</loc></url>
          <url><loc>https://docs.paloaltonetworks.com/pan-os/12-1/.../pan-os-12-1-1-known-issues</loc></url>
          <url><loc>https://docs.paloaltonetworks.com/pan-os/10-2/.../pan-os-10-2-9-known-issues</loc></url>
        </urlset>"""
    )
    assert discover_major_versions(sitemap, "panos") == ["12-1", "11-2", "10-2"]


def test_discover_version_pages_filters_to_major_version():
    sitemap = SitemapIndex.from_xml(
        """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/.../pan-os-11-2-3-known-issues</loc></url>
          <url><loc>https://docs.paloaltonetworks.com/pan-os/12-1/.../pan-os-12-1-1-known-issues</loc></url>
        </urlset>"""
    )
    vis_11 = discover_version_pages(sitemap, "panos", major_version="11-2")
    assert {vi.version for vi in vis_11} == {"11.2.3"}
    vis_12 = discover_version_pages(sitemap, "panos", major_version="12-1")
    assert {vi.version for vi in vis_12} == {"12.1.1"}


def test_discover_version_pages_returns_empty_when_sitemap_is_none():
    assert discover_version_pages(None, "panos") == []

"""Tests for the PAN-OS landing-page double-fetch regression.

For each PAN-OS minor version the sitemap lists THREE URLs:
- .../pan-os-11-2-3-known-and-addressed-issues               (landing, zero tables)
- .../pan-os-11-2-3-known-and-addressed-issues/...-known-issues
- .../pan-os-11-2-3-known-and-addressed-issues/...-addressed-issues

group_into_version_infos was putting the landing into BOTH the known
and addressed URL lists, causing 2 useless fetches per minor (~300
extra HTTP calls per full run). Fix: when a sibling URL with a
more-specific known/addressed suffix exists for the same version,
drop the landing from that bucket. Only keep the landing if no
sibling exists.
"""

from bugdb.crawlers.sitemap_discovery import group_into_version_infos
from bugdb.sitemap import SitemapIndex


_SITEMAP_PANOS = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/x/pan-os-11-2-3-known-and-addressed-issues</loc></url>
  <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/x/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues</loc></url>
  <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/x/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-addressed-issues</loc></url>
</urlset>
"""


def test_landing_page_is_dropped_when_known_subpage_exists():
    sm = SitemapIndex.from_xml(_SITEMAP_PANOS)
    vis = group_into_version_infos(list(sm.issue_urls()))
    assert len(vis) == 1
    vi = vis[0]
    # Both buckets contain only the SPECIFIC subpage, not the landing.
    assert len(vi.known_issues_urls) == 1
    assert all("11-2-3-known-issues" in u for u in vi.known_issues_urls)
    assert len(vi.addressed_issues_urls) == 1
    assert all("11-2-3-addressed-issues" in u for u in vi.addressed_issues_urls)
    # No URL still has the bare "known-and-addressed-issues" suffix
    all_urls = vi.known_issues_urls + vi.addressed_issues_urls
    for u in all_urls:
        last_seg = u.rsplit("/", 1)[-1]
        assert last_seg != "pan-os-11-2-3-known-and-addressed-issues"


_SITEMAP_LANDING_ONLY = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.paloaltonetworks.com/globalprotect/6-2/x/globalprotect-app-6-2-8-known-and-addressed-issues</loc></url>
</urlset>
"""


def test_landing_page_is_kept_when_no_sibling_subpages():
    """If a version has ONLY a known-and-addressed URL (e.g. GlobalProtect
    older minor versions), keep it in both buckets."""
    sm = SitemapIndex.from_xml(_SITEMAP_LANDING_ONLY)
    vis = group_into_version_infos(list(sm.issue_urls()))
    assert len(vis) == 1
    vi = vis[0]
    assert len(vi.known_issues_urls) == 1
    assert len(vi.addressed_issues_urls) == 1


_SITEMAP_KNOWN_ONLY = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/x/pan-os-11-2-3-known-and-addressed-issues</loc></url>
  <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/x/pan-os-11-2-3-known-and-addressed-issues/pan-os-11-2-3-known-issues</loc></url>
</urlset>
"""


def test_landing_page_is_dropped_from_known_only_when_known_sibling_exists():
    """When the version has a specific known subpage but no addressed
    subpage, the landing should be dropped from `known_issues_urls`
    but KEPT in `addressed_issues_urls` (as a best-effort fallback)."""
    sm = SitemapIndex.from_xml(_SITEMAP_KNOWN_ONLY)
    vis = group_into_version_infos(list(sm.issue_urls()))
    assert len(vis) == 1
    vi = vis[0]
    # Known: just the specific subpage
    assert len(vi.known_issues_urls) == 1
    assert all("pan-os-11-2-3-known-issues" in u for u in vi.known_issues_urls)
    # Addressed: only the landing (because no specific addressed subpage exists)
    assert len(vi.addressed_issues_urls) == 1
    assert any("known-and-addressed" in u for u in vi.addressed_issues_urls)

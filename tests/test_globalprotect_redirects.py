"""Tests for the GlobalProtect sitemap-prefix narrowing fix.

The sitemap lists 84 stale-but-redirecting URLs under
'/globalprotect/<ver>/globalprotect-app-release-notes/...' alongside
91 canonical URLs under '/globalprotect/release-notes/<ver>/...'. The
stale URLs 301-redirect to the canonical layout, so every request to
them costs an extra round-trip — and the destination is the same page
that the canonical sitemap entry already requests.

Narrowing _PRODUCT_PREFIXES['globalprotect'] to '/globalprotect/release-notes/'
makes the stale URLs not classified as a GlobalProtect entry at all,
so they're skipped entirely.
"""

from bugdb.sitemap import SitemapIndex


_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <!-- canonical (200) layout -->
  <url><loc>https://docs.paloaltonetworks.com/globalprotect/release-notes/6-3/known-issues-related-to-gp-app/globalprotect-6-3-2-known-issues</loc></url>
  <!-- stale (301) layout -->
  <url><loc>https://docs.paloaltonetworks.com/globalprotect/6-3/globalprotect-app-release-notes/known-issues-related-to-gp-app/globalprotect-6-3-2-known-issues</loc></url>
</urlset>
"""


def test_stale_globalprotect_url_not_classified():
    sm = SitemapIndex.from_xml(_SITEMAP)
    entries = list(sm.for_product("globalprotect"))
    assert len(entries) == 1
    assert "/globalprotect/release-notes/" in entries[0].url
    assert "/globalprotect-app-release-notes/" not in entries[0].url

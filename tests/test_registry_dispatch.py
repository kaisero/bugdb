"""Regression tests for dispatch_async + shared-transport lifecycle.

These guard against the failure mode where one shared `httpx.AsyncClient`
is created in event loop L_main, but each per-product call goes through
`asyncio.to_thread(sync_wrapper)` → `asyncio.run(_async)`, which spawns a
new loop per product. httpx then sees its connection-pool primitives
attached to a dead loop and raises `RuntimeError: Event loop is closed`
on every product after the first.

The fix is to await the async helpers directly inside one event loop.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from bugdb.crawlers.registry import dispatch_async
from bugdb.transport.httpx_transport import HttpxDocsTransport

_OK_HTML = """<html><body>
<table>
  <thead><tr><th>Issue ID</th><th>Description</th></tr></thead>
  <tbody><tr><td>PAN-1</td><td>desc</td></tr></tbody>
</table>
</body></html>"""

_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/x/pan-os-11-2-3-known-issues</loc><lastmod>2026-04-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/x/pan-os-11-2-3-addressed-issues</loc><lastmod>2026-04-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/ai-runtime-security/release-notes/known-issues</loc><lastmod>2026-04-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/ai-runtime-security/release-notes/addressed-issues</loc><lastmod>2026-04-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/strata-logging-service/release-notes/known-issues</loc><lastmod>2026-04-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/strata-logging-service/release-notes/addressed-issues</loc><lastmod>2026-04-01</lastmod></url>
</urlset>"""


@pytest.mark.asyncio
@respx.mock
async def test_dispatch_async_shares_one_transport_across_products():
    """Regression for "Event loop is closed" on every product after the first.

    Builds one shared HttpxDocsTransport in the test's event loop and
    dispatches three products through it sequentially. They must all
    succeed because dispatch_async stays in the same event loop.
    """
    # Mock all docs responses
    respx.get(host="docs.paloaltonetworks.com").mock(
        return_value=httpx.Response(200, text=_OK_HTML)
    )

    from bugdb.sitemap import SitemapIndex

    sitemap = SitemapIndex.from_xml(_SITEMAP)
    transport = HttpxDocsTransport(concurrency=2)
    try:
        # adem, ai-runtime-security, panos — three different products,
        # one shared transport. None of them may fail with "Event loop is closed".
        for prod_id in ("panos", "ai-runtime-security", "strata-logging-service"):
            result = await dispatch_async(
                prod_id,
                None,
                transport=transport,
                sitemap=sitemap,
            )
            # No FailedFetch entries means no fetches errored out.
            assert result.failed_fetches == [], (
                f"{prod_id}: unexpected failed fetches: {[f.error for f in result.failed_fetches]}"
            )
    finally:
        await transport.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_dispatch_async_routes_unknown_product_to_keyerror():
    with pytest.raises(KeyError):
        await dispatch_async("does-not-exist")


@pytest.mark.asyncio
@respx.mock
async def test_dispatch_async_routes_plugin_via_plugin_helper():
    """plugin-* keys go through _crawl_plugin_async, not the main dispatch."""
    respx.get(host="docs.paloaltonetworks.com").mock(
        return_value=httpx.Response(200, text=_OK_HTML)
    )
    from bugdb.sitemap import SitemapIndex

    sitemap = SitemapIndex.from_xml(_SITEMAP)
    transport = HttpxDocsTransport(concurrency=2)
    try:
        # Even with an empty sitemap, this should not raise.
        result = await dispatch_async(
            "plugin-aws",
            None,
            transport=transport,
            sitemap=sitemap,
        )
        assert result.database.products[0].id == "plugin-aws"
    finally:
        await transport.aclose()

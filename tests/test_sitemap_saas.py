"""Tests for the discover_saas_urls helper."""

from bugdb.crawlers.sitemap_discovery import discover_saas_urls
from bugdb.fetch_manifest import FetchManifest, ManifestEntry
from bugdb.sitemap import SitemapIndex

_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.paloaltonetworks.com/ai-runtime-security/release-notes/known-issues</loc><lastmod>2026-04-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/ai-runtime-security/release-notes/addressed-issues</loc><lastmod>2026-04-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/cloud-ngfw-aws/release-notes/cloud-ngfw-for-aws-known-issues</loc><lastmod>2026-04-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/cloud-ngfw-azure/release-notes/cloud-ngfw-for-azure-known-issues</loc><lastmod>2026-04-01</lastmod></url>
  <url><loc>https://docs.paloaltonetworks.com/cloud-ngfw-azure/release-notes/cloud-ngfw-for-azure-addressed-issues</loc><lastmod>2026-04-01</lastmod></url>
</urlset>
"""


def test_discover_saas_urls_finds_ai_runtime_security():
    sitemap = SitemapIndex.from_xml(_SITEMAP)
    known, addressed = discover_saas_urls(sitemap, "ai-runtime-security")
    assert any("ai-runtime-security/release-notes/known-issues" in u for u in known)
    assert any("ai-runtime-security/release-notes/addressed-issues" in u for u in addressed)


def test_discover_saas_urls_uses_correct_cloud_ngfw_aws_prefix():
    """Cloud NGFW for AWS lives under /cloud-ngfw-aws/ on the docs site
    (the old code's `/cloud-ngfw/aws/` prefix produces 404s)."""
    sitemap = SitemapIndex.from_xml(_SITEMAP)
    known, _addressed = discover_saas_urls(sitemap, "cloud-ngfw-aws")
    assert any("cloud-ngfw-aws/release-notes/cloud-ngfw-for-aws-known-issues" in u for u in known)


def test_discover_saas_urls_finds_cloud_ngfw_azure():
    sitemap = SitemapIndex.from_xml(_SITEMAP)
    known, addressed = discover_saas_urls(sitemap, "cloud-ngfw-azure")
    assert any(
        "cloud-ngfw-azure/release-notes/cloud-ngfw-for-azure-known-issues" in u for u in known
    )
    assert any(
        "cloud-ngfw-azure/release-notes/cloud-ngfw-for-azure-addressed-issues" in u
        for u in addressed
    )


def test_discover_saas_urls_returns_empty_when_no_sitemap():
    assert discover_saas_urls(None, "ai-runtime-security") == ([], [])


def test_discover_saas_urls_honours_manifest_skip():
    sitemap = SitemapIndex.from_xml(_SITEMAP)
    manifest = FetchManifest(
        entries={
            "https://docs.paloaltonetworks.com/ai-runtime-security/release-notes/known-issues": ManifestEntry(
                lastmod="2026-04-01"
            )
        }
    )
    known, addressed = discover_saas_urls(sitemap, "ai-runtime-security", manifest=manifest)
    assert known == []
    assert any("ai-runtime-security/release-notes/addressed-issues" in u for u in addressed)

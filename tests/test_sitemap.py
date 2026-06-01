"""Tests for SitemapIndex."""

from pathlib import Path

from bugdb.sitemap import SitemapIndex

FIXTURE = Path(__file__).parent / "fixtures" / "sitemap-sample.xml"


def test_parse_extracts_all_entries():
    idx = SitemapIndex.from_xml(FIXTURE.read_text())
    assert len(idx.all_entries()) == 4


def test_issue_urls_filters_only_known_or_addressed_pages():
    idx = SitemapIndex.from_xml(FIXTURE.read_text())
    urls = {e.url for e in idx.issue_urls()}
    assert any("pan-os-11-2-3-known-issues" in u for u in urls)
    assert any("pan-os-11-2-3-addressed-issues" in u for u in urls)
    assert any("globalprotect-app-6-2-8-known-and-addressed-issues" in u for u in urls)
    assert not any("features-introduced-in-pan-os" in u for u in urls)


def test_classify_by_product_prefix_matches_panos():
    idx = SitemapIndex.from_xml(FIXTURE.read_text())
    panos = list(idx.for_product("panos"))
    assert len(panos) == 2
    assert all("/pan-os/" in e.url for e in panos)


def test_classify_by_product_prefix_matches_globalprotect():
    idx = SitemapIndex.from_xml(FIXTURE.read_text())
    gp = list(idx.for_product("globalprotect"))
    assert len(gp) == 1
    assert "/globalprotect/" in gp[0].url


def test_extract_major_version_from_url():
    idx = SitemapIndex.from_xml(FIXTURE.read_text())
    entries = list(idx.for_product("panos"))
    versions = {e.major_version for e in entries}
    assert versions == {"11-2"}


def test_lastmod_is_parsed():
    idx = SitemapIndex.from_xml(FIXTURE.read_text())
    e = next(iter(idx.for_product("globalprotect")))
    assert e.lastmod == "2026-04-15"


def test_unknown_product_returns_empty_iterator():
    idx = SitemapIndex.from_xml(FIXTURE.read_text())
    assert list(idx.for_product("does-not-exist")) == []


def test_handles_entry_without_lastmod():
    xml = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://docs.paloaltonetworks.com/pan-os/11-2/pan-os-release-notes/known-issues</loc></url>
    </urlset>"""
    idx = SitemapIndex.from_xml(xml)
    e = next(iter(idx.issue_urls()))
    assert e.lastmod is None

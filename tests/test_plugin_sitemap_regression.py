"""Regression tests for the plugin sitemap-discovery regressions.

The sitemap-driven plugin discovery silently dropped most plugins:
- Azure / Cisco ACI / Cisco TrustSec / GCP / Kubernetes / vCenter had URLs
  whose version slug uses the run-together "522" form instead of "5-2-2".
  `extract_dotted_version` only handled the dashed form, so version
  extraction returned None and these plugins contributed 0 versions.
- VMware NSX and ZTP had wrong product prefixes in
  `bugdb.sitemap._PRODUCT_PREFIXES`, so SitemapIndex.for_product returned
  no entries at all.
- sdwan-plugin had wrong prefixes too (currently uses legacy path so it
  hadn't surfaced, but is fixed defensively).
"""

import pytest

from bugdb.crawlers.sitemap_discovery import (
    discover_version_pages,
    extract_dotted_version,
)
from bugdb.sitemap import SitemapIndex


# Sample of real plugin URLs covering every regression case.
_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <!-- Azure: run-together 3-digit version "522" -->
  <url><loc>https://docs.paloaltonetworks.com/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-azure/azure-plugin-522/known-issues-in-the-panorama-plugin-for-azure-522</loc></url>
  <url><loc>https://docs.paloaltonetworks.com/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-azure/azure-plugin-522/addressed-issues-in-the-panorama-plugin-for-azure-522</loc></url>
  <!-- Cisco ACI: run-together "203" -->
  <url><loc>https://docs.paloaltonetworks.com/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-cisco-aci/cisco-aci-plugin-203/known-issues-in-panorama-plugin-for-cisco-aci-203</loc></url>
  <!-- GCP: run-together "312" -->
  <url><loc>https://docs.paloaltonetworks.com/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-gcp/panorama-plugin-for-gcp-312/addressed-issues-in-panorama-plugin-for-gcp-312</loc></url>
  <!-- Kubernetes: run-together "303" -->
  <url><loc>https://docs.paloaltonetworks.com/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-kubernetes/panorama-plugin-for-kubernetes-303/known-issues-in-kubernetes-plugin-303</loc></url>
  <!-- AWS: BOTH a dashed-version URL and a run-together one -->
  <url><loc>https://docs.paloaltonetworks.com/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-aws/panorama-plugin-for-aws-5-4-1/addressed-issues-in-panorama-plugin-for-aws-5-4-1</loc></url>
  <url><loc>https://docs.paloaltonetworks.com/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-aws/aws-plugin-534/addressed-issues-in-panorama-plugin-for-aws-5-3-4</loc></url>
  <!-- NSX: prefix uses "vmware-nsx", was wrongly classified as None -->
  <url><loc>https://docs.paloaltonetworks.com/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-vmware-nsx/vmware-nsx-plugin-502/known-issues-in-panorama-plugin-for-vmware-nsx-502</loc></url>
  <!-- ZTP: prefix uses "panorama-plugin-for-zero-touch-provisioning" -->
  <url><loc>https://docs.paloaltonetworks.com/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-zero-touch-provisioning/panorama-plugin-for-zero-touch-provisioning-30/known-issues-in-zero-touch-provisioning-301</loc></url>
  <!-- SDWAN: prefix is panorama-plugin-for-sd-wan -->
  <url><loc>https://docs.paloaltonetworks.com/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-sd-wan/sd-wan-plugin-340/known-issues-in-sd-wan-plugin-340</loc></url>
</urlset>
"""


def _sm() -> SitemapIndex:
    return SitemapIndex.from_xml(_SITEMAP)


# ============================================================
# extract_dotted_version: must handle run-together digits
# ============================================================

@pytest.mark.parametrize(
    "url,expected",
    [
        # Run-together 3-digit (the main regression)
        (
            "/plugins/.../azure-plugin-522/known-issues-in-the-panorama-plugin-for-azure-522",
            "5.2.2",
        ),
        (
            "/plugins/.../panorama-plugin-for-gcp-312/addressed-issues-in-panorama-plugin-for-gcp-312",
            "3.1.2",
        ),
        (
            "/plugins/.../panorama-plugin-for-kubernetes-303/known-issues-in-kubernetes-plugin-303",
            "3.0.3",
        ),
        # Dashed (still works)
        (
            "/plugins/.../panorama-plugin-for-aws-5-4-1/addressed-issues",
            "5.4.1",
        ),
        # With hotfix suffix
        (
            "/plugins/.../vm-series-plugin-6-1-2-h1/addressed-issues",
            "6.1.2-h1",
        ),
    ],
)
def test_extract_dotted_version(url: str, expected: str):
    assert extract_dotted_version(url) == expected


def test_extract_dotted_version_prefers_dashed_form_when_both_present():
    """Some URLs contain BOTH the run-together segment AND a dashed version
    in the filename. The dashed form is canonical and must win."""
    url = (
        "/plugins/.../panorama-plugin-for-aws/aws-plugin-534/"
        "addressed-issues-in-panorama-plugin-for-aws-5-3-4"
    )
    assert extract_dotted_version(url) == "5.3.4"


# ============================================================
# discover_version_pages: must find every plugin's URLs
# ============================================================

@pytest.mark.parametrize(
    "product_id,expected_version",
    [
        ("plugin-azure", "5.2.2"),
        ("plugin-cisco-aci", "2.0.3"),
        ("plugin-gcp", "3.1.2"),
        ("plugin-kubernetes", "3.0.3"),
        ("plugin-aws", "5.4.1"),
        ("plugin-vmware-nsx", "5.0.2"),
        ("plugin-ztp", "3.0.1"),
        ("sdwan-plugin", "3.4.0"),
    ],
)
def test_discover_version_pages_finds_plugin(
    product_id: str, expected_version: str
):
    sm = _sm()
    vis = discover_version_pages(sm, product_id)
    versions = {vi.version for vi in vis}
    assert (
        expected_version in versions
    ), f"{product_id}: expected {expected_version} in {versions}"

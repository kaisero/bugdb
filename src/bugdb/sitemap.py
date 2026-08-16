"""Sitemap-driven URL discovery for bugdb.

The Palo Alto Networks documentation portals expose a `/sitemap.xml` with
every release-notes URL and a `<lastmod>` timestamp. Parsing the sitemap
once per run is dramatically cheaper than the JS-rendered version-index
crawl the legacy code does, and it also gives us a free incremental gate:
skip URLs whose `<lastmod>` matches the manifest entry from the last run.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from lxml import etree

logger = logging.getLogger(__name__)

# Map of product_id -> URL path substrings; an entry whose URL contains
# *any* substring belongs to that product. Mirrors `PRODUCT_CRAWLERS` keys
# in `bugdb.crawlers.registry`.
_PRODUCT_PREFIXES: dict[str, tuple[str, ...]] = {
    # PAN-OS release notes live in two places. Everything up to 11.2 sits
    # on the legacy `/pan-os/<v>/pan-os-release-notes` path. From 12.1
    # onward Palo Alto publishes them on the shared NGFW book at
    # `/ngfw/release-notes/<v>` and the legacy path 404s — so matching
    # only `/pan-os/` silently dropped every 12.x version.
    #
    # Pin to `/ngfw/release-notes/`, not `/ngfw/`: the sitemap carries
    # ~4700 other NGFW doc URLs (administration, api, networking, ...)
    # and only the release-notes subtree holds issue pages.
    "panos": ("/pan-os/", "/ngfw/release-notes/"),
    # The sitemap lists BOTH the canonical /globalprotect/release-notes/
    # layout (~91 URLs, 200 OK) and stale /globalprotect/<ver>/globalprotect-app-release-notes/
    # URLs (~84, 301-redirect to canonical). Pinning to /release-notes/
    # means the stale URLs aren't classified as a GlobalProtect entry,
    # saving ~250 redirected GETs per full fetch.
    "globalprotect": ("/globalprotect/release-notes/",),
    "prisma-access": ("/prisma-access/",),
    "prisma-access-agent": (
        "/gp-app-for-prisma-access/",
        "/prisma-access-agent/",
        "/prisma-access-app/",
    ),
    "prisma-sdwan": ("/prisma-sd-wan/",),
    # The docs site has been migrated from /cloud-ngfw/azure/* paths to
    # /cloud-ngfw-azure/* (dash, not slash). The sitemap still lists the
    # old paths but they 301-redirect — and the redirect for the
    # addressed-issues URL points at "What's New", which has no bug
    # tables. So we deliberately match ONLY the new paths.
    "cloud-ngfw-azure": ("/cloud-ngfw-azure/",),
    "cloud-ngfw-aws": ("/cloud-ngfw-aws/",),
    "remote-browser-isolation": ("/remote-browser-isolation/",),
    "ai-access-security": ("/ai-access-security/",),
    "ai-runtime-security": ("/ai-runtime-security/",),
    "strata-logging-service": ("/strata-logging-service/",),
    # The legacy `/iot/iot-security-release-notes` and `/iot-security/`
    # paths no longer serve issue pages (the index 404s). The current
    # docs live under `/iot/release-notes/`. The Network Discovery
    # plugin shares that path but uses semantic versions, so its URLs
    # are filtered out inside the DeviceSecurityCrawler.
    "device-security": ("/iot/release-notes/",),
    "enterprise-dlp": ("/enterprise-dlp/",),
    "adem": ("/autonomous-dem/",),
    "scm": ("/strata-cloud-manager/",),
    "sdwan-plugin": (
        # The sitemap uses "panorama-plugin-for-sd-wan" — the legacy
        # paths under /panorama/plugins/sd-wan/ no longer appear.
        "/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-sd-wan",
    ),
    "vm-series-plugin": ("/plugins/vm-series-and-panorama-plugins-release-notes/vm-series-plugin",),
    "plugin-aws": (
        "/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-aws",
    ),
    "plugin-azure": (
        "/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-azure",
    ),
    "plugin-gcp": (
        "/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-gcp",
    ),
    "plugin-vmware-nsx": (
        # Sitemap path includes "vmware-nsx", not just "nsx".
        "/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-vmware-nsx",
    ),
    "plugin-vmware-vcenter": (
        "/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-vmware-vcenter",
    ),
    "plugin-kubernetes": (
        "/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-kubernetes",
    ),
    "plugin-cisco-aci": (
        "/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-cisco-aci",
    ),
    "plugin-cisco-trustsec": (
        "/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-cisco-trustsec",
    ),
    "plugin-ztp": (
        # Sitemap path is "panorama-plugin-for-zero-touch-provisioning";
        # the legacy `/plugins/.../zero-touch-provisioning-ztp-plugin`
        # base URL no longer appears in the sitemap.
        "/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-zero-touch-provisioning",
    ),
    "plugin-clustering": (
        "/plugins/vm-series-and-panorama-plugins-release-notes/panorama-plugin-for-clustering",
    ),
}

_ISSUE_MARKERS = (
    "known-issues",
    "addressed-issues",
    "known-and-addressed",
    "fixed-issues",
    "known-issue",
    "addressed-issue",
)

# Major version pattern as it appears in URLs, e.g. "/11-2/" or "/6-2/".
_MAJOR_VERSION_RE = re.compile(r"/(\d+-\d+)(?:[/-]|$)")


@dataclass(frozen=True)
class SitemapEntry:
    """One `<url>` from the sitemap, with derived fields."""

    url: str
    lastmod: str | None
    product_id: str | None
    major_version: str | None
    is_issue_page: bool


@dataclass
class SitemapIndex:
    """In-memory index of a sitemap.xml document."""

    _entries: list[SitemapEntry] = field(default_factory=list)

    @classmethod
    def from_xml(cls, xml: str) -> SitemapIndex:
        root = etree.fromstring(xml.encode("utf-8"))
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        entries: list[SitemapEntry] = []
        for url_el in root.findall("s:url", ns):
            loc = url_el.findtext("s:loc", default="", namespaces=ns).strip()
            if not loc:
                continue
            lastmod = url_el.findtext("s:lastmod", default=None, namespaces=ns)
            entries.append(_classify(loc, lastmod))
        logger.debug("parsed sitemap: %d entries", len(entries))
        return cls(_entries=entries)

    def all_entries(self) -> list[SitemapEntry]:
        return list(self._entries)

    def issue_urls(self) -> Iterable[SitemapEntry]:
        return (e for e in self._entries if e.is_issue_page)

    def for_product(self, product_id: str) -> Iterable[SitemapEntry]:
        return (e for e in self._entries if e.is_issue_page and e.product_id == product_id)


def _classify(url: str, lastmod: str | None) -> SitemapEntry:
    lower = url.lower()
    product_id: str | None = None
    # Prefer the most-specific prefix match (longest).
    best_len = 0
    for pid, prefixes in _PRODUCT_PREFIXES.items():
        for p in prefixes:
            if p.lower() in lower and len(p) > best_len:
                product_id = pid
                best_len = len(p)
    is_issue_page = any(m in lower for m in _ISSUE_MARKERS)
    m = _MAJOR_VERSION_RE.search(url)
    major_version = m.group(1) if m else None
    return SitemapEntry(
        url=url,
        lastmod=lastmod.strip() if isinstance(lastmod, str) else lastmod,
        product_id=product_id,
        major_version=major_version,
        is_issue_page=is_issue_page,
    )

"""Shared helpers for sitemap-driven discovery used by product crawlers."""

from __future__ import annotations

import logging
import re
from typing import Optional

from bugdb.fetch_manifest import FetchManifest
from bugdb.sitemap import SitemapEntry, SitemapIndex

from .models import VersionInfo
from .utils import version_sort_key

logger = logging.getLogger(__name__)


# Regex matching a "1.2.3" or "1.2.3-h4" or "1.2.3-c471" version triple
# in a URL slug.  The legacy code uses several variants; this one is the
# union: three numeric segments followed by an optional "-<alphanum>".
_VERSION_TRIPLE_RE = re.compile(r"(\d+)-(\d+)-(\d+)(?:-([a-zA-Z0-9]+))?")
# Run-together 3-digit version (e.g. "azure-plugin-522" → 5.2.2).
# Many Panorama plugin slugs use this shape instead of the dashed form
# used by PAN-OS / GlobalProtect / VM-Series. Anchored against other
# digits on both sides only — a leading or trailing dash is fine (the
# slug shape is "-NNN/" or "-NNN-").
_VERSION_RUN_TOGETHER_RE = re.compile(r"(?<!\d)(\d)(\d)(\d)(?!\d)")
# 2-dashed version as a path segment (e.g. "/prisma-access/.../4-0/...").
# Used as a last-resort fallback for products whose URLs encode only
# major-minor (Prisma Access, Prisma Access Agent). Anchored on `/`
# boundaries so it doesn't match arbitrary `\d-\d` substrings inside
# slug names like `aws-plugin-534`.
_VERSION_TWO_DASHED_RE = re.compile(r"/(\d+)-(\d+)/")
# Page-type tokens we must NOT treat as a version suffix.
_NON_VERSION_SUFFIXES = {"known", "addressed", "issues", "and"}


def extract_dotted_version(url: str) -> Optional[str]:
    """Extract a 1.2.3[-suffix] version from a URL.

    The Palo Alto docs URLs use two distinct version slug shapes:
    - Dashed:        ".../pan-os-11-2-3-known-issues" → "11.2.3"
                     ".../globalprotect-app-6-2-8-h9-known-issues" → "6.2.8-h9"
    - Run-together:  ".../azure-plugin-522/..." → "5.2.2"
                     ".../panorama-plugin-for-kubernetes-303/..." → "3.0.3"

    When a URL contains BOTH shapes (e.g. AWS plugins which use a
    run-together slug segment plus a dashed filename), the dashed form is
    canonical and takes precedence — that's how the legacy
    `PluginCrawler.extract_version_from_url` resolved the same ambiguity.
    """
    # Prefer the dashed form. Take the rightmost match because filenames
    # typically end with the version (e.g. ".../...-5-3-4").
    matches = list(_VERSION_TRIPLE_RE.finditer(url))
    if matches:
        m = matches[-1]
        ver = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
        suffix = m.group(4)
        if suffix and suffix.lower() not in _NON_VERSION_SUFFIXES:
            ver += f"-{suffix}"
        return ver
    # Fall back to run-together 3-digit form for plugin slugs.
    matches = list(_VERSION_RUN_TOGETHER_RE.finditer(url))
    if matches:
        m = matches[-1]
        return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
    # Last resort: 2-dashed major-minor as a path segment. Used by Prisma
    # Access and Prisma Access Agent (e.g. ".../release-notes/4-0/...").
    # Returned as X.Y.0 since there's no patch component on the wire.
    matches = list(_VERSION_TWO_DASHED_RE.finditer(url))
    if matches:
        m = matches[-1]
        return f"{m.group(1)}.{m.group(2)}.0"
    return None


def to_relative_path(url: str, base: str = "https://docs.paloaltonetworks.com") -> str:
    """Strip the docs base URL and any trailing .html so existing parsers fit."""
    path = url.removeprefix(base)
    if path.endswith(".html"):
        path = path[:-5]
    return path


def filter_unchanged(
    entries: list[SitemapEntry],
    manifest: Optional[FetchManifest],
) -> list[SitemapEntry]:
    """Drop entries whose <lastmod> matches the manifest (incremental gate)."""
    if manifest is None:
        return entries
    out = []
    for e in entries:
        if manifest.should_skip(e.url, e.lastmod):
            logger.debug("manifest skip: %s", e.url)
            continue
        out.append(e)
    return out


def group_into_version_infos(
    entries: list[SitemapEntry],
) -> list[VersionInfo]:
    """Group sitemap entries by extracted dotted version into VersionInfo objects."""
    by_version: dict[str, VersionInfo] = {}
    for entry in entries:
        ver = extract_dotted_version(entry.url)
        if not ver:
            continue
        vi = by_version.setdefault(
            ver,
            VersionInfo(
                version=ver,
                known_issues_urls=[],
                addressed_issues_urls=[],
            ),
        )
        lower = entry.url.lower()
        path = to_relative_path(entry.url)
        if "known-and-addressed" in lower:
            if path not in vi.known_issues_urls:
                vi.known_issues_urls.append(path)
            if path not in vi.addressed_issues_urls:
                vi.addressed_issues_urls.append(path)
        elif "known" in lower and "addressed" not in lower:
            if path not in vi.known_issues_urls:
                vi.known_issues_urls.append(path)
        elif "addressed" in lower and "known" not in lower:
            if path not in vi.addressed_issues_urls:
                vi.addressed_issues_urls.append(path)
        elif "fixed" in lower:
            if path not in vi.addressed_issues_urls:
                vi.addressed_issues_urls.append(path)
    return sorted(
        by_version.values(),
        key=lambda v: version_sort_key(v.version),
        reverse=True,
    )


def discover_major_versions(
    sitemap: Optional[SitemapIndex], product_id: str
) -> list[str]:
    """Distinct `major-minor` strings present in the sitemap for a product, newest first."""
    if sitemap is None:
        return []
    versions = {
        e.major_version
        for e in sitemap.for_product(product_id)
        if e.major_version
    }
    return sorted(
        versions, key=lambda v: [int(x) for x in v.split("-")], reverse=True
    )


def discover_version_pages(
    sitemap: Optional[SitemapIndex],
    product_id: str,
    major_version: Optional[str] = None,
    manifest: Optional[FetchManifest] = None,
) -> list[VersionInfo]:
    """High-level helper: filtered, grouped, manifest-skipped VersionInfo list."""
    if sitemap is None:
        return []
    entries = [
        e
        for e in sitemap.for_product(product_id)
        if major_version is None or e.major_version == major_version
    ]
    entries = filter_unchanged(entries, manifest)
    return group_into_version_infos(entries)


def discover_saas_urls(
    sitemap: Optional[SitemapIndex],
    product_id: str,
    manifest: Optional[FetchManifest] = None,
) -> tuple[list[str], list[str]]:
    """Return (known_urls, addressed_urls) for a single-version SaaS product.

    Used by crawlers like AI Runtime Security, Cloud NGFW, RBI, and SLS that
    have no major-version concept — they simply have a small fixed set of
    known/addressed issue pages on the docs portal.

    URLs are returned as relative paths (no `https://docs.paloaltonetworks.com`
    prefix and no `.html` suffix) so they slot directly into existing
    `_parse_issues_page` calls.
    """
    if sitemap is None:
        return [], []
    entries = filter_unchanged(list(sitemap.for_product(product_id)), manifest)
    known: list[str] = []
    addressed: list[str] = []
    for e in entries:
        lower = e.url.lower()
        path = to_relative_path(e.url)
        if "known-and-addressed" in lower:
            if path not in known:
                known.append(path)
            if path not in addressed:
                addressed.append(path)
        elif "known" in lower and "addressed" not in lower:
            if path not in known:
                known.append(path)
        elif "addressed" in lower or "fixed" in lower:
            if path not in addressed:
                addressed.append(path)
    return known, addressed

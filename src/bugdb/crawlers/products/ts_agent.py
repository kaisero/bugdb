"""Terminal Server (TS) Agent crawler implementation.

The TS Agent release notes live inside the PAN-OS documentation tree at
``/pan-os/<major>/terminal-services-agent-release-notes/``. Those URLs
therefore already match ``_PRODUCT_PREFIXES["panos"]`` and are already
crawled as PAN-OS — the WINAGENT bugs currently show up under panos
10.1.0 / 10.2.0. That attribution is deliberately left in place, so this
crawler must NOT register a sitemap prefix of its own: ``_classify``
assigns exactly one product per URL, and adding one would move the data
out of PAN-OS.

Instead we scan ``sitemap.all_entries()`` directly. That is also the only
option for the 11.x pages, whose slugs
(``terminal-services-ts-agent-release-information-11-0``) contain no
known/addressed token, so ``SitemapEntry.is_issue_page`` is False and
neither ``for_product()`` nor ``issue_urls()`` would surface them.

Two upstream page layouts, handled by one section-walking parser. Both
were fetched and inspected live (2026-08-16) rather than trusted from
prior recon — the second one turned out to nest one level deeper than
originally assumed:

* **10.1 / 10.2** — separate known and addressed URLs. The addressed
  page is split by flat ``<h2>TS Agent 10.2.N Addressed Issues</h2>``
  siblings; most patch sections carry no table ("no updates or
  addressed issues"). The known-issues page currently carries no table
  at all (upstream says "There are no known issues...").
* **11.0 / 11.1** — one combined page per version. Live markup nests
  each patch under its own ``<h2>Terminal Server (TS) Agent 11.0.N
  Release Information</h2>`` wrapper, with an ``<h3>`` inside for
  "Known Issues" / "TS Agent 11.0.N Addressed Issues" / "Features
  Introduced in TS Agent 11.0.N". The section walker below only relies
  on document order, not nesting depth, so the extra ``<h2>`` layer
  doesn't matter — each ``<h3>`` still self-identifies its own version
  and kind. Header pluralization ("Issue"/"Description" vs.
  "Issues"/"Descriptions") varies even between sub-tables on the same
  page; :meth:`BaseCrawler._parse_issues_table` already handles both via
  substring matching.

Feature tables ("New Feature | Description") are ignored for free —
``_parse_issues_table`` requires an issue/bug/id column and returns an
empty list for them.
"""

from __future__ import annotations

import asyncio
import logging
import re

from bugdb.models import Issue, Product, ProductVersion

from ..base import BaseCrawler
from ..models import CrawlResult, FailedFetch
from ..sitemap_discovery import to_relative_path

logger = logging.getLogger(__name__)

# Every TS Agent page sits under this path segment. Used instead of a
# _PRODUCT_PREFIXES entry so PAN-OS keeps its existing classification.
_TREE_MARKER = "/terminal-services-agent-release-notes/"

# Pages that actually carry issues. The release-information pages are
# the 11.x combined layout; the other two are the 10.x split layout.
_ISSUE_PAGE_MARKERS = (
    "known-issues-in-ts-agent",
    "-addressed-issues",
    "terminal-services-ts-agent-release-information-",
)

# PAN-OS major encoded in the path, e.g. "/pan-os/10-2/" -> "10.2".
_MAJOR_RE = re.compile(r"/pan-os/(\d+)-(\d+)/")

# "TS Agent 10.2.2 Addressed Issues" -> the dotted version in the
# heading. Deliberately does NOT match "(TS) Agent" (the page-level
# "Terminal Server (TS) Agent 11.0.4 Release Information" wrapper
# heading) — that heading carries no useful version signal beyond what
# the nested <h3> already provides, and matching it would require
# threading through the parenthesis.
_HEADING_VERSION_RE = re.compile(r"TS\s*Agent\s+(\d+\.\d+(?:\.\d+)?)", re.IGNORECASE)

# Fallback URL set for the no-sitemap (Playwright) path.
_FALLBACK_URLS = (
    "/pan-os/10-1/terminal-services-agent-release-notes/"
    "terminal-services-ts-agent-10-1-release-information/known-issues-in-ts-agent-10-1",
    "/pan-os/10-1/terminal-services-agent-release-notes/"
    "terminal-services-ts-agent-10-1-release-information/"
    "terminal-services-ts-agent-10-1-addressed-issues",
    "/pan-os/10-2/terminal-services-agent-release-notes/"
    "terminal-services-ts-agent-10-2-release-information/known-issues-in-ts-agent-10-2",
    "/pan-os/10-2/terminal-services-agent-release-notes/"
    "terminal-services-ts-agent-10-2-release-information/"
    "terminal-services-ts-agent-10-2-addressed-issues",
    "/pan-os/11-0/terminal-services-agent-release-notes/"
    "terminal-services-ts-agent-release-information/"
    "terminal-services-ts-agent-release-information-11-0",
    "/pan-os/11-0/terminal-services-agent-release-notes/"
    "terminal-services-ts-agent-release-information/"
    "terminal-services-ts-agent-release-information-11-1",
)


class TSAgentCrawler(BaseCrawler):
    """Crawler for Terminal Server (TS) Agent release notes."""

    product_id = "ts-agent"
    product_name = "Terminal Server Agent"

    def discover_urls(self) -> list[str]:
        """Return relative paths of every TS Agent issue page.

        Scans ``all_entries()`` rather than ``for_product()`` — see the
        module docstring for both reasons.

        Deliberately ignores ``self._manifest``. Confirmed live: the
        shared manifest is a flat ``url -> lastmod`` map with no product
        dimension, and the PAN-OS crawler visits these exact URLs on
        every run (that's the whole point of the approved scope — the
        WINAGENT bugs are meant to appear under both products). By the
        time TS Agent's very first live fetch ran, PAN-OS had already
        recorded these URLs in the manifest, so honouring the gate here
        skipped every 10.x page and produced zero 10.x versions. Since
        PAN-OS will keep re-recording these URLs forever, that
        collision is permanent, not a one-time cold-start artifact —
        so this crawler always fetches its (small, fixed) URL set.
        """
        if self._sitemap is None:
            return list(_FALLBACK_URLS)

        paths: list[str] = []
        for entry in self._sitemap.all_entries():
            lower = entry.url.lower()
            if _TREE_MARKER not in lower:
                continue
            if not any(marker in lower for marker in _ISSUE_PAGE_MARKERS):
                continue
            path = to_relative_path(entry.url)
            if path not in paths:
                paths.append(path)
        if not paths:
            logger.warning("%s: discovery found nothing", self.product_name)
        return paths

    def _default_kind(self, url: str) -> str:
        """Issue type to assume before any heading says otherwise.

        The 10.x layout has one kind per URL; the 11.x combined layout
        announces both kinds via headings, and its first heading is
        always "Known Issues", so "known" is a safe default there too.
        """
        lower = url.lower()
        if "addressed" in lower or "fixed" in lower:
            return "addressed"
        return "known"

    def _major_from_url(self, url: str) -> str:
        """PAN-OS major as a dotted string, e.g. "10.2".

        The trailing ``-<major>-<minor>`` on the page's own slug (the
        11.x combined layout) identifies the document's subject
        version and is checked first. The ``/pan-os/<major>-<minor>/``
        ancestor path segment only says where the page is filed — the
        11.1 combined page, for instance, is filed under the 11-0 path
        tree, so that segment would misattribute it. Fall back to the
        path segment for the 10.x split layout, whose slugs carry no
        trailing version suffix.
        """
        m = re.search(r"release-information-(\d+)-(\d+)$", url)
        if m:
            return f"{m.group(1)}.{m.group(2)}"
        m = _MAJOR_RE.search(url)
        if m:
            return f"{m.group(1)}.{m.group(2)}"
        return ""

    def _parse_sections(self, soup, url: str) -> dict[tuple[str, str], list[Issue]]:
        """Walk headings and tables in document order.

        Returns ``{(version, kind): [Issue, ...]}``. A heading updates
        the current version (when it names one) and the current kind
        (when it says "known" or "addressed"/"fixed"); each subsequent
        top-level table is attributed to that pair. Nesting depth (the
        11.x page wraps each patch's <h3> inside its own <h2>) doesn't
        matter here — ``find_all`` with multiple tag names still walks
        in document order regardless of ancestry.
        """
        # The 11.x combined page nests its version in the slug, not in a
        # per-section heading, so seed both from the URL.
        current_version = self._major_from_url(url)
        current_kind = self._default_kind(url)
        sections: dict[tuple[str, str], list[Issue]] = {}

        for element in soup.find_all(["h1", "h2", "h3", "h4", "table"]):
            if element.name != "table":
                text = element.get_text(" ", strip=True)
                lower = text.lower()
                m = _HEADING_VERSION_RE.search(text)
                if m:
                    current_version = m.group(1)
                else:
                    # A kind-only heading ("Known Issues") applies to the
                    # page's own version, not to whatever patch section
                    # happened to come before it.
                    if "known" in lower or "addressed" in lower or "fixed" in lower:
                        current_version = self._major_from_url(url)
                if "known" in lower and "addressed" not in lower:
                    current_kind = "known"
                elif "addressed" in lower or "fixed" in lower:
                    current_kind = "addressed"
                continue

            if element.find_parent("table"):
                continue
            issues = self._parse_issues_table(element)
            if issues:
                sections.setdefault((current_version, current_kind), []).extend(issues)

        return sections

    async def _parse_page(self, url: str) -> dict[tuple[str, str], list[Issue]]:
        soup = await self._fetch_page_with_semaphore(url)
        return self._parse_sections(soup, url)

    async def crawl(
        self,
        major_versions: list[str] | None = None,
        skip_versions: set[str] | None = None,
    ) -> CrawlResult:
        """Crawl Terminal Server Agent release notes.

        Args:
            major_versions: Ignored — versions come from the sitemap.
            skip_versions: Version keys already present locally.

        Returns:
            CrawlResult with Product and any failed fetches.
        """
        skip_versions = skip_versions or set()
        failed_fetches: list[FailedFetch] = []

        urls = self.discover_urls()
        self._set_task_total(
            len(urls),
            f"{self.product_name}: fetching {len(urls)} pages"
            if urls
            else f"{self.product_name}: nothing new to fetch",
        )

        results = await asyncio.gather(*[self._parse_page(u) for u in urls], return_exceptions=True)

        by_version: dict[str, dict[str, list[Issue]]] = {}
        for url, result in zip(urls, results, strict=True):
            self._advance_task(f"{self.product_name}: {url.rsplit('/', 1)[-1]} done")
            if isinstance(result, Exception):
                logger.error("  Error fetching %s: %s", url, result)
                failed_fetches.append(
                    FailedFetch(
                        url=url,
                        error=str(result),
                        product=self.product_id,
                        issue_type=self._default_kind(url),
                    )
                )
                continue
            for (version, kind), issues in result.items():
                if not version or version in skip_versions:
                    continue
                bucket = by_version.setdefault(version, {"known": [], "addressed": []})
                bucket[kind].extend(issues)

        if failed_fetches:
            _, still_failed = await self._retry_failed_fetches_sequentially(failed_fetches)
            failed_fetches = still_failed

        product_versions = []
        for version, buckets in by_version.items():
            known = self._deduplicate_issues(buckets["known"])
            addressed = self._deduplicate_issues(buckets["addressed"])
            if known or addressed:
                product_versions.append(
                    ProductVersion(
                        version=version,
                        known_issues=known,
                        addressed_issues=addressed,
                    )
                )
                logger.info("  %s: %d known, %d addressed", version, len(known), len(addressed))

        product_versions.sort(key=lambda v: self._version_sort_key(v.version), reverse=True)

        return CrawlResult(
            product=Product(
                id=self.product_id,
                name=self.product_name,
                versions=product_versions,
            ),
            failed_fetches=failed_fetches,
        )
